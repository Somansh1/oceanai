"""Core typed artifacts: documents, chunks, provenance, atomic claims.

Every object that flows through the factory is typed and knows where it came
from. This is what makes triage and auditing possible downstream.
"""
from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChunkKind(str, Enum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    ROW_GROUP = "row_group"
    SCHEMA_PROFILE = "schema_profile"  # column/dtype profile prepended to CSV indexes
    PAGE = "page"


class Provenance(BaseModel):
    """Where a chunk came from, down to character/page/row spans."""

    doc_id: str
    source_path: str
    loader: str
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    row_start: int | None = None
    row_end: int | None = None


class Chunk(BaseModel):
    id: str  # "<doc_id>#c<idx:03d>"
    text: str
    kind: ChunkKind
    provenance: Provenance
    model_used: str | None = None  # if the chunk content was model-derived

    def tokenish(self) -> int:
        """Rough token estimate for budget metering (~4 chars/token)."""
        return max(1, len(self.text) // 4)


class DocumentMeta(BaseModel):
    doc_id: str  # "d01", "d02", ...
    filename: str
    source_path: str
    sha256: str
    kind: Literal["pdf", "csv", "xlsx", "docx", "md", "txt", "quarantined"]
    n_chunks: int = 0
    notes: str | None = None


class QuarantineRecord(BaseModel):
    """A file that failed ingestion. The run continues; the report confesses."""

    source_path: str
    attempted_loader: str
    error: str
    quarantined_at: str


class Claim(BaseModel):
    """One atomic, checkable fact extracted from a chunk.

    Atomic claims are the currency of the whole factory: groundability maps are
    built from them, eval cases carry them as expected facts, and the judge
    scores answers by matching claims pairwise. Never prose paragraphs.
    """

    id: str  # "<chunk_id>#f<idx:02d>"
    chunk_id: str
    text: str
    verbatim: bool = False  # True when lifted directly from the chunk text
