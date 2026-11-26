# Factory Report — Berth Information Officer

Produced by ForgeAI. Definition version 2, iteration 2.

## Requirements (as compiled by the factory)

| topic | status | density | evidence | note |
|---|---|---|---|---|
| Berth occupancy charges | supported | 0.40 | d03#c002, d03#c000 | The chunks from 'd03#c002' and 'd03#c000' contain information about berth occupancy charges, which directly addresses th |
| Pilotage by LOA | supported | 0.20 | d03#c001 | deterministic corroboration: 'Pilotage by LOA' terms found verbatim in d03#c001; model verdict disputed, re-asked with e |
| Tugs | supported | 0.20 | d03#c001 | deterministic corroboration: 'Tugs' terms found verbatim in d03#c001; model verdict disputed, re-asked with evidence quo |
| Current sea conditions at the port | supported | 0.20 | d03#c001 | deterministic corroboration: 'Current sea conditions at the port' terms found verbatim in d03#c001; model verdict disput |

**Groundability overrides: 1** — the guard model disputed verified evidence; code overruled, disagreement retained above.

Auto-resolved assumptions: 5 (each logged in requirements.json).

## Tool selection

| tool | rationale |
|---|---|
| csv_lookup | Needed to look up vessel berth information and tariff details. |
| calculator | Required for exact arithmetic in calculating berth occupancy charges, pilotage costs, and demurrage. |
| open_meteo | Needed to check current sea conditions at the port for movement windows. |
| now | ENFORCED — brief keyword rule matched 'next vessel'; rejected by selector |

## Eval set (generated from the documents, gates applied)

| kind | cases |
|---|---|
| ambiguous | 2 |
| answerable | 10 |
| canary | 3 |
| cross_doc | 1 |
| numeric | 2 |
| refusal | 1 |
| rephrase_a | 2 |
| rephrase_b | 2 |

## Optimization iterations

| iteration | score | patched class | change | Δ |
|---|---|---|---|---|
| iter 0 | 8/23 (35%) | hallucination | appended 'Refusal discipline' section: refuse when the SPECIFIC fact is absent, even if the topic is covered | 35% → 43% |
| iter 1 | 10/23 (43%) | prompt_defect | appended 'Output format reminder' section: JSON-only responses enforced [ROLLED BACK: score dropped 43% -> 35% | 43% → 35% |
| iter 1 | 8/23 (35%) | — | post-patch re-eval rejected & rolled back (288s) | — |
| iter 2 | 10/23 (43%) | — | no patchable failure class remains (all already patched) | — |

### Prompt tournament (pilot subset)

| candidate | pilot score |
|---|---|
| candidate-1 | 60% |
| candidate-2 | 20% |
| candidate-3 | 60% |

## Final scorecard

| passed | total | score | 95% CI |
|---|---|---|---|
| 10 | 23 | 43% | [26%, 63%] |

## What still fails and why (13 cases)

| id | kind | class | question | why |
|---|---|---|---|---|
| q03 | answerable | prompt_defect | Which type of vessel receives more free time at berth and how much free time doe | missed 1 fact(s): dry cargo vessels receive 24 hours of free time at berth |
| q04 | answerable | hallucination | How much more does it cost to pilot a vessel with a length over 280 meters compa | ungrounded claim |
| q08 | answerable | hallucination | What is the total length of all vessels berthed in berth B1? | ungrounded claim; missed 1 fact(s): MV ORIENTAL BAY has a length of 186 m |
| q10 | answerable | hallucination | Which vessel has the longest length overall (LOA) and what is its length? | ungrounded claim; missed 2 fact(s): MV SIENNNA STAR has an LOA of 190 m |
| q11 | answerable | hallucination | Which supplier offers VLSFO at the lower price per ton at Meridian Harbour? | ungrounded claim; missed 1 fact(s): Vortex Bunkering offers VLSFO at 612 USD per ton |
| q12 | ambiguous | hallucination | If a vessel with an LOA of 270 meters arrives at the port and incurs demurrage d | ungrounded claim |
| q13 | cross_doc | prompt_defect | What would be the total cost for a tanker of 250 meters LOA to receive VLSFO fue | output contract JSON invalid; invalid/missing citations; ungrounded claim; missed 1 fact(s): VLSFO fuel from V |
| q14 | numeric | hallucination | What is the total difference in draft (in meters) between the vessel with the ma | ungrounded claim; numeric mismatch (expected 1.6); missed 1 fact(s): draft_m column in berth_schedule.csv |
| q15 | rephrase_b | hallucination | Which ship is currently docked at berth number 2? | ungrounded claim |
| q16 | answerable | hallucination | What is the flat fee for waste disposal for a 150 m LOA vessel? | ungrounded claim |
| q18 | answerable | hallucination | Which vessel has the earliest estimated time of departure (ETD) and what is its  | missed 1 fact(s): MV ANTIPODEAN SPIRIT has the earliest ETD of 2026-12-17 11:0 |
| q22 | numeric | hallucination | What is the total price difference in USD per ton between VLSFO and MGO supplied | ungrounded claim; numeric mismatch (expected -252.0); missed 1 fact(s): Vortex Bunkering supplies VLSFO and MG |
| q23 | rephrase_a | hallucination | What is the name of the vessel berthed at berth B2? | ungrounded claim; missed 1 fact(s): MV NORDIC PIONEER is berthed at berth B2 |

## How this was judged

- **L0 deterministic**: citation IDs validated against the index and retrieved context; refusals read from the output contract (schema field, not prose); numeric answers checked deterministically within 2% relative tolerance; retrieval telemetry recorded per case.
- **L1 micro-binary**: every expected fact checked against the answer as a single YES/NO entailment call, plus answer groundedness verified against cited chunks and tool outputs; coverage aggregated mechanically without holistic scoring or position/verbosity ranking bias.
- **Eval-set self-defense**: expected facts verified against their own grounding chunk at generation time; refusal/canary cases passed an answerability gate; near-duplicates dropped.

## Cost ledger

| stage | calls | in tokens | out tokens |
|---|---|---|---|
| agent_answer | 93 | 232904 | 7672 |
| eval_answerable | 37 | 31952 | 2474 |
| eval_canary | 16 | 12117 | 1280 |
| eval_edge | 14 | 9821 | 2399 |
| eval_fact_verify | 72 | 37396 | 144 |
| eval_refusal | 32 | 24449 | 2201 |
| eval_refusal_gate | 6 | 16968 | 12 |
| eval_rephrase | 4 | 719 | 125 |
| groundability | 4 | 5698 | 303 |
| groundability_reask | 6 | 4638 | 601 |
| interview | 1 | 836 | 262 |
| judge_grounded | 61 | 53746 | 122 |
| judge_l1 | 51 | 10879 | 102 |
| judge_pair | 2 | 331 | 4 |
| judge_reframe | 4 | 2151 | 8 |
| prompt_candidate | 3 | 2492 | 519 |
| requirements | 2 | 1901 | 536 |
| tool_loop | 117 | 250539 | 18540 |
| tool_selection | 1 | 1136 | 243 |

Total: 526 calls, 738220 tokens, 2203s model time.

---

*A factory that claims 100% is suspicious; this one explains its 43%.*