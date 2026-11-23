"""LLM harness: local-first Ollama backend, typed JSON generation with repair.

Design rules:
- The model only fills typed slots. Control flow, retries, budget = Python.
- Bad JSON never kills a stage: validate -> repair prompt with the exact
  validation errors -> structured fallback error. Never a crash mid-run.
- Every call lands in the CostLedger with a prompt hash.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Type, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from .core import sha256_text
from .evaltypes import CostEntry, CostLedger

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class PromptLibrary:
    """Numbered prompts are committed artifacts, referenced by hash everywhere."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or PROMPTS_DIR

    def load(self, name: str) -> str:
        path = self.directory / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"prompt artifact missing: {path}")
        return path.read_text(encoding="utf-8")

    def render(self, name: str, **vars: str) -> tuple[str, str]:
        """Returns (rendered_prompt, sha256_of_template)."""
        template = self.load(name)
        rendered = template
        for key, val in vars.items():
            rendered = rendered.replace("{{" + key + "}}", str(val))
        leftover = re.findall(r"\{\{(\w+)\}\}", rendered)
        if leftover:
            raise ValueError(f"unfilled prompt variables {leftover} in {name}")
        return rendered, sha256_text(template)


class OllamaBackend:
    """Thin, inspectable HTTP client. No SDK magic between us and the model."""

    def __init__(self, host: str = "http://localhost:11434", model: str = "qwen2.5:7b-instruct",
                 embed_model: str = "nomic-embed-text", timeout: int = 240):
        self.host = host.rstrip("/")
        self.model = model
        self.embed_model = embed_model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            return requests.get(f"{self.host}/api/tags", timeout=3).status_code == 200
        except requests.RequestException:
            return False

    def generate(self, prompt: str, system: str | None = None, temperature: float = 0.2,
                 max_tokens: int = 2048) -> tuple[str, dict]:
        payload: dict = {
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens, "seed": 42},
        }
        if system:
            payload["system"] = system
        r = requests.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data.get("response", ""), {
            "prompt_eval_count": data.get("prompt_eval_count", 0),
            "eval_count": data.get("eval_count", 0),
        }

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            r = requests.post(f"{self.host}/api/embeddings",
                              json={"model": self.embed_model, "prompt": text[:8000]},
                              timeout=self.timeout)
            r.raise_for_status()
            vectors.append(r.json()["embedding"])
        return vectors


class StructuredGenError(RuntimeError):
    def __init__(self, message: str, raw: str, errors: list[str]):
        super().__init__(message)
        self.raw = raw
        self.errors = errors


def _extract_json(text: str) -> str:
    """Pull the outermost JSON object out of a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


class Harness:
    """Typed generation with the repair loop. This is the only door to the model."""

    def __init__(self, backend: OllamaBackend | None = None, ledger: CostLedger | None = None,
                 prompts: PromptLibrary | None = None):
        self.backend = backend or OllamaBackend()
        self.ledger = ledger or CostLedger()
        self.prompts = prompts or PromptLibrary()

    def _record(self, stage: str, prompt_sha: str, usage: dict, latency_ms: int) -> None:
        self.ledger.add(CostEntry(
            stage=stage, model=self.backend.model, prompt_sha=prompt_sha[:16],
            in_tokens=usage.get("prompt_eval_count", 0), out_tokens=usage.get("eval_count", 0),
            latency_ms=latency_ms,
        ))

    def ask_json(self, schema: Type[T], prompt: str, *, stage: str = "unknown",
                 system: str | None = None, prompt_sha: str = "ad-hoc",
                 max_repairs: int = 3, temperature: float = 0.2) -> T:
        """Generate -> validate -> repair-with-exact-errors -> fail loud, never crash."""
        sys_line = system or (
            "You are a precise extraction engine. You output ONLY valid JSON matching "
            "the requested schema. No prose, no markdown fences, no commentary."
        )
        repair_prompt = prompt
        last_raw, last_errors = "", ["no response"]
        for _attempt in range(max_repairs + 1):
            t0 = time.time()
            raw, usage = self.backend.generate(repair_prompt, system=sys_line, temperature=temperature)
            self._record(stage, prompt_sha, usage, int((time.time() - t0) * 1000))
            last_raw = raw
            candidate = _extract_json(raw)
            try:
                return schema.model_validate_json(candidate)
            except ValidationError as exc:
                last_errors = [f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()]
                schema_json = json.dumps(schema.model_json_schema(), indent=1)
                repair_prompt = (
                    f"Your previous JSON output was INVALID against this schema:\n{schema_json}\n\n"
                    f"PREVIOUS OUTPUT:\n{candidate[:3000]}\n\n"
                    f"VALIDATION ERRORS:\n- " + "\n- ".join(last_errors) + "\n\n"
                    "Return the CORRECTED complete JSON object only. Fix every listed error."
                )
        raise StructuredGenError(
            f"structured generation failed after {max_repairs} repairs at stage '{stage}'",
            last_raw, last_errors,
        )

    def ask_text(self, prompt: str, *, stage: str = "unknown", system: str | None = None,
                 prompt_sha: str = "ad-hoc", temperature: float = 0.4) -> str:
        t0 = time.time()
        raw, usage = self.backend.generate(prompt, system=system, temperature=temperature)
        self._record(stage, prompt_sha, usage, int((time.time() - t0) * 1000))
        return raw

    def yes_no(self, question: str, *, stage: str = "judge", prompt_sha: str = "ad-hoc") -> bool:
        """A single binary judgment — the atom the whole judge is built from."""
        out = self.ask_text(
            f"{question}\n\nAnswer with exactly one word: YES or NO.",
            stage=stage, prompt_sha=prompt_sha, temperature=0.0,
            system="You are a strict binary classifier. One word only: YES or NO.",
        )
        return out.strip().upper().startswith("Y")

