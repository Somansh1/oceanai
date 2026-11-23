"""Critic–optimizer: triage failures, apply surgical patches, log everything."""
from .optimizer import optimize
from .patches import PATCH_LIBRARY

__all__ = ["optimize", "PATCH_LIBRARY"]
