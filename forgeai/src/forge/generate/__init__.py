"""Agent generation: system prompt candidates + tournament, retrieval config, tool selection with explicit rejections."""
from .generator import (
    derive_retrieval_config,
    generate_agent,
    generate_prompt_candidates,
    tournament,
)

__all__ = [
    "derive_retrieval_config",
    "generate_agent",
    "generate_prompt_candidates",
    "tournament",
]
