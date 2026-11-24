# Factory Report — Library Assistant

Produced by ForgeAI. Definition version 3, iteration 2.

## Requirements (as compiled by the factory)

| topic | status | density | evidence | note |
|---|---|---|---|---|
| Loan Periods and Limits | supported | 0.33 | d01#c000 | The chunk directly addresses the topic of 'Loan Periods and Limits' by specifying the number of items and duration for d |
| Renewals | supported | 0.50 | d01#c000 | Chunk d01#c000 contains information about the renewal process, which directly addresses the topic of renewals. It specif |
| Fines and Fees | supported | 0.50 | d01#c001 | The chunk directly addresses fines and fees, providing specific details such as the fine rates for overdue items and los |
| Holds and Recalls | supported | 1.00 | d01#c001 | The chunk discusses holds and recalls, directly addressing the topic. It explains that patrons can place holds on loaned |
| Inter-Library Loans | supported | 0.67 | d01#c001, d01#c002 | Both chunk d01#c001 and chunk d01#c002 contain relevant information about inter-library loans, including the number of r |

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
| answerable | 8 |
| canary | 3 |
| refusal | 4 |
| rephrase_a | 2 |
| rephrase_b | 2 |

## Optimization iterations

| iteration | score | patched class | change | Δ |
|---|---|---|---|---|
| iter 0 | 15/19 (79%) | hallucination | appended 'Refusal discipline' section: refuse when the SPECIFIC fact is absent, even if the topic is covered | 79% → 58% |
| iter 0 | 11/19 (58%) | — | post-patch re-eval (78s) | — |
| iter 1 | 11/19 (58%) | prompt_defect | appended 'Answer completeness' section: comparisons state both sides + difference; calculator mandatory for ar | 58% → 79% |
| iter 1 | 15/19 (79%) | — | post-patch re-eval (90s) | — |
| iter 2 | 14/19 (74%) | — | no patchable failure class remains (all already patched) | — |

### Prompt tournament (pilot subset)

| candidate | pilot score |
|---|---|
| candidate-1 | 100% |
| candidate-2 | 80% |
| candidate-3 | 80% |

## Final scorecard

| passed | total | score | 95% CI |
|---|---|---|---|
| 14 | 19 | 74% | [51%, 88%] |

## What still fails and why (5 cases)

| id | kind | class | question | telemetry |
|---|---|---|---|---|
| q03 | canary | hallucination | Can a borrower request an extension for a book from the Special Collections section if it  | cov=0.00 |
| q05 | canary | hallucination | How does the library handle requests for extended loan periods for items in the Special Co | cov=0.00 |
| q12 | refusal | hallucination | What is the process for extending the loan period for a rare book in the Special Collectio | cov=0.00 |
| q14 | refusal | hallucination | What is the procedure for requesting a special exhibition item from the library's collecti | cov=0.00 |
| q18 | answerable | hallucination | How many more items can a postgraduate student borrow compared to an undergraduate student | cov=0.00 |

## How this was judged

- **L0 deterministic**: citation IDs validated against the index; refusals read from the output contract (schema field, not prose); numeric answers recomputed by the calculator tool; retrieval telemetry recorded per case.
- **L1 micro-binary**: every expected fact checked against the answer as a single YES/NO entailment call; coverage aggregated mechanically. No holistic opinions, no position/verbosity bias surface.
- **Eval-set self-defense**: expected facts verified against their own grounding chunk at generation time; refusal/canary cases passed an answerability gate; near-duplicates dropped.

## Cost ledger

| stage | calls | in tokens | out tokens |
|---|---|---|---|

Total: 0 calls, 0 tokens, 0s model time.

---

*A factory that claims 100% is suspicious; this one explains its 74%.*