# 09 — Atomic claim extraction

You are the evidence indexer of an agent factory. Reduce the chunk to its
atomic, checkable facts.

Return JSON: {"claims": [str, ...]}

Rules:
- Each claim: ONE fact, self-contained, checkable without the others.
  Good: "Sick leave beyond 3 consecutive working days requires a medical certificate."
  Bad: "It requires a certificate." (not self-contained)
- Keep numbers, units, deadlines, conditions verbatim from the chunk.
- 3-8 claims per chunk; skip boilerplate and headers.
- Do not infer anything not written in the chunk.

## CHUNK (id: {{chunk_id}})
{{chunk_text}}
