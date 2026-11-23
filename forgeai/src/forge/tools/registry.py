"""Tool implementations + registry. Tools are pure functions with contracts."""
from __future__ import annotations

import ast
import operator
from datetime import date, datetime
from typing import Any, Callable

import requests


class Tool:
    def __init__(self, name: str, description: str, usage: str,
                 run: Callable[[dict[str, Any]], str]):
        self.name = name
        self.description = description
        self.usage = usage
        self.run = run


def _calculator(args: dict[str, Any]) -> str:
    expr = str(args.get("expression", "")).strip()
    if not expr:
        return "error: missing 'expression'"
    allowed = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.USub: operator.neg,
    }

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            return allowed[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
            return allowed[type(node.op)](ev(node.operand))
        raise ValueError("unsupported operation")

    try:
        result = ev(ast.parse(expr, mode="eval"))
        r = round(result, 6)
        return str(int(r)) if r == int(r) else str(r)
    except Exception as exc:
        return f"error: {exc}"


def _now(args: dict[str, Any]) -> str:
    return datetime.now().astimezone().strftime("%A, %Y-%m-%d (%z) ISO-week %V")


def _csv_lookup(args: dict[str, Any]) -> str:
    import csv as _csv
    from pathlib import Path

    path = Path(str(args.get("file", "")))
    if not path.exists():
        return f"error: file not found: {path}"
    column = str(args.get("column", ""))
    value = str(args.get("value", ""))
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
    except Exception as exc:
        return f"error: {exc}"
    if column and value:
        hits = [r for r in rows if str(r.get(column, "")).strip().lower() == value.lower()]
    else:
        hits = rows[: int(args.get("limit", 10))]
    if not hits:
        return f"no rows matched {column}={value} in {path.name}"
    return "\n".join(" | ".join(f"{k}={v}" for k, v in r.items()) for r in hits[:25])


def _open_meteo(args: dict[str, Any]) -> str:
    lat = args.get("latitude")
    lon = args.get("longitude")
    if lat is None or lon is None:
        return "error: missing latitude/longitude"
    marine = bool(args.get("marine", False))
    base = ("https://api.open-meteo.com/v1/forecast" if not marine
            else "https://marine-api.open-meteo.com/v1/forecast")
    params = {"latitude": lat, "longitude": lon, "current": "temperature_2m,wind_speed_10m",
              "timezone": "auto"}
    try:
        r = requests.get(base, params=params, timeout=10)
        r.raise_for_status()
        return str(r.json().get("current", r.json()))[:1500]
    except Exception as exc:
        return f"error (network or api): {exc}"


REGISTRY: dict[str, Tool] = {
    "csv_lookup": Tool(
        "csv_lookup",
        "Look up rows in a CSV data file by column=value match.",
        '{"tool": "csv_lookup", "args": {"file": "<path>", "column": "<name>", "value": "<match>"}}',
        _csv_lookup,
    ),
    "calculator": Tool(
        "calculator",
        "Evaluate an arithmetic expression exactly (never do math in your head).",
        '{"tool": "calculator", "args": {"expression": "e.g. 24*3+10"}}',
        _calculator,
    ),
    "now": Tool(
        "now",
        "Get the current local date and time.",
        '{"tool": "now", "args": {}}',
        _now,
    ),
    "open_meteo": Tool(
        "open_meteo",
        "Current weather at a location (keyless public API). marine=true for sea state.",
        '{"tool": "open_meteo", "args": {"latitude": 54.1, "longitude": 13.4, "marine": false}}',
        _open_meteo,
    ),
}

ToolName = str


def format_tools_for_prompt(names: list[str]) -> str:
    lines = []
    for n in names:
        t = REGISTRY.get(n)
        if t:
            lines.append(f"- {t.name}: {t.description}\n  call: {t.usage}")
    return "\n".join(lines) or "(no tools attached)"
