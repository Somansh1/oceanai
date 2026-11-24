"""Unit tests for document ingest and text chunking."""
from __future__ import annotations

import tempfile
from pathlib import Path

from forge.ingest.chunking import chunk_document


def test_chunk_document_small():
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("# Policy Document\n\nEmployees receive 24 days annual paid leave.\n")
        temp_path = Path(f.name)

    try:
        chunks, meta = chunk_document(temp_path, "d01", chunk_size=500, overlap=50)
        assert len(chunks) >= 1
        assert chunks[0].id == "d01#c000"
        assert meta.doc_id == "d01"
        assert meta.n_chunks == len(chunks)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_chunk_document_with_overlap():
    long_text = ("## General Regulations\n\n" + "Section A specifies duty hours and rest periods. " * 25 +
                 "\n\n" + "Section B specifies overtime and holiday allowances. " * 25)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(long_text)
        temp_path = Path(f.name)

    try:
        chunks, meta = chunk_document(temp_path, "d02", chunk_size=400, overlap=100)
        assert len(chunks) > 1
        for i, c in enumerate(chunks):
            assert c.id == f"d02#c{i:03d}"
            assert len(c.text) > 0
    finally:
        if temp_path.exists():
            temp_path.unlink()
