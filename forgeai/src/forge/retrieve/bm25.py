"""Hand-rolled BM25: zero dependencies, fully inspectable, corpus-scale honest.

At factory scale (hundreds of chunks) this is instant and deterministic.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "is", "are", "for", "on",
    "with", "as", "by", "at", "be", "it", "this", "that", "from", "was", "were",
    "what", "which", "who", "whom", "how", "when", "where", "why", "do", "does",
    "can", "could", "should", "would", "will", "shall", "may", "might", "i",
    "you", "we", "they", "he", "she", "my", "our", "your", "their",
}


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    toks = _TOKEN.findall(text.lower())
    if drop_stopwords:
        toks = [t for t in toks if t not in _STOPWORDS]
    return toks


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_ids: list[str] = []
        self.doc_tokens: list[list[str]] = []
        self.tf: list[Counter] = []
        self.df: Counter = Counter()
        self.avgdl: float = 0.0

    def build(self, doc_ids: list[str], texts: list[str]) -> None:
        self.doc_ids = list(doc_ids)
        self.doc_tokens = [tokenize(t) for t in texts]
        self.tf = [Counter(toks) for toks in self.doc_tokens]
        for counter in self.tf:
            for term in counter:
                self.df[term] += 1
        lens = [len(t) for t in self.doc_tokens]
        self.avgdl = (sum(lens) / len(lens)) if lens else 1.0

    def _idf(self, term: str) -> float:
        n = len(self.doc_ids)
        df = self.df.get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query: str) -> dict[str, float]:
        q_terms = tokenize(query)
        scores: dict[str, float] = {}
        for i, doc_id in enumerate(self.doc_ids):
            s = 0.0
            dl = len(self.doc_tokens[i])
            for term in q_terms:
                f = self.tf[i].get(term, 0)
                if not f:
                    continue
                idf = self._idf(term)
                s += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s > 0:
                scores[doc_id] = s
        return scores

    def query(self, query: str, top_k: int = 8) -> list[tuple[str, float]]:
        scores = self.score(query)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return ranked
