"""Agent generator: prompt candidates, retrieval config, tool selection.

The model proposes candidates; code validates + scores. Tool selection must
justify attachment AND record explicit rejections (negative selection is as
visible as positive).
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from ..llm import Harness
from ..spec import (AgentDefinition, RefusalPolicy, RequirementsDoc,
                    RetrievalConfig, ToolBinding, ToolRejection)
from ..tools import REGISTRY, format_tools_for_prompt


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
        rej_names = {r.get("name", "") for r in self.rejected}
        self.rejected = [r for r in self.rejected if r.get("name") in REGISTRY]
        for name in REGISTRY:
            if name not in seen and name not in rej_names:
                self.rejected.append({"name": name, "reason": "not selected by generator"})
        return self


def _tool_selection(harness: Harness, req: RequirementsDoc, inventory: str) -> ToolDecision:
    class ToolOut(BaseModel):
        selected: list[dict[str, str]]
        rejected: list[dict[str, str]]

    catalog = "\n".join(f"- {t.description}\n  {t.usage}" for t in REGISTRY.values())
    prompt = (
        "You are the tool selector of an agent factory. Attach ONLY the tools this brief "
        "genuinely needs. Attaching an unneeded tool is a factory defect.\n\n"
        "For every tool in the catalog, decide select or reject with a one-line reason.\n\n"
        "Return JSON: {\"selected\": [{\"name\", \"justification\", \"invoked_when\"}], "
        "\"rejected\": [{\"name\", \"reason\"}]}\n\n"
        "## BRIEF\n" + req.brief_verbatim +
        "\n\n## REQUIREMENTS DIGEST\n" + _digest(req) +
        "\n\n## DOCUMENT INVENTORY\n" + inventory +
        "\n\n## TOOL CATALOG\n" + catalog)
    out = harness.ask_json(ToolOut, prompt, stage="tool_selection", temperature=0.1)
    d = ToolDecision(selected=out.selected, rejected=out.rejected)
    return d.sanitize(harness)


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
    tool_names = [t.name for t in tools]
    for i, v in enumerate(variants, 1):
        prompt, sha = harness.prompts.render(
            "04_system_prompt", requirements_digest=_digest(req),
            tools=format_tools_for_prompt(tool_names), variant=v)
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


def generate_agent(harness: Harness, req: RequirementsDoc, inventory: str,
                    winner: PromptCandidate,
                    tools: ToolDecision, iteration: int = 0) -> AgentDefinition:
    definition = AgentDefinition(
        name=req.agent_name,
        iteration=iteration,
        system_prompt=winner.system_prompt,
        requirements_digest=_digest(req),
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
