"""Ingestion: loaders + table-aware chunking. Malformed files quarantine, never crash."""
from .chunking import chunk_document
from .loaders import SUPPORTED, load

__all__ = ["chunk_document", "load", "SUPPORTED"]
