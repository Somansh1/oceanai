# Factory Report — Library Assistant

Produced by ForgeAI. Definition version 2, iteration 2.

## Requirements (as compiled by the factory)

| topic | status | density | evidence | note |
|---|---|---|---|---|
| Loan periods and limits | supported | 0.33 | d01#c000 | The chunk [d01#c000] directly addresses the topic of 'Loan periods and limits' by providing specific details on the numb |
| Renewals | supported | 0.67 | d01#c000, d01#c001 | The chunks from both 'd01#c000' and 'd01#c001' contain information about the renewal process, which directly addresses t |
| Fines and fees | supported | 0.33 | d01#c001 | Chunk d01#c001 directly addresses fines and fees, providing specific details about overdue fines, short-loan fees, lost  |
| Holds and recalls | supported | 0.67 | d01#c000, d01#c001 | Both chunks [d01#c000] and [d01#c001] contain information about holds and recalls, specifically mentioning that items wi |
| Inter-library loans | supported | 0.67 | d01#c001, d01#c002 | Both chunk d01#c001 and chunk d01#c002 contain information about inter-library loans, including the number of requests p |

Auto-resolved assumptions: 5 (each logged in requirements.json).

## Tool selection

| tool | rationale |
|---|---|
| ~~csv_lookup~~ (rejected) | No CSV file provided for lookup. |
| ~~calculator~~ (rejected) | No arithmetic expressions needed in the brief. |
| ~~now~~ (rejected) | No need for current date and time. |
| ~~open_meteo~~ (rejected) | No weather information required. |

## Eval set (generated from the documents, gates applied)

| kind | cases |
|---|---|
| ambiguous | 2 |
| answerable | 7 |
| canary | 1 |
| cross_doc | 2 |
| numeric | 1 |
| refusal | 4 |
| rephrase_a | 2 |
| rephrase_b | 2 |

## Optimization iterations

| iteration | score | patched class | change | Δ |
|---|---|---|---|---|
| iter 0 | 13/21 (62%) | hallucination | appended 'Refusal discipline' section: refuse when the SPECIFIC fact is absent, even if the topic is covered | 62% → 67% |
| iter 1 | 14/21 (67%) | wrong_refusal | appended 'Answer when grounded' section: refuse only when no chunk addresses the specifics [ROLLED BACK: score | 67% → 57% |
| iter 1 | 12/21 (57%) | — | post-patch re-eval rejected & rolled back (57s) | — |
| iter 2 | 14/21 (67%) | — | no patchable failure class remains (all already patched) | — |

### Prompt tournament (pilot subset)

| candidate | pilot score |
|---|---|
| candidate-1 | 40% |
| candidate-2 | 60% |
| candidate-3 | 40% |

## Final scorecard

| passed | total | score | 95% CI |
|---|---|---|---|
| 14 | 21 | 67% | [45%, 83%] |

## What still fails and why (7 cases)

| id | kind | class | question | why |
|---|---|---|---|---|
| q04 | numeric | wrong_refusal | What is the total fine for a standard item that is 16 days overdue? | cov=0.00 |
| q05 | cross_doc | hallucination | What is the maximum number of days an external member can keep a borrowed item i | ungrounded claim; missed 1 fact(s): Loans can be renewed up to 3 times if no other patron has pl |
| q12 | cross_doc | hallucination | What is the maximum fine a patron can incur for a lost short-loan item, and how  | ungrounded claim; missed 4 fact(s): Overdue standard items accrue fines of 30 pence per item per |
| q14 | answerable | hallucination | How long can a patron keep a standard loan item before it starts accruing fines? | missed 1 fact(s): standard items accrue fines of 30 pence per item per day |
| q16 | canary | hallucination | Can a patron request an extension for a loan if they have an outstanding fine th | answered instead of refusing |
| q17 | answerable | hallucination | How many more items can a postgraduate student borrow compared to an undergradua | missed 2 fact(s): postgraduate students may borrow 12 items |
| q20 | answerable | hallucination | How much does it cost to make two inter-library loan requests, considering the f | ungrounded claim; missed 1 fact(s): 2 requests per patron per month free of charge |

## How this was judged

- **L0 deterministic**: citation IDs validated against the index and retrieved context; refusals read from the output contract (schema field, not prose); numeric answers checked deterministically within 2% relative tolerance; retrieval telemetry recorded per case.
- **L1 micro-binary**: every expected fact checked against the answer as a single YES/NO entailment call, plus answer groundedness verified against cited chunks and tool outputs; coverage aggregated mechanically without holistic scoring or position/verbosity ranking bias.
- **Eval-set self-defense**: expected facts verified against their own grounding chunk at generation time; refusal/canary cases passed an answerability gate; near-duplicates dropped.

## Cost ledger

| stage | calls | in tokens | out tokens |
|---|---|---|---|
| agent_answer | 177 | 136156 | 12133 |
| eval_answerable | 15 | 9164 | 871 |
| eval_canary | 12 | 7640 | 962 |
| eval_edge | 8 | 4441 | 1042 |
| eval_fact_verify | 26 | 9508 | 52 |
| eval_refusal | 4 | 2478 | 281 |
| eval_refusal_gate | 6 | 3329 | 12 |
| eval_rephrase | 2 | 346 | 50 |
| groundability | 5 | 3728 | 498 |
| interview | 1 | 517 | 177 |
| judge_grounded | 126 | 53483 | 252 |
| judge_l1 | 127 | 31045 | 254 |
| judge_pair | 4 | 766 | 8 |
| judge_reframe | 65 | 25133 | 130 |
| prompt_candidate | 3 | 1613 | 426 |
| requirements | 2 | 1407 | 372 |
| tool_selection | 1 | 693 | 85 |

Total: 584 calls, 309052 tokens, 581s model time.

---

*A factory that claims 100% is suspicious; this one explains its 67%.*