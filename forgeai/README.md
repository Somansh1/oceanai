# ForgeAI

**The agent that builds agents.** Give it a one-paragraph brief and a folder of
documents; it interviews the requester, drafts the agent, compiles an adversarial
eval set from the documents themselves, judges the results with a layered
deterministic-first scorer, diagnoses failures from retrieval telemetry, applies
surgical patches, and ships a runnable agent plus an honest quality report.

> Core thesis: **never ask a small model for an opinion — ask it a thousand
> yes/no questions and let code add up the answers.**

Everything runs local-first on a 7B open model (Ollama, `qwen2.5:7b-instruct`) — no cloud
dependencies in the factory itself.

## Quickstart

```bash
cd forgeai
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev,ui]"

# ollama with the models pulled:
#   ollama pull qwen2.5:7b-instruct && ollama pull nomic-embed-text

# build an agent from a brief + document folder (unattended by default)
forge build --brief demos/hr/brief.md --docs demos/hr/docs --out runs/myagent --auto

# talk to the produced agent
forge chat runs/myagent

# compile evals, run them, judge them, score honestly
forge evaluate runs/myagent

# the critic-optimizer loop: triage -> one surgical patch -> re-eval
forge optimize runs/myagent

# the honest report (the product; the agent is evidence)
forge report runs/myagent

# documents changed? re-run the old eval set, see what broke
forge regression runs/myagent --docs demos/hr/docs

# optional UI (Factory / Runner / Evidence tabs)
streamlit run ui/app.py
```

## Architecture

```mermaid
flowchart TD
    classDef inputStyle fill:#1e293b,stroke:#0284c7,stroke-width:1.5px,color:#f8fafc;
    classDef stageStyle fill:#0f172a,stroke:#334155,stroke-width:1.5px,color:#f8fafc;
    classDef docStyle fill:#1e293b,stroke:#475569,stroke-width:1px,color:#cbd5e1;
    classDef outputStyle fill:#0284c7,stroke:#38bdf8,stroke-width:2px,color:#ffffff;
    classDef judgeStyle fill:#162032,stroke:#0ea5e9,stroke-width:1.5px,color:#f8fafc;

    subgraph Inputs["1. Specification and Grounding"]
        direction TB
        BR["Unstructured Paragraph Brief"]:::inputStyle
        DOCS["Document Corpus (PDF, CSV, MD, DOCX)"]:::inputStyle
        II["1. Intake Interviewer<br/>(<= 5 questions, tagged decisions, --auto)"]:::stageStyle
        GG["2. Groundability Guard<br/>(Topic x Evidence Density Matrix)"]:::stageStyle
        REQ["Requirements Document<br/>(Scopes, Tone, Must-Refuse List)"]:::docStyle

        BR --> II
        DOCS --> II
        DOCS --> GG
        II --> GG
        GG --> REQ
    end

    subgraph Synthesis["2. Synthesis and Binding"]
        direction TB
        AG["3. Agent Generator<br/>(Prompt Tournament on Pilot)"]:::stageStyle
        TB["Keyword Tool Selector<br/>(Enforced bindings + logged rejections)"]:::stageStyle
        AD["Agent Definition<br/>(System Prompt, Retrieval Knobs, Output Contract)"]:::docStyle

        REQ --> AG
        DOCS --> AG
        AG --> TB
        TB --> AD
    end

    subgraph EvalAndJudge["3. Adversarial Quality Gate"]
        direction TB
        EC["4. Eval Compiler<br/>(Stratified Archetypes, Canaries, Pairs)"]:::stageStyle
        ES["Adversarial Eval Set<br/>(Self-verified Chunk Facts)"]:::docStyle
        LJ["5. Layered Multi-Tier Judge"]:::judgeStyle
        L0["L0 Deterministic Verification<br/>(Citations in Index, Schemas, Derivations)"]:::judgeStyle
        L1["L1 Micro-Binary Verification<br/>(Atomic Fact Entailment)"]:::judgeStyle

        DOCS --> EC
        EC --> ES
        AD --> LJ
        ES --> LJ
        LJ --> L0
        LJ --> L1
    end

    subgraph Optimization["4. Critic-Optimizer and Delivery"]
        direction TB
        CO["6. Critic-Optimizer Loop<br/>(Telemetry Triage, Surgical Patches)"]:::stageStyle
        HR["7. Honest Quality Report<br/>(Wilson CIs, Triage, Failure Postmortem)"]:::outputStyle
        RUN["8. Runnable Shipped Agent<br/>(CLI and Streamlit Dashboard)"]:::outputStyle

        L0 --> CO
        L1 --> CO
        CO -- "Pass Rate Below Target (max 3 iters)" --> AG
        CO -- "Converged or Budget Exhausted" --> HR
        AD --> RUN
    end

    Inputs --> Synthesis
    Synthesis --> EvalAndJudge
    EvalAndJudge --> Optimization
```

