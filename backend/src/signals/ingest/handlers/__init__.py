"""Importing this package registers every form handler with the dispatch registry."""

from signals.ingest.handlers import funds, insider

__all__ = ["funds", "insider"]
