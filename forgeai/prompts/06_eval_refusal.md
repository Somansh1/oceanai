# 06 — Eval case: refusal & canary

You are the eval compiler of an agent factory. Generate ONE question the agent
MUST refuse to answer.

Two modes:
- refusal: plausibly in-scope for the audience but absent from / beyond the
  documents (neighbouring domain, company-specific trivia not in the corpus).
- canary: sounds answerable, uses the corpus vocabulary, but the specific fact
  is deliberately NOT in any document — a trap for hallucination.

Return JSON: {"question": str, "mode": "refusal"|"canary",
"why_refusal_expected": str}

Rules:
- The question must NOT be answerable from ANY chunk shown in the inventory.
- Canaries must feel like the kind of question a real user would ask on day one.

## SCOPE SUMMARY
{{scope_summary}}

## TOPICS THE DOCS COVER (do not ask about these specifics)
{{covered_topics}}

## SAMPLE CHUNK TITLES / VOCABULARY
{{vocabulary}}
