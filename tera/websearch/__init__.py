"""Tera Search — a self-contained crawler + inverted index + BM25 ranker.

No third-party search API is used; the engine fetches and indexes pages itself.
"""

from .engine import WebSearch
from .index import InvertedIndex
from .crawler import fetch, extract

__all__ = ["WebSearch", "InvertedIndex", "fetch", "extract"]
