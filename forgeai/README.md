# ForgeAI

**The agent that builds agents.** Give it a one-paragraph brief and a folder of
documents; it interviews the requester, drafts the agent, compiles an adversarial
eval set from the documents themselves, judges the results with a layered
deterministic-first scorer, diagnoses failures from retrieval telemetry, applies
surgical patches, and ships a runnable agent plus an honest quality report.

> Core thesis: **never ask a small model for an opinion — ask it a thousand
> yes/no questions and let code add up the answers.**

Status: scaffold (day 1). See `PLAN.md` in the parent folder for the full
architecture and attack plan.

## Quickstart

```bash
cd forgeai
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"

# chunk + index a document folder (works without ollama: BM25-only, honestly logged)
forge ingest --docs demos/hr/docs --out runs/scratch/hr

# with ollama running locally (qwen2.5 + nomic-embed-text pulled):
#   dense+sparse hybrid retrieval kicks in automatically
```

## Layout

```
src/forge/     orchestrator, intake, generator, evals, judge, critic, runner, tools
prompts/       numbered generation prompts (committed artifacts, hash-referenced)
demos/         two full committed runs + synthesized source documents
gold/          hand-labeled judge-calibration cases
runs/          every factory run, manifest-addressed
```
