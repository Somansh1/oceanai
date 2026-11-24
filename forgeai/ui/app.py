"""ForgeAI UI — three tabs: Factory, Runner, Evidence.

Deliberately thin: the UI is a window onto the CLI, not a parallel
implementation. The factory runs exactly what the review demo runs.
Run with:  streamlit run ui/app.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from forge.llm import Harness, OllamaBackend  # noqa: E402
from forge.retrieve import HybridIndex  # noqa: E402
from forge.runner import ForgeAgent  # noqa: E402
from forge.spec import AgentDefinition  # noqa: E402

st.set_page_config(page_title="ForgeAI", page_icon="🏭", layout="wide")


def _run_dirs() -> list[Path]:
    base = ROOT
    candidates = sorted(
        [p for p in (base / "runs").glob("*") if p.is_dir()]
        + [p for p in (base / "demos").glob("*/run") if p.is_dir()]
    )
    return [c for c in candidates if (c / "definition.json").exists()]


def _forge(*args: str) -> subprocess.CompletedProcess:
    py = sys.executable
    return subprocess.run([py, "-m", "forge.cli", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=3600)


tab_factory, tab_chat, tab_evidence = st.tabs(["🏭 Factory", "💬 Runner", "📊 Evidence"])

with tab_factory:
    st.header("The Agent That Builds Agents")
    st.caption("Brief in, working agent out — with the honest report attached.")
    brief_text = st.text_area(
        "One-paragraph brief", height=120,
        placeholder="I need an assistant that answers … for …, refuses …, tone …")
    docs_dir = st.text_input("Document folder (absolute path)", value=str(ROOT / "demos" / "hr" / "docs"))
    auto = st.checkbox("Unattended (--auto): resolve interview questions to logged assumptions", value=True)
    if st.button("Build agent", type="primary", disabled=not (brief_text.strip() and Path(docs_dir).is_dir())):
        out_dir = ROOT / "runs" / "ui-latest"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir.parent / "ui-brief.md").write_text(brief_text, encoding="utf-8")
        with st.status("factory running…") as status:
            result = _forge("build", "--brief", str(out_dir.parent / "ui-brief.md"),
                            "--docs", docs_dir, "--out", str(out_dir),
                            *(["--auto"] if auto else ["--interactive"]))
            status.update(label=f"exit {result.returncode}")
            st.code(result.stdout[-4000:] or result.stderr[-4000:])
        if (out_dir / "report.md").exists():
            st.markdown((out_dir / "report.md").read_text(encoding="utf-8"))

with tab_chat:
    st.header("Generic runner")
    st.caption("Loads ANY produced definition — retrieval params, tools and prompt come from the artifact.")
    runs = _run_dirs()
    selected = st.selectbox("Run", [str(r) for r in runs] or ["(no runs found)"])
    if st.button("Load agent") and Path(selected).is_dir():
        st.session_state["agent_dir"] = selected
    agent_dir = st.session_state.get("agent_dir")
    if agent_dir and Path(agent_dir).is_dir():
        try:
            definition = AgentDefinition.model_validate_json(
                (Path(agent_dir) / "definition.json").read_text(encoding="utf-8"))
            index = HybridIndex(Path(agent_dir) / "index.sqlite")
            agent = ForgeAgent(Harness(OllamaBackend()), index, definition)
            st.success(f"{definition.name} loaded — tools: {[t.name for t in definition.tools]}")
            if "messages" not in st.session_state:
                st.session_state["messages"] = []
            for m in st.session_state["messages"]:
                st.chat_message(m["role"]).write(m["content"])
                if m.get("citations"):
                    st.caption("citations: " + ", ".join(m["citations"]))
            q = st.chat_input("Ask the agent…")
            if q:
                st.session_state["messages"].append({"role": "user", "content": q})
                st.chat_message("user").write(q)
                with st.chat_message("assistant"):
                    with st.spinner("thinking…"):
                        resp = agent.answer(q)
                    style = "_(refused)_ " if resp.refused else ""
                    st.write(style + (resp.answer or "(no answer)"))
                    if resp.citations:
                        st.caption("citations: " + ", ".join(resp.citations))
                st.session_state["messages"].append(
                    {"role": "assistant", "content": resp.answer,
                     "citations": resp.citations})
        except Exception as exc:
            st.error(f"failed to load run: {exc}")

with tab_evidence:
    st.header("Evidence")
    st.caption("The report is the product; the agent is evidence for it.")
    runs = _run_dirs()
    selected = st.selectbox("Run to inspect", [str(r) for r in runs] or ["(no runs found)"],
                            key="evidence_run")
    p = Path(selected)
    if p.is_dir():
        col1, col2 = st.columns(2)
        with col1:
            if (p / "scorecard.json").exists():
                sc = json.loads((p / "scorecard.json").read_text(encoding="utf-8"))
                st.metric("score", f"{sc['score']:.0%}",
                          delta=f"{sc['passed']}/{sc['total']} passed")
                st.caption(f"95% CI [{sc['wilson_low']:.0%}, {sc['wilson_high']:.0%}]")
            if (p / "iterations.json").exists():
                it = json.loads((p / "iterations.json").read_text(encoding="utf-8"))
                st.write("optimization entries:", len(it.get("entries", [])),
                         "· stopped early:", it.get("stopped_early"))
        with col2:
            if (p / "ledger.json").exists():
                ledger = json.loads((p / "ledger.json").read_text(encoding="utf-8"))
                totals = ledger.get("totals", {})
                st.metric("model calls", totals.get("calls", 0))
                st.caption(f"{totals.get('in_tokens', 0) + totals.get('out_tokens', 0)} tokens, "
                           f"{totals.get('latency_ms', 0) / 1000:.0f}s")
        if (p / "report.md").exists():
            st.markdown("---")
            st.markdown((p / "report.md").read_text(encoding="utf-8"))

