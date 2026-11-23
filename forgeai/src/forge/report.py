"""Honest report builder: the product is the report, the agent is evidence."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def build_report(run_dir: Path) -> str:
    req = json.loads((run_dir / "requirements.json").read_text(encoding="utf-8"))
    defn = json.loads((run_dir / "definition.json").read_text(encoding="utf-8"))
    cases = [json.loads(l) for l in (run_dir / "evalset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    results = [json.loads(l) for l in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    scorecard = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))
    ledger = json.loads((run_dir / "ledger.json").read_text(encoding="utf-8"))
    iterations = json.loads((run_dir / "iterations.json").read_text(encoding="utf-8")) \
        if (run_dir / "iterations.json").exists() else None

    L: list[str] = []
    L.append(f"# Factory Report — {defn['name']}")
    L.append("")
    L.append(f"Produced by ForgeAI. Definition version {defn['version']}, "
             f"iteration {defn['iteration']}.")
    L.append("")

    L.append("## Requirements (as compiled by the factory)")
    L.append("")
    g = req.get("groundability", {})
    rows = [[r["topic"], r["status"], f"{r['evidence_density']:.2f}",
             ", ".join(r["supporting_chunk_ids"]) or "—",
             (r.get("note") or "")[:120]] for r in g.get("rows", [])]
    L.append(_table(["topic", "status", "density", "evidence", "note"], rows))
    L.append("")
    overrides = [r for r in g.get("rows", [])
                 if r.get("note") and "DETERMINISTIC OVERRIDE" in r["note"]]
    if overrides:
        L.append(f"**Groundability overrides: {len(overrides)}** — the guard model disputed "
                 "verified evidence; code overruled, disagreement retained above.")
        L.append("")
    if req.get("assumptions"):
        L.append(f"Auto-resolved assumptions: {len(req['assumptions'])} "
                 "(each logged in requirements.json).")
        L.append("")

    L.append("## Tool selection")
    L.append("")
    trows = [[t["name"], t["justification"][:100]] for t in defn.get("tools", [])]
    trows += [[f"~~{t['name']}~~ (rejected)", t["reason"][:100]]
              for t in defn.get("rejected_tools", [])]
    L.append(_table(["tool", "rationale"], trows or [["(none)", "—"]]))
    L.append("")

    kinds = Counter(c["kind"] for c in cases)
    L.append("## Eval set (generated from the documents, gates applied)")
    L.append("")
    L.append(_table(["kind", "cases"], sorted(kinds.items())))
    L.append("")

    if iterations:
        L.append("## Optimization iterations")
        L.append("")
        irows = []
        for e in iterations.get("entries", []):
            sc = e["scorecard"]
            note = e.get("note", "")
            for p in e.get("patches", []):
                irows.append([f"iter {sc['iteration']}",
                              f"{sc['passed']}/{sc['total']} ({sc['score']:.0%})",
                              f"{p['failure_class']}", p["change"][:110],
                              f"{p['score_before']:.0%} → {p['score_after']:.0%}"])
            if not e.get("patches"):
                irows.append([f"iter {sc['iteration']}",
                              f"{sc['passed']}/{sc['total']} ({sc['score']:.0%})",
                              "—", note[:110], "—"])
        L.append(_table(["iteration", "score", "patched class", "change", "Δ"], irows))
        L.append("")
        if iterations.get("tournament_log"):
            L.append("### Prompt tournament (pilot subset)")
            L.append("")
            L.append(_table(["candidate", "pilot score"],
                            [[t.get("candidate", "?"), f"{t.get('pilot_score', 0):.0%}"]
                             for t in iterations["tournament_log"] if "candidate" in t]))
            L.append("")

    L.append("## Final scorecard")
    L.append("")
    L.append(_table(["passed", "total", "score", "95% CI"],
                    [[scorecard["passed"], scorecard["total"],
                      f"{scorecard['score']:.0%}",
                      f"[{scorecard['wilson_low']:.0%}, {scorecard['wilson_high']:.0%}]"]]))
    L.append("")

    fails = [r for r in results if not r["passed"]]
    case_by_id = {c["id"]: c for c in cases}
    L.append(f"## What still fails and why ({len(fails)} cases)")
    L.append("")
    if not fails:
        L.append("Nothing fails. Treat this claim with suspicion and re-run.")
    else:
        frows = []
        for r in fails:
            c = case_by_id.get(r["case_id"], {})
            frows.append([r["case_id"], c.get("kind", "?"),
                          (r.get("failure_class") or "unclassified"),
                          c.get("question", "")[:90],
                          f"cov={r.get('fact_coverage', 0):.2f}"])
        L.append(_table(["id", "kind", "class", "question", "telemetry"], frows))
    L.append("")

    totals = ledger.get("totals", {})
    L.append("## How this was judged")
    L.append("")
    L.append("- **L0 deterministic**: citation IDs validated against the index; refusals read "
             "from the output contract (schema field, not prose); numeric answers recomputed "
             "by the calculator tool; retrieval telemetry recorded per case.")
    L.append("- **L1 micro-binary**: every expected fact checked against the answer as a "
             "single YES/NO entailment call; coverage aggregated mechanically. No holistic "
             "opinions, no position/verbosity bias surface.")
    L.append("- **Eval-set self-defense**: expected facts verified against their own "
             "grounding chunk at generation time; refusal/canary cases passed an "
             "answerability gate; near-duplicates dropped.")
    L.append("")
    L.append("## Cost ledger")
    L.append("")
    by_stage = ledger.get("by_stage", {})
    L.append(_table(["stage", "calls", "in tokens", "out tokens"],
                    [[s, v.get("calls", 0), v.get("in_tokens", 0), v.get("out_tokens", 0)]
                     for s, v in sorted(by_stage.items())]))
    L.append("")
    L.append(f"Total: {totals.get('calls', 0)} calls, "
             f"{totals.get('in_tokens', 0) + totals.get('out_tokens', 0)} tokens, "
             f"{totals.get('latency_ms', 0) / 1000:.0f}s model time.")
    L.append("")
    L.append("---")
    L.append("")
    L.append("*A factory that claims 100% is suspicious; this one explains its "
             f"{scorecard['score']:.0%}.*")
    return "\n".join(L)

