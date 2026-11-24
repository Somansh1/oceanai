"""Unit tests for BM25 keyword retrieval engine."""
from __future__ import annotations

from forge.retrieve.bm25 import BM25Index


def test_bm25_ranking():
    doc_ids = ["d01#c000", "d01#c001", "d02#c000"]
    texts = [
        "Employees receive 24 days annual paid vacation and leave.",
        "Sick leave requires a medical certificate from a doctor after three consecutive days.",
        "Port marine bunker prices for VLSFO and MGO fuel grades updated daily.",
    ]
    index = BM25Index()
    index.build(doc_ids, texts)

    # Search for sick leave
    hits = index.query("medical certificate doctor sick", top_k=2)
    assert len(hits) > 0
    assert hits[0][0] == "d01#c001"

    # Search for bunker prices
    bunker_hits = index.query("fuel bunker prices", top_k=1)
    assert len(bunker_hits) == 1
    assert bunker_hits[0][0] == "d02#c000"


def test_bm25_empty_query():
    index = BM25Index()
    index.build(["d01#c000"], ["Sample text"])
    assert index.query("", top_k=5) == []
