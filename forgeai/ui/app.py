"""ForgeAI UI — Production Control Dashboard.

High-performance interface for autonomous agent generation, interactive
execution, and empirical quality verification.

Run with:
    streamlit run ui/app.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from forge.core import Chunk  # noqa: E402
from forge.llm import Harness, OllamaBackend  # noqa: E402
from forge.retrieve import HybridIndex  # noqa: E402
from forge.runner import ForgeAgent  # noqa: E402
from forge.spec import AgentDefinition  # noqa: E402

st.set_page_config(
    page_title="ForgeAI",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
  :root {
    --bg-base: #060911;
    --bg-surface: rgba(15, 23, 42, 0.75);
    --bg-card: rgba(22, 32, 50, 0.70);
    --bg-card-hover: rgba(30, 41, 59, 0.85);
    --border-hairline: rgba(255, 255, 255, 0.08);
    --border-highlight: rgba(255, 255, 255, 0.14);
    --border-focus: #0284c7;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --accent: #0284c7;
    --accent-hover: #0369a1;
    --accent-glass: rgba(2, 132, 199, 0.14);
    --accent-border: rgba(2, 132, 199, 0.35);
    --success: #10b981;
    --success-glass: rgba(16, 185, 129, 0.14);
    --success-border: rgba(16, 185, 129, 0.35);
    --danger: #ef4444;
    --danger-glass: rgba(239, 68, 68, 0.14);
    --danger-border: rgba(239, 68, 68, 0.35);
    --radius-outer: 12px;
    --radius-inner: 8px;
    --radius-pill: 9999px;
  }

  .stApp {
    background-color: var(--bg-base);
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  .brand-header {
    border-bottom: 1px solid var(--border-hairline);
    padding: 16px 0 20px 0;
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }
  .brand-title {
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.025em;
    color: var(--text-primary);
    margin: 0;
  }
  .brand-subtitle {
    font-size: 13px;
    color: var(--text-secondary);
    margin-top: 4px;
    letter-spacing: -0.01em;
  }
  .brand-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: var(--radius-pill);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    background: var(--accent-glass);
    color: #38bdf8;
    border: 1px solid var(--accent-border);
  }

  .kpi-card {
    background: var(--bg-card);
    border: 1px solid var(--border-hairline);
    border-top: 1px solid var(--border-highlight);
    border-radius: var(--radius-outer);
    padding: 16px 18px;
    margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3), 0 8px 24px rgba(0, 0, 0, 0.2);
  }
  .kpi-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    margin-bottom: 4px;
  }
  .kpi-value {
    font-size: 26px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
  }
  .kpi-caption {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 4px;
  }

  .citation-pill {
    display: inline-block;
    background: var(--accent-glass);
    border: 1px solid var(--accent-border);
    color: #38bdf8;
    padding: 2px 8px;
    border-radius: var(--radius-inner);
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 12px;
    margin: 2px 4px 2px 0;
  }
  .refusal-badge {
    display: inline-block;
    background: var(--danger-glass);
    border: 1px solid var(--danger-border);
    color: #f87171;
    padding: 2px 10px;
    border-radius: var(--radius-pill);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
    margin-bottom: 8px;
  }
  .grounded-badge {
    display: inline-block;
    background: var(--success-glass);
    border: 1px solid var(--success-border);
    color: #34d399;
    padding: 2px 10px;
    border-radius: var(--radius-pill);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
    margin-bottom: 8px;
  }

  .stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: rgba(15, 23, 42, 0.5);
    padding: 4px;
    border-radius: var(--radius-outer);
    border: 1px solid var(--border-hairline);
  }
  .stTabs [data-baseweb="tab"] {
    height: 36px;
    background-color: transparent;
    border-radius: var(--radius-inner);
    color: var(--text-secondary);
    font-weight: 500;
    font-size: 13px;
    padding: 0 16px;
    border: none;
    transition: all 0.2s ease;
  }
  .stTabs [aria-selected="true"] {
    background-color: var(--bg-card-hover);
    color: var(--text-primary);
    border-top: 1px solid var(--border-highlight);
    box-shadow: 0 1px 3px rgba(0,0,0,0.4);
    font-weight: 600;
  }
</style>
""",
    unsafe_allow_html=True,
)


