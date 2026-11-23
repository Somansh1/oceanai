"""Chunking: paragraph-aware merging, whole-table chunks, CSV row-groups.

Rules that matter downstream:
- Tables are NEVER split. Headers repeat in every row-group chunk.
- CSVs get a schema-profile chunk first so retrieval can find the table
  structurally, not just lexically.
- Paragraph chunks carry char spans for provenance.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core import Chunk, ChunkKind, DocumentMeta, Provenance
from .loaders import LoadedDoc, load

_SENT = re.compile(r"(?<=[.!?])\s+")


def _merge_paragraphs(paras: list[tuple[str, int | None]], doc_id: str, source: str,
                      loader: str, chunk_size: int, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    page = None
    start_idx = 0

    def flush(end_idx: int) -> None:
        nonlocal buf, buf_len, start_idx
        if not buf:
            return
        text = "\n\n".join(buf).strip()
        if text:
            idx = len(chunks)
            chunks.append(Chunk(
                id=f"{doc_id}#c{idx:03d}", text=text, kind=ChunkKind.PARAGRAPH,
                provenance=Provenance(doc_id=doc_id, source_path=source, loader=loader,
                                      page=page, char_start=start_idx, char_end=end_idx),
            ))
        buf, buf_len = [], 0

    for i, (text, p) in enumerate(paras):
        if buf and buf_len + len(text) > chunk_size:
            flush(i)
            prev = chunks[-1].text if chunks else ""
            tail_sents = _SENT.split(prev)
            tail = ""
            for s in reversed(tail_sents):
                if len(tail) + len(s) <= overlap:
                    tail = (s + " " + tail).strip()
                else:
                    break
            if tail:
                buf, buf_len = [tail], len(tail)
            start_idx = i
        if not buf:
            page = p
        buf.append(text)
        buf_len += len(text)
    flush(len(paras))
    return chunks


def _chunks_from_dataframe(doc: LoadedDoc, doc_id: str, source: str, loader: str,
                           rows_per_group: int = 12) -> list[Chunk]:
    df = doc.dataframe
    chunks: list[Chunk] = []
    columns = [str(c) for c in df.columns]
    profile = (
        f"[schema profile of {Path(source).name}]\n"
        f"columns: {', '.join(columns)}\n"
        f"rows: {len(df)}\n"
        f"sample:\n{df.head(3).to_csv(index=False)}"
    )
    chunks.append(Chunk(
        id=f"{doc_id}#c{len(chunks):03d}", text=profile, kind=ChunkKind.SCHEMA_PROFILE,
        provenance=Provenance(doc_id=doc_id, source_path=source, loader=loader,
                              row_start=0, row_end=min(3, len(df))),
    ))
    header_csv = ",".join(columns)
    for start in range(0, max(1, len(df)), rows_per_group):
        end = min(start + rows_per_group, len(df))
        body = df.iloc[start:end].to_csv(index=False)
        chunks.append(Chunk(
            id=f"{doc_id}#c{len(chunks):03d}",
            text=f"[rows {start + 2}-{end + 1} of {Path(source).name}]\n{header_csv}\n{body}",
            kind=ChunkKind.ROW_GROUP,
            provenance=Provenance(doc_id=doc_id, source_path=source, loader=loader,
                                  row_start=start, row_end=end),
        ))
    return chunks


def _file_sha(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def chunk_document(path: Path, doc_id: str, chunk_size: int = 900, overlap: int = 150
                   ) -> tuple[list[Chunk], DocumentMeta]:
    doc = load(path)
    chunks: list[Chunk]
    if doc.dataframe is not None:
        chunks = _chunks_from_dataframe(doc, doc_id, str(path), doc.kind)
    else:
        paras = [(p.text, p.page) for p in doc.paragraphs]
        chunks = _merge_paragraphs(paras, doc_id, str(path), doc.kind, chunk_size, overlap)
        for t in doc.tables:
            chunks.append(Chunk(
                id=f"{doc_id}#c{len(chunks):03d}", text=t.to_markdown(), kind=ChunkKind.TABLE,
                provenance=Provenance(doc_id=doc_id, source_path=str(path), loader=doc.kind, page=t.page),
            ))
    meta = DocumentMeta(
        doc_id=doc_id, filename=path.name, source_path=str(path),
        sha256=_file_sha(path), kind=doc.kind, n_chunks=len(chunks),
        notes=(f"{len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables"
               if doc.dataframe is None else "dataframe"),
    )
    return chunks, meta