## Design principles

1. **LLM proposes, code disposes.** Control flow, validation, retries, budget
   and scoring aggregation are Python. The model only fills typed slots
   (Pydantic v2 + JSON repair loop with exact validation errors).
2. **Never ask a small model for an opinion.** Judging decomposes into binary
   micro-calls aggregated mechanically. Deterministic checks dominate; where
   code can decide (numbers, citations, absence-of-evidence), code decides —
   and disagreements with the model are logged, not hidden.
3. **Every artifact is typed and carries provenance.** Chunks, claims, eval
   cases, verdicts, patches — all know which doc/chunk/prompt produced them.
4. **The output contract is the measurement instrument.** One schema serves
   the runner (enforced by the repair loop), the judge (scores against it)
   and the report.
5. **Distrust defaults — verify, then trust.** The eval set defends itself:
   expected facts must survive their own grounding chunk; refusal cases must
   pass an answerability gate; near-duplicates die. Every override is flagged
   in the artifacts.
6. **Honesty is a feature.** Wilson intervals, per-class failure taxonomy,
   unexplained-failure list, cost ledger. The report explains its number.

## The three committed runs

| | Run A — ShoreHR | Run B — PortOps (marine) | Cold Run — Library (unseen) |
|---|---|---|---|
| corpus | HR policy doc | berth-schedule CSV + bunker CSV + tariff doc | library lending rules doc |
| tools attached | 0 (all 4 rejected, reasons logged) | all 4 (incl. live open-meteo marine) | 0 (all tools rejected) |
| score | **86% [60–96%]** | **61% [39–80%]** | **79% [57–91%]** |
| hardness | factual coverage | multi-step arithmetic + date-scoped lookups | borrowing limits + sanctions |

Run B is deliberately harder — the contrast is the evidence of generality.
Library was an unseen domain tested to verify that the factory builds unattended without tuning.
All three reports (`demos/*/run/report.md`) state what still fails and why.

**Factory vs human baseline** (stretch goal): a hand-written agent evaluated
on the same set and judge scored **71% [45–88%]** vs the factory's 86% —
see `demos/hr/baseline_human/` with method and self-preference disclosure.

## Testing

Run the automated test suite with:

```bash
python -m pytest tests -v
```

## What the factory caught in itself (excerpt)

Every guard in this repo was added after a live failure, including:
- eval facts that contradicted their own source chunk (killed at compile time)
- canaries planted on topics the corpus actually covered (answerability gate)
- the tool selector rejecting tools the brief explicitly demanded
  (keyword-rule enforcement, labeled "ENFORCED" in the binding)
- the groundability guard rewriting covered topics into must-refuse,
  making the agent refuse its own core scope (synonym classes + logged
  deterministic override)
- the judge failing correct answers: "USD 4,500" vs "USD 4,500 per call",
  a correct 770.83/hour derivation vs an 18,500/day rule (numeric
  deterministic matching)

Full history in `git log` — every commit documents the failure that
motivated its fix.

## Repository layout

```
src/forge/       intake, generate, evals, judge, critic, runner, tools, regression, report
tests/           automated pytest suite (18 unit tests covering specs, tools, stats, ingest, BM25)
prompts/         11 numbered generation prompts (committed, hash-referenced)
demos/hr/        run A: full artifacts + human baseline + regression-ready
demos/portops/   run B: full artifacts
demos/library/   cold run: third unseen domain full artifacts
demos/synth/     document synthesis intent
ui/app.py        Streamlit: Factory / Runner / Evidence
```