def _render_header() -> None:
    st.markdown(
        """
    <div class="brand-header">
      <div>
        <div class="brand-title">ForgeAI</div>
        <div class="brand-subtitle">Autonomous agent synthesis, adversarial evaluation compiler, and verification engine</div>
      </div>
      <div>
        <span class="brand-badge">Production Build</span>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def _run_dirs() -> list[Path]:
    base = ROOT
    candidates = (
        sorted([p for p in (base / "runs").glob("*") if p.is_dir()])
        + sorted([p for p in (base / "demos").glob("*/run") if p.is_dir()])
    )
    return [c for c in candidates if (c / "definition.json").exists()]


def _forge(*args: str) -> subprocess.CompletedProcess:
    py = sys.executable
    return subprocess.run(
        [py, "-m", "forge.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=3600,
    )


def _load_chunks(run_dir: Path) -> dict[str, str]:
    chunks_file = run_dir / "chunks.jsonl"
    if not chunks_file.exists():
        return {}
    chunks: dict[str, str] = {}
    for line in chunks_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                data = json.loads(line)
                chunks[data.get("id", "")] = data.get("text", "")
            except Exception:
                pass
    return chunks


def _render_pipeline_flow() -> None:
    html_code = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    :root {
      --bg-card: rgba(22, 32, 50, 0.70);
      --border-hairline: rgba(255, 255, 255, 0.08);
      --border-highlight: rgba(255, 255, 255, 0.16);
      --accent: #0284c7;
      --accent-active: #38bdf8;
      --text-primary: #f8fafc;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
    }
    body {
      margin: 0;
      padding: 8px 4px 12px 4px;
      background: transparent;
      color: var(--text-primary);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      user-select: none;
    }
    .pipeline-container {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      position: relative;
    }
    .stage-node {
      flex: 1;
      background: var(--bg-card);
      border: 1px solid var(--border-hairline);
      border-top: 1px solid var(--border-highlight);
      border-radius: 10px;
      padding: 12px 6px;
      text-align: center;
      cursor: pointer;
      position: relative;
      box-shadow: 0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.15);
      min-height: 72px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      transition: all 0.2s ease;
    }
    .stage-node:hover {
      border-color: rgba(2, 132, 199, 0.4);
      transform: translateY(-1px);
    }
    .stage-node:active {
      transform: scale(0.98);
    }
    .stage-node.active {
      border-color: var(--accent-active);
      background: rgba(30, 44, 70, 0.85);
      box-shadow: 0 0 16px rgba(2, 132, 199, 0.25);
    }
    .stage-number {
      font-size: 10px;
      font-weight: 700;
      color: #38bdf8;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 2px;
    }
    .stage-title {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-primary);
      line-height: 1.25;
    }
    .stage-sub {
      font-size: 10px;
      color: var(--text-muted);
      margin-top: 3px;
    }
    .arrow-divider {
      color: #475569;
      font-size: 13px;
      font-weight: 600;
    }
    .detail-drawer {
      background: var(--bg-card);
      border: 1px solid var(--border-hairline);
      border-top: 1px solid var(--border-highlight);
      border-radius: 10px;
      padding: 14px 18px;
      margin-top: 12px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.25);
      min-height: 72px;
      transition: opacity 0.2s ease;
    }
    .detail-header {
      font-size: 13px;
      font-weight: 600;
      color: #38bdf8;
      margin-bottom: 4px;
    }
    .detail-body {
      font-size: 12px;
      color: var(--text-secondary);
      line-height: 1.5;
    }
  </style>
</head>
<body>
  <div class="pipeline-container">
    <div class="stage-node active" id="node-1" onclick="selectNode(1)">
      <div class="stage-number">Stage 1</div>
      <div class="stage-title">Intake Interview</div>
      <div class="stage-sub">&le; 5 questions / auto</div>
    </div>
    <div class="arrow-divider">&rarr;</div>
    <div class="stage-node" id="node-2" onclick="selectNode(2)">
      <div class="stage-number">Stage 2</div>
      <div class="stage-title">Groundability Guard</div>
      <div class="stage-sub">Density matrix</div>
    </div>
    <div class="arrow-divider">&rarr;</div>
    <div class="stage-node" id="node-3" onclick="selectNode(3)">
      <div class="stage-number">Stage 3</div>
      <div class="stage-title">Agent Generator</div>
      <div class="stage-sub">Declarative JSON</div>
    </div>
    <div class="arrow-divider">&rarr;</div>
    <div class="stage-node" id="node-4" onclick="selectNode(4)">
      <div class="stage-number">Stage 4</div>
      <div class="stage-title">Eval Compiler</div>
      <div class="stage-sub">Adversarial gates</div>
    </div>
    <div class="arrow-divider">&rarr;</div>
    <div class="stage-node" id="node-5" onclick="selectNode(5)">
      <div class="stage-number">Stage 5</div>
      <div class="stage-title">Layered Judge</div>
      <div class="stage-sub">L0 check + L1 facts</div>
    </div>
    <div class="arrow-divider">&rarr;</div>
    <div class="stage-node" id="node-6" onclick="selectNode(6)">
      <div class="stage-number">Stage 6</div>
      <div class="stage-title">Critic Optimizer</div>
      <div class="stage-sub">Surgical patches</div>
    </div>
    <div class="arrow-divider">&rarr;</div>
    <div class="stage-node" id="node-7" onclick="selectNode(7)">
      <div class="stage-number">Stage 7</div>
      <div class="stage-title">Honest Report</div>
      <div class="stage-sub">Wilson CIs + triage</div>
    </div>
  </div>

  <div class="detail-drawer" id="drawer">
    <div class="detail-header" id="drawer-title">Stage 1: Intake Interviewer</div>
    <div class="detail-body" id="drawer-desc">
      Inspects the unstructured brief and document collection. Formulates at most 5 clarifying questions, each mapped to a concrete architectural decision. Automated mode (--auto) resolves conservative defaults without blocking.
    </div>
  </div>

  <script>
    const stageDetails = {
      1: {
        title: "Stage 1: Intake Interviewer",
        desc: "Inspects the unstructured brief and document collection. Formulates at most 5 clarifying questions, each mapped to a concrete architectural decision. Automated mode (--auto) resolves conservative defaults without blocking."
      },
      2: {
        title: "Stage 2: Groundability Guard",
        desc: "Builds a topic-by-evidence density matrix over document chunks. Discovers unsupported topics requested in the brief and rewrites them into mandatory refusal constraints before agent generation begins."
      },
      3: {
        title: "Stage 3: Declarative Agent Generator",
        desc: "Emits the complete agent specification: versioned system prompt, retrieval hyperparameters, tool bindings with explicit justification, and a strict JSON output contract. Tools are attached only when justified by brief keywords."
      },
      4: {
        title: "Stage 4: Adversarial Evaluation Compiler",
        desc: "Synthesizes at least 15-20 test cases stratified across answerable lookups, out-of-scope questions, premise canaries, and rephrase pairs. Every expected fact must survive its source chunk."
      },
      5: {
        title: "Stage 5: Layered Multi-Tier Judge",
        desc: "Combines L0 deterministic code checks (valid citation IDs in index, JSON schema compliance, numeric derivation checks) with L1 micro-binary claim verification. Calculates Wilson score confidence intervals."
      },
      6: {
        title: "Stage 6: Critic-Optimizer Loop",
        desc: "Deconstructs failure modes into canonical classes (retrieval miss, prompt defect, hallucination, wrong refusal). Applies surgical versioned patches to the prompt or retrieval config rather than blind regeneration (max 3 iterations)."
      },
      7: {
        title: "Stage 7: Honest Quality Report",
        desc: "Generates the definitive Markdown audit artifact: per-iteration score progression, Wilson confidence bounds, tool selection and rejection rationales, groundability overrides, and remaining failure postmortems."
      }
    };

    function selectNode(id) {
      document.querySelectorAll('.stage-node').forEach(el => el.classList.remove('active'));
      const target = document.getElementById('node-' + id);
      if (target) target.classList.add('active');

      const drawer = document.getElementById('drawer');
      const title = document.getElementById('drawer-title');
      const desc = document.getElementById('drawer-desc');

      drawer.style.opacity = '0.5';
      setTimeout(() => {
        title.textContent = stageDetails[id].title;
        desc.textContent = stageDetails[id].desc;
        drawer.style.opacity = '1';
      }, 50);
    }
  </script>
</body>
</html>
    """
    components.html(html_code, height=210)


# ------------------------------------------------------------- Main Application
_render_header()

tab_pipeline, tab_factory, tab_runner, tab_evidence = st.tabs(
    [
        "Pipeline Architecture",
        "Factory Studio",
        "Agent Chat Runner",
        "Evaluation Evidence",
    ]
)

# ==================================================================== Tab 0
with tab_pipeline:
    st.subheader("Autonomous Pipeline Flow and Verification Stages")
    st.caption("Interactive lifecycle of ForgeAI from raw brief to verified declarative agent.")
    _render_pipeline_flow()

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            """
        **Architectural Guarantee**
        - Model proposes structured candidates; Python code disposes and verifies.
        - Strict JSON schemas with automatic validation error repair loops.
        - Idempotent SQLite indexing supporting dense nomic-embed and sparse BM25.
        """
        )
    with c2:
        st.markdown(
            """
        **Adversarial Self-Distrust**
        - Expected facts must survive source chunk verification at compile time.
        - Canaries planted on covered topics are eliminated by answerability gates.
        - Inverted or negative claims rejected at birth.
        """
        )
    with c3:
        st.markdown(
            """
        **Honest Reporting**
        - 95% Wilson confidence intervals across all evaluation cohorts.
        - Complete failure postmortem classifying omissions vs hallucinations.
        - Provenance tracing linking all citations directly to document spans.
        """
        )

