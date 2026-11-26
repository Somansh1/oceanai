"""Generic agent engine: definition-driven execution with the shared contract.

This is the ONLY execution path for produced agents — runner, judge and chat
CLI all use it, so what the judge tests is exactly what the user gets.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PureWindowsPath

from pydantic import BaseModel, Field

from ..llm import Harness, _extract_json
from ..retrieve import HybridIndex
from ..spec import AgentDefinition
from ..tools import REGISTRY


class AgentResponse:
    """Contract-enforced answer. Same shape the judge scores."""

    __slots__ = ("answer", "refused", "citations", "confidence", "retrieved_chunk_ids",
                 "raw", "tool_calls", "parse_failed")

    def __init__(self, answer: str, refused: bool, citations: list[str],
                 retrieved: list[str], raw: str = "", tool_calls: list[dict] | None = None,
                 confidence: float | None = None, parse_failed: bool = False):
        self.answer = answer
        self.refused = refused
        self.citations = citations
        self.confidence = confidence
        self.retrieved_chunk_ids = retrieved
        self.raw = raw
        self.tool_calls = tool_calls or []
        self.parse_failed = parse_failed


def _path_basename(path_str: str) -> str:
    """Extract filename across both Windows and POSIX path formats."""
    if "\\" in path_str or (len(path_str) > 1 and path_str[1] == ":"):
        return PureWindowsPath(path_str).name
    return Path(path_str).name


def _resolve_bound_csv(
    requested: str,
    allowed_files: list[str],
    run_dir: Path | None = None,
) -> str | None:
    """Resolve a requested CSV/XLSX path strictly within bound files (cross-OS portable)."""
    if not allowed_files:
        return requested
    req_name = _path_basename(requested) if requested else ""
    pkg_root = Path(__file__).resolve().parents[3]
    for f in allowed_files:
        fname = _path_basename(f)
        if requested == f or (req_name and req_name == fname):
            candidates: list[Path] = [Path(f), Path.cwd() / f, Path.cwd() / fname, pkg_root / f]
            if run_dir is not None:
                candidates.extend([
                    run_dir / f,
                    run_dir / fname,
                    run_dir.parent / "docs" / fname,
                ])
            for candidate in candidates:
                if candidate.is_file():
                    return str(candidate)
            if run_dir is not None and (run_dir.parent / "docs").is_dir():
                for match in (run_dir.parent / "docs").rglob(fname):
                    if match.is_file():
                        return str(match)
            return str(Path(f))
    if not requested and len(allowed_files) == 1:
        return _resolve_bound_csv(allowed_files[0], allowed_files, run_dir=run_dir)
    return None


def run_tool_loop(harness: Harness, definition: AgentDefinition,
                  question: str, context: str, max_calls: int = 2,
                  run_dir: Path | None = None) -> tuple[str, list[dict]]:
    """Let the agent request tools via TOOL: {json} lines; code executes them."""
    attachments = []
    allowed_csv_files: list[str] = []
    for t in definition.tools:
        tool = REGISTRY.get(t.name)
        if not tool:
            continue
        line = f"- {tool.name}: {tool.description}\n  call: {tool.usage}"
        files = (t.config or {}).get("files")
        if files:
            allowed_csv_files.extend(files)
            line += "\n  data files: " + ", ".join(files)
        attachments.append(line)
    attachments_text = "\n".join(attachments)
    transcript = ""
    calls: list[dict] = []
    for _ in range(max_calls):
        # ask only for a tool request or a final answer
        prompt = (
            "You have these tools available:\n" + attachments_text + "\n\n"
            "Choose exactly one:\n"
            "  TOOL: {\"tool\": ..., \"args\": {...}}   (request one tool call)\n"
            "  FINAL_SNIPPET: <brief answer given the context, or leave empty>\n\n"
            "Question: " + question + "\n\nRetrieved context:\n" + context[:4000] +
            ("\n\nTool results so far:\n" + transcript[-2000:] if transcript else "")
        )
        out = harness.ask_text(prompt, stage="tool_loop", temperature=0.1)
        m = re.search(r"TOOL:", out)
        if m:
            try:
                req = json.loads(_balanced_json(out[m.end():]))
                tool_name = str(req.get("tool", ""))
                tool = REGISTRY.get(tool_name)
                if tool is None or not any(tb.name == tool_name for tb in definition.tools):
                    transcript += f"\ntool {tool_name}: not attached or unknown"
                    calls.append({"tool": tool_name, "ok": False, "error": "not attached"})
                    continue
                args = dict(req.get("args", {}) or {})
                if tool.name == "csv_lookup" and allowed_csv_files:
                    resolved = _resolve_bound_csv(
                        str(args.get("file", "")), allowed_csv_files, run_dir=run_dir
                    )
                    if not resolved:
                        msg = f"error: file not in bound files ({allowed_csv_files})"
                        transcript += f"\n[csv_lookup] {msg}"
                        calls.append({"tool": "csv_lookup", "args": args, "result": msg})
                        continue
                    args["file"] = resolved
                result = tool.run(args)
                calls.append({"tool": tool.name, "args": args, "result": result[:400]})
                transcript += f"\n[{tool.name}] {result[:800]}"
            except json.JSONDecodeError:
                calls.append({"tool": "?", "ok": False, "error": "bad json"})
        else:
            fm = re.search(r"FINAL_SNIPPET:\s*(.*)", out, re.S)
            if fm:
                return fm.group(1).strip(), calls
            return out.strip()[:400], calls
    return transcript[-2000:] if transcript else "", calls


def _balanced_json(text: str) -> str:
    """Extract a balanced JSON object. The old non-greedy regex truncated
    nested args objects at the first closing brace — three tool calls in a
    row died as 'bad json' before this existed."""
    start = text.find("{")
    if start == -1:
        return text.strip()
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text[start:].strip()


class ContractAnswer(BaseModel):
    """The output contract as a schema — enforced by the repair loop, not by
    hopeful parsing. One '(unparseable)' case died to make this happen."""
    answer: str = ""
    refused: bool = False
    citations: list[str] = Field(default_factory=list)
    confidence: float | None = None


class ForgeAgent:
    """Loads ANY definition. Retrieval params, tools, prompt all come from data."""

    def __init__(self, harness: Harness, index: HybridIndex, definition: AgentDefinition,
                 run_dir: Path | None = None):
        self.harness = harness
        self.index = index
        self.definition = definition
        self.run_dir = run_dir

    def _embed_query(self, text: str) -> list[float] | None:
        if not self.definition.retrieval.hybrid or not self.index._dense_ready:
            return None
        if not self.harness.backend.available():
            return None
        try:
            return self.harness.backend.embed([text])[0]
        except Exception:
            return None

    def answer(self, question: str) -> AgentResponse:
        rcfg = self.definition.retrieval
        top_k = max(rcfg.top_k_dense, rcfg.top_k_sparse)
        qvec = self._embed_query(question)
        hits = self.index.query(
            question, vector=qvec, top_k=top_k,
            dense_k=rcfg.top_k_dense, sparse_k=rcfg.top_k_sparse,
            rrf_k=rcfg.rrf_k, hybrid=rcfg.hybrid, min_score=rcfg.min_score,
        )
        if rcfg.query_rewrite:
            rewritten = self.harness.ask_text(
                f"Rewrite this question as 4-8 concise search keywords:\n{question}",
                stage="query_rewrite", temperature=0.0,
            ).strip()
            if rewritten:
                qvec2 = self._embed_query(rewritten)
                hits2 = self.index.query(
                    rewritten, vector=qvec2, top_k=top_k,
                    dense_k=rcfg.top_k_dense, sparse_k=rcfg.top_k_sparse,
                    rrf_k=rcfg.rrf_k, hybrid=rcfg.hybrid, min_score=rcfg.min_score,
                )
                merged: dict[str, float] = {}
                for cid, sc in hits + hits2:
                    merged[cid] = max(merged.get(cid, 0.0), sc)
                hits = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)[:top_k]

        retrieved_ids = [cid for cid, _ in hits]
        context = "\n\n---\n\n".join(
            f"[{cid}] {self.index.get_chunk(cid).text}" for cid in retrieved_ids
            if self.index.get_chunk(cid))
        tool_snippet, tool_calls = (None, [])
        if self.definition.tools:
            tool_snippet, tool_calls = run_tool_loop(self.harness, self.definition,
                                                     question, context, run_dir=self.run_dir)
        user_msg = (
            f"Context chunks:\n{context[:6000]}\n\n"
            + (f"Tool evidence:\n{tool_snippet}\n\n" if tool_snippet else "")
            + f"Question: {question}\n\n"
            "Respond ONLY as JSON: {\"answer\": str, \"refused\": bool, \"citations\": [chunk ids], \"confidence\": 0..1}"
        )
        from ..llm import StructuredGenError
        try:
            data = self.harness.ask_json(ContractAnswer, user_msg,
                                         system=self.definition.system_prompt,
                                         stage="agent_answer", temperature=0.1)
            resp = AgentResponse(
                answer=data.answer, refused=data.refused, citations=data.citations,
                retrieved=retrieved_ids, raw="", tool_calls=tool_calls,
                confidence=data.confidence, parse_failed=False)
            return resp
        except StructuredGenError as exc:
            # last-ditch: salvage whatever JSON the model produced
            try:
                salvaged = json.loads(_extract_json(exc.raw))
                resp = AgentResponse(
                    answer=str(salvaged.get("answer", "(unparseable)")),
                    refused=bool(salvaged.get("refused", False)),
                    citations=[str(c) for c in salvaged.get("citations", [])],
                    retrieved=retrieved_ids, raw=exc.raw, tool_calls=tool_calls,
                    confidence=_num_or_none(salvaged.get("confidence")),
                    parse_failed=True)
            except (json.JSONDecodeError, ValueError):
                resp = AgentResponse(answer="(unparseable)", refused=False, citations=[],
                                     retrieved=retrieved_ids, raw=exc.raw, tool_calls=tool_calls,
                                     parse_failed=True)
            return resp


def _num_or_none(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
