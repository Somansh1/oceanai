# Factory vs Human Baseline — Method & Honest Notes

Comparative baseline: hand-write one of the two demo agents as an expert baseline, run both through
the same generated eval set, and measure performance differences objectively.

## Method

- The human agent (`baseline_human/definition.json`) was authored by hand
  BEFORE looking at the factory's run A artifacts (fresh build, unspoiled).
- Both agents ran the SAME eval set (`demos/hr/run/evalset.jsonl`) through
  the SAME judge (deterministic + micro-binary) via
  `forge evaluate --definition <path>`.
- The factory's score is the committed `demos/hr/run/scorecard.json`.

## What I wrote by hand (design intent)

Direct, imperative system prompt built from reading the source doc once:
- grounding rule with explicit refused=true fallback
- numbers-first answer style with citations required
- refusal list copied from the brief verbatim
- no tools (a doc-lookup agent needs none)

## Honest expectations

- The human prompt is likely *tighter* on refusal cases (I wrote the refusal
  conditions knowing exactly what the evals probe) — that's the self-preference
  risk we disclose, not hide: the human author understood the domain's eval
  emphasis while writing.
- The factory is likely better on coverage of topics a single reader skims
  (it derives expected facts mechanically from every chunk).
- Where the human wins, it shows the factory's generator has headroom; where
  the factory wins, it shows the pipeline earns its complexity. Both results
  are reported as-is, numbers first.