# ==================================================================== Tab 1
with tab_factory:
    st.subheader("Autonomous Agent Factory Studio")
    st.caption("Synthesize a production-ready agent from an unstructured brief.")

    col_presets, col_config = st.columns([1, 2])
    presets = {
        "Custom Brief": {
            "brief": "",
            "docs": str(ROOT / "demos" / "hr" / "docs"),
        },
        "ShoreHR Policy (Maritime Staff)": {
            "brief": (
                "I need an assistant that answers HR policy questions for shore staff at "
                "Northwind Maritime. The team asks things like how many annual leave days they get, "
                "notice periods for vacation requests, sick leave rules, parental leave entitlements, "
                "and what happens with unused days. It should only answer from our policy documents, "
                "and politely refuse anything about salary, pensions, or sea-staff crewing rules, "
                "which are handled by other departments. Tone should be plain and helpful for non-HR people."
            ),
            "docs": str(ROOT / "demos" / "hr" / "docs"),
        },
        "PortOps Logistics (Berths and Tariffs)": {
            "brief": (
                "I'm the port operations coordinator at Meridian Harbour (51.95 N, 4.14 E). I need an "
                "assistant that answers vessel turnaround questions: which vessel is at which berth on a given "
                "date, when the next vessel arrives at a berth, what a berth change or stay costs under our tariff "
                "rules (port dues, occupancy, demurrage if free time is exceeded, pilotage by LOA, tugs), and it "
                "should check current sea conditions at the port when I ask about movement windows. It must use our "
                "berth schedule and bunker price sheets for lookups, do any arithmetic exactly, work out relative "
                "dates correctly, and refuse anything about crew visas or cargo insurance, which other departments handle. "
                "Plain, operational tone for watch officers."
            ),
            "docs": str(ROOT / "demos" / "portops" / "docs"),
        },
        "University Library (Lending Regulations)": {
            "brief": (
                "I'm the front-desk supervisor at the Greystone University library. I need an assistant that "
                "answers student and staff questions about our lending rules: how many items each patron type can "
                "borrow and for how long, renewals, fines and when borrowing gets blocked, holds and recalls, and "
                "inter-library loans. It must only answer from our lending rules document, politely refuse anything "
                "about library room bookings, IT passwords, or archiving donations, and keep a plain, friendly tone for students."
            ),
            "docs": str(ROOT / "demos" / "library" / "docs"),
        },
    }

    selected_preset = st.selectbox(
        "Load Domain Preset", list(presets.keys()), index=1
    )
    current_preset = presets[selected_preset]

    brief_input = st.text_area(
        "Project Brief",
        value=current_preset["brief"],
        height=130,
        placeholder="Provide the one-paragraph brief describing domain, audience, and refusal boundaries...",
    )
    docs_input = st.text_input(
        "Document Folder Path", value=current_preset["docs"]
    )

    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        auto_flag = st.checkbox(
            "Unattended mode (--auto)",
            value=True,
            help="Resolve clarifying questions automatically with logged conservative assumptions.",
        )
    with fcol2:
        tournament_flag = st.checkbox(
            "Prompt Tournament",
            value=True,
            help="Generate 3 candidate prompts and select via pilot eval tournament.",
        )
    with fcol3:
        max_iters = st.number_input(
            "Max Optimization Iterations",
            min_value=1,
            max_value=5,
            value=3,
        )

    out_folder = ROOT / "runs" / "studio_run"
    ready = bool(brief_input.strip() and Path(docs_input).is_dir())

    if st.button("Synthesize Agent", type="primary", disabled=not ready):
        out_folder.mkdir(parents=True, exist_ok=True)
        brief_file = out_folder.parent / "studio_brief.md"
        brief_file.write_text(brief_input, encoding="utf-8")

        with st.status(
            "Executing autonomous factory stages...", expanded=True
        ) as status:
            cmd_args = [
                "build",
                "--brief",
                str(brief_file),
                "--docs",
                docs_input,
                "--out",
                str(out_folder),
                "--auto" if auto_flag else "--interactive",
            ]
            st.write("Invoking Forge CLI build pipeline...")
            res = _forge(*cmd_args)
            if res.returncode == 0:
                status.update(
                    label="Agent synthesis successfully completed",
                    state="complete",
                )
                st.success(f"Agent artifacts generated in {out_folder}")
            else:
                status.update(
                    label=f"Build finished with code {res.returncode}",
                    state="error",
                )
                st.code(res.stderr or res.stdout)

        if (out_folder / "report.md").exists():
            st.markdown("### Generated Factory Report")
            st.markdown((out_folder / "report.md").read_text(encoding="utf-8"))

