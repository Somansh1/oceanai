"""Generic agent engine: definition-driven execution with the shared contract.

This is the ONLY execution path for produced agents — runner, judge and chat
CLI all use it, so what the judge tests is exactly what the user gets.
"""
from __future__ import annotations

import json
import re

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


def run_tool_loop(harness: Harness, definition: AgentDefinition,
                  question: str, context: str, max_calls: int = 3) -> tuple[str, list[dict]]:
    """Let the agent request tools via TOOL: {json} lines; code executes them."""
    attachments = "\n".join(f"- {t.name}: {REGISTRY[t.name].description}\n  call: {REGISTRY[t.name].usage}"
                            for t in definition.tools)
    transcript = ""
    calls: list[dict] = []
    for _ in range(max_calls):
        # ask only for a tool request or a final answer
        prompt = (
            "You have these tools available:\n" + attachments + "\n\n"
            "Choose exactly one:\n"
            "  TOOL: {\"tool\": ..., \"args\": {...}}   (request one tool call)\n"
            "  FINAL_SNIPPET: <brief answer given the context, or leave empty>\n\n"
            "Question: " + question + "\n\nRetrieved context:\n" + context[:4000] +
            ("\n\nTool results so far:\n" + transcript[-2000:] if transcript else "")
        )
        out = harness.ask_text(prompt, stage="tool_loop", temperature=0.1)
        m = re.search(r"TOOL:\s*(\{.*?\})", out, re.S)
        if m:
            try:
                req = json.loads(m.group(1))
                tool = REGISTRY.get(str(req.get("tool", "")))
                if tool is None:
                    transcript += f"\ntool {req.get('tool')}: unknown tool"
                    calls.append({"tool": req.get("tool"), "ok": False, "error": "unknown"})
                    continue
                result = tool.run(req.get("args", {}))
                calls.append({"tool": tool.name, "args": req.get("args", {}), "result": result[:400]})
                transcript += f"\n[{tool.name}] {result[:800]}"
            except json.JSONDecodeError:
                calls.append({"tool": "?", "ok": False, "error": "bad json"})
        else:
            fm = re.search(r"FINAL_SNIPPET:\s*(.*)", out, re.S)
            if fm:
                return fm.group(1).strip(), calls
            return out.strip()[:400], calls
    return "", calls


class ForgeAgent:
    """Loads ANY definition. Retrieval params, tools, prompt all come from data."""

    def __init__(self, harness: Harness, index: HybridIndex, definition: AgentDefinition):
        self.harness = harness
        self.index = index
        self.definition = definition

    def answer(self, question: str) -> AgentResponse:
        cfg = self.definition.refusal_policy
        rcfg = self.definition.retrieval
        qvec = None  # embeddings optional at runtime
        hits = self.index.query(question, vector=qvec, top_k=rcfg.top_k_dense,
                                 dense_k=rcfg.top_k_dense, sparse_k=rcfg.top_k_sparse)
        retrieved_ids = [cid for cid, _ in hits]
        context = "\n\n---\n\n".join(
            f"[{cid}] {self.index.get_chunk(cid).text}" for cid in retrieved_ids
            if self.index.get_chunk(cid))
        tool_snippet, tool_calls = (None, [])
        if self.definition.tools:
            tool_snippet, tool_calls = run_tool_loop(self.harness, self.definition,
                                                     question, context)
        user_msg = (
            f"Context chunks:\n{context[:6000]}\n\n"
            + (f"Tool evidence:\n{tool_snippet}\n\n" if tool_snippet else "")
            + f"Question: {question}\n\n"
            "Respond ONLY as JSON: {\"answer\": str, \"refused\": bool, \"citations\": [chunk ids], \"confidence\": 0..1}"
        )
        raw = self.harness.ask_text(user_msg, system=self.definition.system_prompt,
                                    stage="agent_answer", temperature=0.1)
        try:
            data = json.loads(_extract_json(raw))
            resp = AgentResponse(
                answer=str(data.get("answer", "")), refused=bool(data.get("refused", False)),
                citations=[str(c) for c in data.get("citations", [])],
                retrieved=retrieved_ids, raw=raw, tool_calls=tool_calls,
                confidence=_num_or_none(data.get("confidence")), parse_failed=False)
        except (json.JSONDecodeError, ValueError):
            resp = AgentResponse(answer="(unparseable)", refused=False, citations=[],
                                 retrieved=retrieved_ids, raw=raw, tool_calls=tool_calls,
                                 parse_failed=True)
        return resp


def _num_or_none(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
