"""Hybrid index: BM25 (always) + dense vectors (when embeddings are available).

Degrades honestly: no embedding backend -> sparse-only, and the run manifest
records the degraded mode. RRF fuses the two lists.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from ..core import Chunk, ChunkKind, Provenance
from .bm25 import BM25Index

RRF_K = 60


class HybridIndex:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._dense_ready = False
        self._try_load_vec()
        self._init_tables()
        self.bm25 = BM25Index()
        self._chunks: dict[str, Chunk] = {}
        self._reload_from_db()

    def _reload_from_db(self) -> None:
        """Rehydrate on open: BM25 + chunk cache must survive process boundaries."""
        rows = self.conn.execute("SELECT chunk_id, text, kind, meta FROM chunks").fetchall()
        if not rows:
            return
        for chunk_id, text, kind, meta in rows:
            prov = Provenance(**json.loads(meta))
            self._chunks[chunk_id] = Chunk(id=chunk_id, text=text,
                                           kind=ChunkKind(kind), provenance=prov)
        self.bm25.build([r[0] for r in rows], [r[1] for r in rows])
        if self._vec_ext:
            n = self.conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
            self._dense_ready = n > 0
        else:
            n = self.conn.execute("SELECT COUNT(*) FROM vec_fallback").fetchone()[0]
            self._dense_ready = n > 0

    def _try_load_vec(self) -> bool:
        try:
            import sqlite_vec
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            self._vec_ext = True
            return True
        except Exception:
            self._vec_ext = False
            return False

    def _init_tables(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT, text TEXT, kind TEXT, meta TEXT)"
        )
        if self._vec_ext:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(chunk_id TEXT PRIMARY KEY, embedding float[768])"
            )
        else:
            self.conn.execute("CREATE TABLE IF NOT EXISTS vec_fallback (chunk_id TEXT PRIMARY KEY, embedding TEXT)")
        self.conn.commit()

    # ------------------------------------------------------------------ build

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]] | None = None) -> None:
        for c in chunks:
            self._chunks[c.id] = c
            self.conn.execute(
                "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?)",
                (c.id, c.provenance.doc_id, c.text, c.kind.value,
                 json.dumps(c.provenance.model_dump())),
            )
        if embeddings is not None and len(embeddings) == len(chunks):
            dim = len(embeddings[0])
            if self._vec_ext:
                self.conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING "
                    f"vec0(chunk_id TEXT PRIMARY KEY, embedding float[{dim}])"
                )
                for c, e in zip(chunks, embeddings):
                    # vec0 does not honor INSERT OR REPLACE — delete first
                    self.conn.execute("DELETE FROM vec_chunks WHERE chunk_id = ?", (c.id,))
                    self.conn.execute(
                        "INSERT INTO vec_chunks VALUES (?, ?)",
                        (c.id, np.asarray(e, dtype=np.float32).tobytes()),
                    )
            else:
                for c, e in zip(chunks, embeddings):
                    self.conn.execute(
                        "INSERT OR REPLACE INTO vec_fallback VALUES (?, ?)",
                        (c.id, json.dumps(e)),
                    )
            self._dense_ready = True
        self.conn.commit()
        rows = self.conn.execute("SELECT chunk_id, text FROM chunks").fetchall()
        self.bm25.build([r[0] for r in rows], [r[1] for r in rows])

    # ------------------------------------------------------------------ query

    def _dense_query(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        if self._vec_ext:
            rows = self.conn.execute(
                "SELECT chunk_id, distance FROM vec_chunks WHERE embedding MATCH ? "
                "AND k = ? ORDER BY distance",
                (np.asarray(vector, dtype=np.float32).tobytes(), top_k),
            ).fetchall()
            return [(cid, 1.0 / (1.0 + d)) for cid, d in rows]
        rows = self.conn.execute("SELECT chunk_id, embedding FROM vec_fallback").fetchall()
        if not rows:
            return []
        q = np.asarray(vector, dtype=np.float32)
        q = q / (np.linalg.norm(q) + 1e-9)
        scored: list[tuple[str, float]] = []
        for cid, blob in rows:
            v = np.asarray(json.loads(blob), dtype=np.float32)
            v = v / (np.linalg.norm(v) + 1e-9)
            scored.append((cid, float(np.dot(q, v))))
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:top_k]

    def query(self, text: str, vector: list[float] | None = None, top_k: int = 6,
              dense_k: int = 5, sparse_k: int = 8, rrf_k: int = RRF_K,
              hybrid: bool = True, min_score: float = 0.0) -> list[tuple[str, float]]:
        """RRF fusion of sparse (+ dense when available). Returns [(chunk_id, rrf)]."""
        lists: list[list[str]] = []
        sparse = [cid for cid, _ in self.bm25.query(text, top_k=sparse_k)]
        if sparse:
            lists.append(sparse)
        if hybrid and vector is not None and self._dense_ready:
            lists.append([cid for cid, _ in self._dense_query(vector, dense_k)])
        fused: dict[str, float] = {}
        for ranked in lists:
            for rank, cid in enumerate(ranked):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
        items = [(cid, score) for cid, score in fused.items() if score >= min_score]
        return sorted(items, key=lambda kv: kv[1], reverse=True)[:top_k]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self._chunks.get(chunk_id)

    def all_chunk_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT chunk_id FROM chunks").fetchall()]

    def close(self) -> None:
        self.conn.close()
