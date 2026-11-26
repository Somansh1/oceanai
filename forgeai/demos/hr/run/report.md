# Factory Report — Leave Policy Advisor

Produced by ForgeAI. Definition version 2, iteration 1.

## Requirements (as compiled by the factory)

| topic | status | density | evidence | note |
|---|---|---|---|---|
| Annual Leave Entitlement | supported | 0.33 | d01#c000 | The chunk provides details on the annual leave entitlement, including the number of days, pro-rata entitlement, carryove |
| Sick Leave | supported | 0.67 | d01#c000, d01#c001 | Both chunks [d01#c000] and [d01#c001] contain information about sick leave policies, including the number of paid sick d |
| Parental Leave | supported | 0.33 | d01#c002 | The chunk from 'Unpaid Leave and Sabbatical' section directly states the parental leave entitlements, including the numb |
| Unpaid Leave and Sabbatical | supported | 0.67 | d01#c001, d01#c002 | The chunks from 'd01#c001' and 'd01#c002' provide direct evidence about unpaid leave and sabbatical policies, including  |

Auto-resolved assumptions: 5 (each logged in requirements.json).

## Tool selection

| tool | rationale |
|---|---|
| ~~csv_lookup~~ (rejected) | Not relevant to the HR leave policy documents. |
| ~~calculator~~ (rejected) | No arithmetic calculations are needed for the leave policies. |
| ~~now~~ (rejected) | Current date and time are not required for answering leave policy questions. |
| ~~open_meteo~~ (rejected) | Weather information is not relevant to the leave policies. |

## Eval set (generated from the documents, gates applied)

| kind | cases |
|---|---|
| ambiguous | 2 |
| answerable | 7 |
| canary | 2 |
| cross_doc | 2 |
| numeric | 2 |
| refusal | 1 |
| rephrase_a | 2 |
| rephrase_b | 2 |

## Optimization iterations

| iteration | score | patched class | change | Δ |
|---|---|---|---|---|
| iter 0 | 14/20 (70%) | hallucination | appended 'Refusal discipline' section: refuse when the SPECIFIC fact is absent, even if the topic is covered | 70% → 75% |
| iter 1 | 15/20 (75%) | — | no patchable failure class remains (all already patched) | — |

### Prompt tournament (pilot subset)

| candidate | pilot score |
|---|---|
| candidate-1 | 60% |
| candidate-2 | 60% |
| candidate-3 | 80% |

## Final scorecard

| passed | total | score | 95% CI |
|---|---|---|---|
| 14 | 20 | 70% | [48%, 85%] |

## What still fails and why (6 cases)

| id | kind | class | question | why |
|---|---|---|---|---|
| q05 | cross_doc | hallucination | What is the maximum number of days a shore-based staff member can carry over fro | ungrounded claim; missed 1 fact(s): Shore staff receive 10 paid sick days per year. |
| q06 | canary | hallucination | What is the process for requesting a sabbatical leave, and how does it differ fr | answered instead of refusing |
| q07 | ambiguous | hallucination | How many working days of annual leave can a new employee join in August 2024 and | ungrounded claim |
| q11 | canary | hallucination | What is the exact number of public holidays observed by Northwind Maritime Ltd i | answered instead of refusing |
| q12 | cross_doc | hallucination | If an employee is on parental leave for 16 weeks and then takes 2 weeks of unpai | ungrounded claim; missed 1 fact(s): Staff with 3+ years of service may apply for unpaid leave be |
| q19 | answerable | hallucination | How does the entitlement for unpaid leave compare between staff with 2 years of  | ungrounded claim |

## Factory vs Human Baseline

| agent | passed | total | score | 95% CI |
|---|---|---|---|---|
| Factory | 14 | 20 | 70% | [48%, 85%] |
| Human Baseline | 13 | 20 | 65% | [43%, 82%] |

Delta: `+5%`.
- Factory beats human on: q02
- Factory loses to human on: none

## How this was judged

- **L0 deterministic**: citation IDs validated against the index and retrieved context; refusals read from the output contract (schema field, not prose); numeric answers checked deterministically within 2% relative tolerance; retrieval telemetry recorded per case.
- **L1 micro-binary**: every expected fact checked against the answer as a single YES/NO entailment call, plus answer groundedness verified against cited chunks and tool outputs; coverage aggregated mechanically without holistic scoring or position/verbosity ranking bias.
- **Eval-set self-defense**: expected facts verified against their own grounding chunk at generation time; refusal/canary cases passed an answerability gate; near-duplicates dropped.

## Cost ledger

| stage | calls | in tokens | out tokens |
|---|---|---|---|
| agent_answer | 75 | 55638 | 4554 |
| eval_answerable | 17 | 10957 | 1020 |
| eval_canary | 16 | 10929 | 1222 |
| eval_edge | 6 | 3380 | 1018 |
| eval_fact_verify | 22 | 7754 | 44 |
| eval_refusal | 16 | 10855 | 1104 |
| eval_refusal_gate | 3 | 1657 | 6 |
| eval_rephrase | 2 | 346 | 50 |
| groundability | 4 | 2956 | 383 |
| interview | 1 | 521 | 287 |
| judge_grounded | 60 | 22983 | 120 |
| judge_l1 | 29 | 6796 | 58 |
| judge_pair | 2 | 358 | 4 |
| judge_reframe | 23 | 8709 | 46 |
| prompt_candidate | 3 | 1673 | 456 |
| requirements | 2 | 1627 | 499 |
| tool_selection | 1 | 717 | 186 |

Total: 282 calls, 158913 tokens, 322s model time.

---

*A factory that claims 100% is suspicious; this one explains its 70%.*