# ==================================================================== Tab 2
with tab_runner:
    st.subheader("Generic Agent Runtime")
    st.caption("Execute and interrogate any declarative agent artifact with live provenance inspection.")

    runs = _run_dirs()
    if not runs:
        st.info("No synthesized agent runs discovered.")
    else:
        run_labels = {str(r): f"{r.parent.name} ({r})" for r in runs}
        selected_run_str = st.selectbox(
            "Select Agent Artifact",
            options=list(run_labels.keys()),
            format_func=lambda x: run_labels[x],
        )
        selected_run = Path(selected_run_str)

        if (selected_run / "definition.json").exists():
            defn_data = json.loads(
                (selected_run / "definition.json").read_text(encoding="utf-8")
            )
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            with col_m1:
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>Agent Name</div><div class='kpi-value'>{defn_data.get('name', 'Agent')}</div><div class='kpi-caption'>v{defn_data.get('version', 1)} (iter {defn_data.get('iteration', 0)})</div></div>",
                    unsafe_allow_html=True,
                )
            with col_m2:
                tools_attached = [t["name"] for t in defn_data.get("tools", [])]
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>Tools Attached</div><div class='kpi-value'>{len(tools_attached)}</div><div class='kpi-caption'>{', '.join(tools_attached) or 'Pure RAG'}</div></div>",
                    unsafe_allow_html=True,
                )
            with col_m3:
                r_cfg = defn_data.get("retrieval", {})
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>Retrieval Config</div><div class='kpi-value'>k={r_cfg.get('top_k_dense', 5)}+{r_cfg.get('top_k_sparse', 8)}</div><div class='kpi-caption'>Hybrid RRF (k={r_cfg.get('rrf_k', 60)})</div></div>",
                    unsafe_allow_html=True,
                )
            with col_m4:
                rej_tools = [
                    t["name"] for t in defn_data.get("rejected_tools", [])
                ]
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>Tools Rejected</div><div class='kpi-value'>{len(rej_tools)}</div><div class='kpi-caption'>{', '.join(rej_tools) or 'None'}</div></div>",
                    unsafe_allow_html=True,
                )

        chunks_map = _load_chunks(selected_run)

        state_key = f"messages_{selected_run.name}_{selected_run.parent.name}"
        if state_key not in st.session_state:
            st.session_state[state_key] = []

        for msg in st.session_state[state_key]:
            with st.chat_message(msg["role"]):
                if msg.get("refused"):
                    st.markdown(
                        "<span class='refusal-badge'>Refused: Out of Scope / Ungrounded</span>",
                        unsafe_allow_html=True,
                    )
                elif msg.get("citations"):
                    st.markdown(
                        "<span class='grounded-badge'>Grounded Response</span>",
                        unsafe_allow_html=True,
                    )
                st.write(msg["content"])
                if msg.get("citations"):
                    pills = "".join(
                        f"<span class='citation-pill'>{c}</span>"
                        for c in msg["citations"]
                    )
                    st.markdown(
                        f"<div style='margin-top:6px;'>{pills}</div>",
                        unsafe_allow_html=True,
                    )

        query = st.chat_input("Ask the agent a question...")
        if query:
            st.session_state[state_key].append(
                {"role": "user", "content": query}
            )
            with st.chat_message("user"):
                st.write(query)

            with st.chat_message("assistant"):
                with st.spinner("Retrieving evidence and formulating answer..."):
                    try:
                        definition = AgentDefinition.model_validate_json(
                            (selected_run / "definition.json").read_text(
                                encoding="utf-8"
                            )
                        )
                        index = HybridIndex(selected_run / "index.sqlite")
                        agent = ForgeAgent(
                            Harness(OllamaBackend()), index, definition
                        )
                        resp = agent.answer(query)

                        if resp.refused:
                            st.markdown(
                                "<span class='refusal-badge'>Refused: Out of Scope / Ungrounded</span>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                "<span class='grounded-badge'>Grounded Response</span>",
                                unsafe_allow_html=True,
                            )

                        st.write(
                            resp.answer or "(The agent declined to answer.)"
                        )
                        if resp.citations:
                            pills = "".join(
                                f"<span class='citation-pill'>{c}</span>"
                                for c in resp.citations
                            )
                            st.markdown(
                                f"<div style='margin-top:6px;'>{pills}</div>",
                                unsafe_allow_html=True,
                            )

                        st.session_state[state_key].append(
                            {
                                "role": "assistant",
                                "content": resp.answer,
                                "citations": resp.citations,
                                "refused": resp.refused,
                            }
                        )
                    except Exception as e:
                        st.error(f"Error querying agent: {e}")

        if chunks_map:
            with st.expander("Inspect Grounded Document Chunks (Index Provenance)"):
                cid_inspect = st.selectbox(
                    "Select Chunk ID to inspect", list(chunks_map.keys())
                )
                if cid_inspect:
                    st.text_area(
                        "Chunk Text",
                        value=chunks_map[cid_inspect],
                        height=140,
                        disabled=True,
                    )

