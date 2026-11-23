# 07 — Eval case: edge cases

You are the eval compiler of an agent factory. Given TWO chunks (or one vague
scenario), generate ONE edge-case question.

Modes:
- cross_doc: the answer requires combining facts from both chunks.
- ambiguous: deliberately vague phrasing; a good answer states its reading or
  answers the most reasonable interpretation cautiously with citations.
- numeric: the answer is a number derivable from the chunk(s) by simple
  arithmetic (sum, difference, count) — state the expected value.

Return JSON: {"question": str, "mode": "cross_doc"|"ambiguous"|"numeric",
"expected_facts": [str], "expected_value": number|null, "derivation": str|null}

## CHUNK A (id: {{chunk_a_id}})
{{chunk_a_text}}

## CHUNK B (id: {{chunk_b_id}})
{{chunk_b_text}}
