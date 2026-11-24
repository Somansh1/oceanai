# Factory Report — Berthing Assistant

Produced by ForgeAI. Definition version 3, iteration 2.

## Requirements (as compiled by the factory)

| topic | status | density | evidence | note |
|---|---|---|---|---|
| vessel berthing information | supported | 0.20 | d03#c000 | The chunk from 'Meridian Harbour — Port Tariffs & Operating Rules (Rev. 7, effective 1 Nov 2026)' contains information a |
| next vessel arrival at a berth | supported | 0.00 | — | supported via attached tool 'now' (live data) |
| berth change or stay costs (port dues, occupancy, demurrage, pilotage by LOA, tugs) | supported | 0.40 | d03#c000, d03#c001 | The chunks from 'd03#c000' and 'd03#c001' provide evidence related to berth change or stay costs, including port dues, b |
| current sea conditions at the port | supported | 0.00 | — | supported via attached tool 'open_meteo' (live data) |

Auto-resolved assumptions: 2 (each logged in requirements.json).

## Tool selection

| tool | rationale |
|---|---|
| csv_lookup | Needed to retrieve vessel berthing information and bunker prices |
| calculator | Required for exact arithmetic in calculating berth change or stay costs |
| open_meteo | Needed to check current sea conditions at the port |
| now | ENFORCED — brief keyword rule matched 'next vessel'; rejected by selector |
| ~~csv_lookup~~ (rejected) | Not needed for checking current sea conditions |

## Eval set (generated from the documents, gates applied)

| kind | cases |
|---|---|
| answerable | 8 |
| canary | 3 |
| numeric | 1 |
| refusal | 2 |
| rephrase_a | 2 |
| rephrase_b | 2 |

## Optimization iterations

| iteration | score | patched class | change | Δ |
|---|---|---|---|---|
| iter 0 | 8/18 (44%) | hallucination | appended 'Refusal discipline' section: refuse when the SPECIFIC fact is absent, even if the topic is covered | 44% → 50% |
| iter 0 | 9/18 (50%) | — | post-patch re-eval (170s) | — |
| iter 1 | 9/18 (50%) | prompt_defect | appended 'Answer completeness' section: comparisons must state both sides; totals + rules | 50% → 61% |
| iter 1 | 11/18 (61%) | — | post-patch re-eval (182s) | — |
| iter 2 | 11/18 (61%) | — | no patchable failure class remains (all already patched) | — |

### Prompt tournament (pilot subset)

| candidate | pilot score |
|---|---|
| candidate-1 | 0% |
| candidate-2 | 40% |
| candidate-3 | 20% |

## Final scorecard

| passed | total | score | 95% CI |
|---|---|---|---|
| 11 | 18 | 61% | [39%, 80%] |

## What still fails and why (7 cases)

| id | kind | class | question | telemetry |
|---|---|---|---|---|
| q01 | rephrase_b | hallucination | Which ship is currently docked at berth number 2? | cov=0.00 |
| q05 | numeric | hallucination | What is the price difference between VLSFO from Harbour Fuel Partners and VLSFO from Delta | cov=1.00 |
| q07 | refusal | hallucination | What is the specific procedure for berthing a vessel that is 350 meters long at Meridian H | cov=0.00 |
| q09 | answerable | hallucination | Which type of vessel receives more free time at Meridian Harbour and by how many hours? | cov=0.00 |
| q10 | rephrase_a | hallucination | What is the name of the vessel berthed at berth B2? | cov=0.00 |
| q12 | answerable | hallucination | What is the waste disposal charge for a vessel with a length of 180 meters? | cov=0.00 |
| q18 | answerable | hallucination | What is the name of the vessel scheduled to berth at WH1 on December 12, 2026? | cov=0.00 |

## How this was judged

- **L0 deterministic**: citation IDs validated against the index; refusals read from the output contract (schema field, not prose); numeric answers recomputed by the calculator tool; retrieval telemetry recorded per case.
- **L1 micro-binary**: every expected fact checked against the answer as a single YES/NO entailment call; coverage aggregated mechanically. No holistic opinions, no position/verbosity bias surface.
- **Eval-set self-defense**: expected facts verified against their own grounding chunk at generation time; refusal/canary cases passed an answerability gate; near-duplicates dropped.

## Cost ledger

| stage | calls | in tokens | out tokens |
|---|---|---|---|

Total: 0 calls, 0 tokens, 0s model time.

---

*A factory that claims 100% is suspicious; this one explains its 61%.*