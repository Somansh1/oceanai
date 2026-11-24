"""Unit tests for tool registry and implementations."""
from __future__ import annotations

import tempfile
from pathlib import Path

from forge.tools.registry import REGISTRY


def test_tool_registry_contains_core_tools():
    assert "calculator" in REGISTRY
    assert "now" in REGISTRY
    assert "csv_lookup" in REGISTRY
    assert "open_meteo" in REGISTRY


def test_calculator_valid_expressions():
    calc = REGISTRY["calculator"]
    assert calc.run({"expression": "2 + 2"}) == "4"
    assert calc.run({"expression": "100 * (45 - 20) / 5"}) == "500"
    assert calc.run({"expression": "2 ** 8"}) == "256"
    assert calc.run({"expression": "15.5 + 4.5"}) == "20"


def test_calculator_invalid_or_malicious_expressions():
    calc = REGISTRY["calculator"]
    # Empty
    assert "error" in calc.run({})
    # Syntax error
    assert "error" in calc.run({"expression": "2 + "})
    # Security: disallowed operations or function calls
    assert "error" in calc.run({"expression": "__import__('os').system('dir')"})


def test_now_tool():
    now_tool = REGISTRY["now"]
    res = now_tool.run({})
    assert "202" in res
    assert "ISO-week" in res


def test_csv_lookup_tool():
    csv_tool = REGISTRY["csv_lookup"]
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write("vessel,berth,status\nOceanVoyager,B01,berthed\nSeaStar,B02,anchored\n")
        temp_path = Path(f.name)

    try:
        # Match vessel
        out = csv_tool.run({"file": str(temp_path), "column": "vessel", "value": "OceanVoyager"})
        assert "OceanVoyager" in out
        assert "B01" in out

        # Non-existent file
        err = csv_tool.run({"file": "does_not_exist.csv"})
        assert "error: file not found" in err
    finally:
        if temp_path.exists():
            temp_path.unlink()
