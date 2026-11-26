"""Agent generator: prompt candidates, retrieval config, tool selection.

The model proposes candidates; code validates + scores. Tool selection must
justify attachment AND record explicit rejections (negative selection is as
visible as positive).
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from ..core import Chunk, DocumentMeta
from ..llm import Harness
from ..spec import (AgentDefinition, RefusalPolicy, RequirementsDoc,
                    RetrievalConfig, ToolBinding, ToolRejection)
from ..tools import REGISTRY


class PromptCandidate(BaseModel):
    name: str
    system_prompt: str
    design_notes: str = ""


class ToolDecision(BaseModel):
    selected: list[dict[str, str]] = Field(default_factory=list)   # {name, justification, invoked_when}
    rejected: list[dict[str, str]] = Field(default_factory=list)  # {name, reason}

    def sanitize(self, harness: Harness) -> "ToolDecision":
        """Code disposes: unknown / duplicate tools are dropped by us, not the model."""
        seen, kept = set(), []
        for t in self.selected:
            name = t.get("name", "")
            if name in REGISTRY and name not in seen:
                seen.add(name)
                kept.append(t)
        self.selected = kept
        # Never keep a selected tool in rejected; keep unique valid rejections.
        rej_seen: set[str] = set()
        clean_rejected: list[dict[str, str]] = []
        for r in self.rejected:
            name = r.get("name", "")
            if name in REGISTRY and name not in seen and name not in rej_seen:
                rej_seen.add(name)
                clean_rejected.append(r)
        for name in REGISTRY:
            if name not in seen and name not in rej_seen:
                clean_rejected.append({"name": name, "reason": "not selected by generator"})
        self.rejected = clean_rejected
        return self


_HINT_RULES = {
    "calculator": ["cost", "costs", "fee", "fees", "demurrage", "charge", "charges",
                   "price", "prices", "total", "arithmetic", "exact", "exactly",
                   "compute", "calculate", "per ton", "difference"],
    "open_meteo": ["weather", "sea condition", "sea conditions", "wind speed",
                   "windy", "swell", "forecast", "wave", "waves", "marine"],
    "now": ["next vessel", "current date", "current time", "today", "as of",
            "upcoming", "relative date", "relative dates", "this week"],
}


def _hinted_tools(brief: str, data_files: list[str] | None) -> dict[str, str]:
    """Deterministic word-boundary hints from the brief.

    Uses word boundaries so substrings like 'wind' in 'Northwind' never trigger
    the weather tool on an HR brief.
    """
    low = brief.lower()
    hints: dict[str, str] = {}
    for name, kws in _HINT_RULES.items():
        hit = next((k for k in kws if re.search(rf"\b{re.escape(k)}\b", low)), None)
        if hit:
            hints[name] = f"brief keyword rule matched '{hit}'"
    if data_files:
        hints.setdefault("csv_lookup", "structured data files present in the document folder")
    return hints


def _tool_selection(harness: Harness, req: RequirementsDoc, inventory: str,
                    data_files: list[str] | None = None) -> ToolDecision:
    class ToolOut(BaseModel):
        selected: list[dict[str, str]]
        rejected: list[dict[str, str]]

    catalog = "\n".join(f"- {t.description}\n  {t.usage}" for t in REGISTRY.values())
    files_note = ("\n\n## DATA FILES AVAILABLE FOR csv_lookup\n"
                  + "\n".join(f"- {f}" for f in (data_files or []))) if data_files else ""
    prompt = (
        "You are the tool selector of an agent factory. Attach ONLY the tools this brief "
        "genuinely needs. Attaching an unneeded tool is a factory defect.\n\n"
        "For every tool in the catalog, decide select or reject with a one-line reason.\n\n"
        "Return JSON: {\"selected\": [{\"name\", \"justification\", \"invoked_when\"}], "
        "\"rejected\": [{\"name\", \"reason\"}]}\n\n"
        "## BRIEF\n" + req.brief_verbatim +
        "\n\n## REQUIREMENTS DIGEST\n" + _digest(req) +
        "\n\n## DOCUMENT INVENTORY\n" + inventory + files_note +
        "\n\n## TOOL CATALOG\n" + catalog)
    out = harness.ask_json(ToolOut, prompt, stage="tool_selection", temperature=0.1)
    d = ToolDecision(selected=out.selected, rejected=out.rejected)
    d = d.sanitize(harness)
    if data_files:
        for t in d.selected:
            if t.get("name") == "csv_lookup":
                t["config"] = {"files": data_files}

    # ENFORCEMENT: brief-keyword hints override the selector. The override is
    # labeled in the justification — the report shows every enforced tool.
    hints = _hinted_tools(req.brief_verbatim, data_files)
    rejected_names = {r.get("name") for r in d.rejected}
    for name, basis in hints.items():
        if any(t.get("name") == name for t in d.selected):
            continue
        was = "rejected by selector" if name in rejected_names else "omitted by selector"
        d.rejected = [r for r in d.rejected if r.get("name") != name]
        d.selected.append({
            "name": name,
            "justification": f"ENFORCED — {basis}; {was}",
            "invoked_when": "when a question requires it",
            "config": {"files": data_files} if name == "csv_lookup" and data_files else {},
        })
    return d


def _digest(req: RequirementsDoc) -> str:
    return json.dumps({
        "agent_name": req.agent_name,
        "scope_in": req.scope_in,
        "scope_out": req.scope_out,
        "must_answer": req.must_answer_topics,
        "must_refuse": req.must_refuse_topics,
        "audience": req.audience,
        "tone": req.tone,
    }, indent=1)


def _tools_text(bindings: list[ToolBinding]) -> str:
    from ..tools import REGISTRY
    lines = []
    for b in bindings:
        t = REGISTRY.get(b.name)
        if not t:
            continue
        line = f"- {t.name}: {t.description}\n  call: {t.usage}"
        files = (b.config or {}).get("files")
        if files:
            line += "\n  data files: " + ", ".join(files)
        lines.append(line)
    return "\n".join(lines) or "(no tools attached)"


def generate_prompt_candidates(harness: Harness, req: RequirementsDoc,
                               tools: list[ToolBinding]) -> list[PromptCandidate]:
    """System prompts are PLAIN TEXT, never JSON-wrapped — small models break
    long string fields; structured slots are for short structured payloads."""
    variants = [
        "balanced: explicit grounding rule, concise refusal template, middle length.",
        "strict: refusal-first posture, lists banned topics verbatim, short answers.",
        "helpful: answers then cites, gentle refusals, slightly warmer tone.",
    ]
    candidates: list[PromptCandidate] = []
    for i, v in enumerate(variants, 1):
        prompt, sha = harness.prompts.render(
            "04_system_prompt", requirements_digest=_digest(req),
            tools=_tools_text(tools), variant=v)
        prompt += (
            "\n\nOUTPUT FORMAT: write ONLY the system prompt itself as plain text. "
            "Do not wrap it in JSON, do not add commentary, do not add a title."
        )
        text = harness.ask_text(prompt, stage="prompt_candidate", prompt_sha=sha, temperature=0.3
                                )
        system_prompt = text.strip()
        # strip a leading markdown header/quotes if the model added one
        system_prompt = re.sub(r"^```\w*\s*|\s*```$", "", system_prompt).strip()
        if not system_prompt:
            continue
        candidates.append(PromptCandidate(name=f"candidate-{i}", system_prompt=system_prompt,
                                          design_notes=v))
    if not candidates:
        raise RuntimeError("all prompt candidates came back empty")
    return candidates


def derive_retrieval_config(chunks: list[Chunk], metas: list[DocumentMeta],
                            chunk_size: int = 900, overlap: int = 150,
                            dense_ready: bool = True) -> RetrievalConfig:
    """Derive retrieval knobs from corpus size and structure rather than fixed defaults."""
    n_chunks = len(chunks)
    has_tabular = any(m.kind in ("csv", "xlsx") for m in metas)
    if n_chunks <= 6:
        top_k_dense, top_k_sparse = min(4, max(2, n_chunks)), min(6, max(3, n_chunks))
    elif n_chunks <= 25:
        top_k_dense, top_k_sparse = 5, 8
    else:
        top_k_dense, top_k_sparse = 7, 10
    if has_tabular:
        top_k_dense = max(top_k_dense, 5)
        top_k_sparse = max(top_k_sparse, 8)
    return RetrievalConfig(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        top_k_dense=top_k_dense,
        top_k_sparse=top_k_sparse,
        rrf_k=60,
        hybrid=dense_ready,
        query_rewrite=False,
        min_score=0.0,
    )


def generate_agent(harness: Harness, req: RequirementsDoc, inventory: str,
                    winner: PromptCandidate,
                    tools: ToolDecision, iteration: int = 0,
                    retrieval: RetrievalConfig | None = None) -> AgentDefinition:
    definition = AgentDefinition(
        name=req.agent_name,
        iteration=iteration,
        system_prompt=winner.system_prompt,
        requirements_digest=_digest(req),
        retrieval=retrieval or RetrievalConfig(),
        tools=[ToolBinding(**t) for t in tools.selected],
        rejected_tools=[ToolRejection(**t) for t in tools.rejected],
        refusal_policy=RefusalPolicy(
            must_refuse_topics=req.must_refuse_topics,
            over_refusal_guard=None,
        ),
    )
    return definition


def tournament(harness: Harness, req: RequirementsDoc, candidates: list[PromptCandidate]
               ) -> tuple[PromptCandidate, list[dict]]:
    """Placeholder for the pilot-eval tournament (day 5-6). Best-name wins for now."""
    # real tournament comes with the judge; for now first candidate wins
    if not candidates:
        raise ValueError("no candidates")
    winner = candidates[0]
    log = [{"candidate": c.name, "note": "tournament pending judge"} for c in candidates]
    return winner, log
