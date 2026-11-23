"""Tool registry: 4 tools. Selection discipline is a factory requirement —
the generator attaches ONLY what a brief needs and records rejections."""
from .registry import REGISTRY, Tool, ToolName, format_tools_for_prompt

__all__ = ["REGISTRY", "Tool", "ToolName", "format_tools_for_prompt"]
