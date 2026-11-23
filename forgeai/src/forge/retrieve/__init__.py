"""Retrieval: BM25 + dense hybrid with RRF fusion. Honest degradation, no servers."""
from .bm25 import BM25Index, tokenize
from .store import HybridIndex

__all__ = ["BM25Index", "HybridIndex", "tokenize"]
