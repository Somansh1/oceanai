# Factory Report — HR Department

Produced by ForgeAI. Definition version 2, iteration 1.

## Requirements (as compiled by the factory)

| topic | status | density | evidence | note |
|---|---|---|---|---|
| Annual Leave Entitlement | supported | 0.33 | d01#c000 | The chunk provides details on the annual leave entitlement, including the number of days, pro-rata entitlement, carryove |
| Sick Leave | supported | 0.67 | d01#c000, d01#c001 | Both chunks [d01#c000] and [d01#c001] contain information about sick leave policies, including the number of paid sick d |
| Parental Leave | supported | 0.33 | d01#c002 | The chunk from 'Unpaid Leave and Sabbatical' section directly states the parental leave entitlements, including the numb |
| Unpaid Leave and Sabbatical | supported | 0.67 | d01#c001, d01#c002 | The chunks from 'd01#c001' and 'd01#c002' provide direct evidence about unpaid leave and sabbatical policies, including  |
| Public Holidays | supported | 1.00 | d01#c002 | The chunk discusses the company's observance of public holidays, including the number of holidays, compensatory days, an |

Auto-resolved assumptions: 1 (each logged in requirements.json).

## Tool selection

| tool | rationale |
|---|---|
| open_meteo | ENFORCED — brief keyword rule matched 'wind'; rejected by selector |
| ~~csv_lookup~~ (rejected) | No CSV file is needed for the HR policy questions. |
| ~~calculator~~ (rejected) | No arithmetic calculations are required for the HR policy questions. |
| ~~now~~ (rejected) | The current date and time are not relevant to answering HR policy questions. |

## Eval set (generated from the documents, gates applied)

| kind | cases |
|---|---|
| answerable | 6 |
| canary | 3 |
| refusal | 1 |
| rephrase_a | 2 |
| rephrase_b | 2 |

## Optimization iterations

| iteration | score | patched class | change | Δ |
|---|---|---|---|---|
| iter 0 | 13/14 (93%) | hallucination | appended 'Refusal discipline' section: refuse when the SPECIFIC fact is absent, even if the topic is covered | 93% → 86% |
| iter 0 | 12/14 (86%) | — | post-patch re-eval (98s) | — |
| iter 1 | 12/14 (86%) | — | no patchable failure class remains (all already patched) | — |

### Prompt tournament (pilot subset)

| candidate | pilot score |
|---|---|
| candidate-1 | 60% |
| candidate-2 | 80% |
| candidate-3 | 80% |

## Final scorecard

| passed | total | score | 95% CI |
|---|---|---|---|
| 12 | 14 | 86% | [60%, 96%] |

## What still fails and why (2 cases)

| id | kind | class | question | telemetry |
|---|---|---|---|---|
| q01 | answerable | hallucination | How many working days of annual leave are entitled to a shore-based employee who joined No | cov=0.00 |
| q04 | answerable | hallucination | How many public holidays does the company observe at its registered office location? | cov=0.00 |

## How this was judged

- **L0 deterministic**: citation IDs validated against the index; refusals read from the output contract (schema field, not prose); numeric answers recomputed by the calculator tool; retrieval telemetry recorded per case.
- **L1 micro-binary**: every expected fact checked against the answer as a single YES/NO entailment call; coverage aggregated mechanically. No holistic opinions, no position/verbosity bias surface.
- **Eval-set self-defense**: expected facts verified against their own grounding chunk at generation time; refusal/canary cases passed an answerability gate; near-duplicates dropped.

## Cost ledger

| stage | calls | in tokens | out tokens |
|---|---|---|---|

Total: 0 calls, 0 tokens, 0s model time.

---

*A factory that claims 100% is suspicious; this one explains its 86%.*