# ==================================================================== Tab 3
with tab_evidence:
    st.subheader("Evaluation Evidence and Benchmark Analysis")
    st.caption("Empirical scoring, Wilson confidence intervals, and comparative baseline analysis.")

    ev_runs = _run_dirs()
    if ev_runs:
        sel_ev_str = st.selectbox(
            "Select Run Artifact to Inspect",
            options=[str(r) for r in ev_runs],
            format_func=lambda x: f"{Path(x).parent.name} ({x})",
            key="ev_select",
        )
        p = Path(sel_ev_str)

        mcol1, mcol2, mcol3, mcol4 = st.columns(4)
        if (p / "scorecard.json").exists():
            sc = json.loads((p / "scorecard.json").read_text(encoding="utf-8"))
            with mcol1:
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>Verification Score</div><div class='kpi-value'>{sc['score']:.0%}</div><div class='kpi-caption'>{sc['passed']} of {sc['total']} cases passed</div></div>",
                    unsafe_allow_html=True,
                )
            with mcol2:
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>95% Wilson CI</div><div class='kpi-value'>[{sc['wilson_low']:.0%}, {sc['wilson_high']:.0%}]</div><div class='kpi-caption'>Statistically sound error bounds</div></div>",
                    unsafe_allow_html=True,
                )

        if (p / "ledger.json").exists():
            ledger = json.loads((p / "ledger.json").read_text(encoding="utf-8"))
            totals = ledger.get("totals", {})
            with mcol3:
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>Model Calls</div><div class='kpi-value'>{totals.get('calls', 0)}</div><div class='kpi-caption'>{totals.get('latency_ms', 0) / 1000:.1f}s total latency</div></div>",
                    unsafe_allow_html=True,
                )
            with mcol4:
                tokens = totals.get("in_tokens", 0) + totals.get(
                    "out_tokens", 0
                )
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>Token Budget</div><div class='kpi-value'>{tokens:,}</div><div class='kpi-caption'>{totals.get('in_tokens', 0):,} in / {totals.get('out_tokens', 0):,} out</div></div>",
                    unsafe_allow_html=True,
                )

        if (p / "scorecard_baseline_human.json").exists():
            st.markdown("### Comparative Evaluation: Autonomous Factory vs. Human-Authored Baseline")
            base_sc = json.loads(
                (p / "scorecard_baseline_human.json").read_text(
                    encoding="utf-8"
                )
            )
            bcol1, bcol2 = st.columns(2)
            with bcol1:
                delta = sc["score"] - base_sc["score"]
                st.markdown(
                    f"""
                <div class="kpi-card" style="border-left: 4px solid #10b981;">
                  <div class="kpi-label">Autonomous Factory Agent</div>
                  <div class="kpi-value">{sc['score']:.0%} <span style="font-size:14px; color:#10b981;">(+{delta:.0%})</span></div>
                  <div class="kpi-caption">95% CI [{sc['wilson_low']:.0%}, {sc['wilson_high']:.0%}] | Passed {sc['passed']}/{sc['total']}</div>
                </div>
                """,
                    unsafe_allow_html=True,
                )
            with bcol2:
                st.markdown(
                    f"""
                <div class="kpi-card" style="border-left: 4px solid #94a3b8;">
                  <div class="kpi-label">Human-Authored Baseline</div>
                  <div class="kpi-value">{base_sc['score']:.0%}</div>
                  <div class="kpi-caption">95% CI [{base_sc['wilson_low']:.0%}, {base_sc['wilson_high']:.0%}] | Passed {base_sc['passed']}/{base_sc['total']}</div>
                </div>
                """,
                    unsafe_allow_html=True,
                )
            st.caption(
                "Human author missed specific policy lookups (sick leave certification thresholds, carryover limits) that exhaustive chunk coverage captured."
            )

        if (p / "iterations.json").exists():
            st.markdown("### Optimization Iterations and Surgical Patches")
            it_data = json.loads(
                (p / "iterations.json").read_text(encoding="utf-8")
            )
            entries = it_data.get("entries", [])
            if entries:
                rows = []
                for entry in entries:
                    sc_i = entry.get("scorecard", {})
                    patches = entry.get("patches", [])
                    if patches:
                        for patch in patches:
                            rows.append(
                                {
                                    "Iteration": f"Iter {sc_i.get('iteration', 0)}",
                                    "Score": f"{sc_i.get('score', 0):.0%}",
                                    "Target Failure Class": patch.get(
                                        "failure_class", ""
                                    ),
                                    "Surgical Modification": patch.get(
                                        "change", ""
                                    ),
                                    "Score Trajectory": f"{patch.get('score_before', 0):.0%} -> {patch.get('score_after', 0):.0%}",
                                }
                            )
                    else:
                        rows.append(
                            {
                                "Iteration": f"Iter {sc_i.get('iteration', 0)}",
                                "Score": f"{sc_i.get('score', 0):.0%}",
                                "Target Failure Class": "Initial Synthesis",
                                "Surgical Modification": entry.get(
                                    "note", "Base candidate generated"
                                ),
                                "Score Trajectory": "-",
                            }
                        )
                st.dataframe(rows, use_container_width=True)

        if (p / "report.md").exists():
            st.markdown("---")
            st.markdown("### Verified Quality Report")
            st.markdown((p / "report.md").read_text(encoding="utf-8"))
