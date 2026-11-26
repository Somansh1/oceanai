"""Unit tests for tool hinting, ToolDecision sanitization, and retrieval config derivation."""
from __future__ import annotations

from forge.core import Chunk, ChunkKind, DocumentMeta, Provenance
from forge.generate.generator import ToolDecision, _hinted_tools, derive_retrieval_config
from forge.llm import Harness


def test_hinted_tools_ignores_substring_northwind():
    hr_brief = (
        "I need an assistant that answers HR policy questions for shore staff at Northwind Maritime. "
        "It should cover annual leave, sick leave, and parental leave, and refuse salary or crewing."
    )
    hints = _hinted_tools(hr_brief, data_files=[])
    assert "open_meteo" not in hints
    assert "calculator" not in hints
    assert "now" not in hints
    assert "csv_lookup" not in hints


def test_hinted_tools_matches_portops_brief():
    portops_brief = (
        "Answer vessel turnaround questions: when the next vessel arrives at a berth, "
        "what berth costs and demurrage are with exact arithmetic, relative dates, "
        "and check current sea conditions at the port."
    )
    hints = _hinted_tools(portops_brief, data_files=["berth_schedule.csv"])
    assert set(hints.keys()) == {"calculator", "open_meteo", "now", "csv_lookup"}


def test_tool_decision_sanitize_deduplicates_selected_and_rejected():
    d = ToolDecision(
        selected=[
            {"name": "csv_lookup", "justification": "CSV files", "invoked_when": "lookup"},
            {"name": "unknown_tool", "justification": "bogus", "invoked_when": "never"},
            {"name": "csv_lookup", "justification": "dup", "invoked_when": "lookup"},
        ],
        rejected=[
            {"name": "csv_lookup", "reason": "contradictory rejection"},
            {"name": "now", "reason": "not needed"},
        ],
    )
    d.sanitize(Harness())
    sel_names = [t["name"] for t in d.selected]
    rej_names = [r["name"] for r in d.rejected]
    assert sel_names == ["csv_lookup"]
    assert "csv_lookup" not in rej_names
    assert set(rej_names) == {"calculator", "now", "open_meteo"}


def test_derive_retrieval_config_adapts_to_corpus():
    small_chunks = [
        Chunk(
            id=f"d01#c{i:03d}",
            text="sample",
            kind=ChunkKind.PARAGRAPH,
            provenance=Provenance(doc_id="d01", source_path="a.md", loader="md"),
        )
        for i in range(3)
    ]
    small_metas = [DocumentMeta(doc_id="d01", filename="a.md", source_path="a.md", sha256="x", kind="md", n_chunks=3)]
    cfg_small = derive_retrieval_config(small_chunks, small_metas, chunk_size=900, overlap=150, dense_ready=False)
    assert cfg_small.hybrid is False
    assert cfg_small.top_k_dense == 3
    assert cfg_small.top_k_sparse == 3

    large_chunks = [
        Chunk(
            id=f"d01#c{i:03d}",
            text="sample",
            kind=ChunkKind.PARAGRAPH,
            provenance=Provenance(doc_id="d01", source_path="a.csv", loader="csv"),
        )
        for i in range(30)
    ]
    large_metas = [DocumentMeta(doc_id="d01", filename="a.csv", source_path="a.csv", sha256="y", kind="csv", n_chunks=30)]
    cfg_large = derive_retrieval_config(large_chunks, large_metas, chunk_size=900, overlap=150, dense_ready=True)
    assert cfg_large.hybrid is True
    assert cfg_large.top_k_dense == 7
    assert cfg_large.top_k_sparse == 10
