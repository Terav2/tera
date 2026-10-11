"""Text utilities: normalisation, hashing, tokenisation.

Shared by the store (inverted index) and the retriever. Kept dependency-free
and deliberately simple — a light stemmer plus a stopword list is enough for a
knowledge base whose facts are short, declarative sentences.
"""

from __future__ import annotations

import hashlib
import re

_WORD_RE = re.compile(r"[a-zA-Z0-9']+")

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "am", "do", "does", "did", "of", "in", "on", "at", "to", "for", "with",
    "and", "or", "but", "if", "then", "than", "that", "this", "these",
    "those", "it", "its", "as", "by", "from", "into", "about", "over",
    "after", "before", "so", "such", "no", "not", "only", "own", "same",
    "too", "very", "can", "will", "just", "also", "i", "you", "he", "she",
    "we", "they", "them", "his", "her", "their", "our", "your", "my",
    "me", "us", "him",
    # question words and politeness — low information for matching
    "what", "who", "whom", "whose", "which", "when", "where", "why", "how",
    "please", "tell", "know", "kindly", "hey", "hi", "hello", "thanks",
}


def normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation — for de-duplication."""
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s]", "", t)
    return t


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:32]


def _stem(word: str) -> str:
    """Crude singulariser — good enough for matching 'planets' to 'planet'."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es") and not word.endswith("ses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    """Return indexable tokens: lowercased, stemmed, stopwords removed."""
    words = _WORD_RE.findall((text or "").lower())
    out = []
    seen = set()
    for w in words:
        if len(w) < 2:
            continue
        if not keep_stopwords and w in STOPWORDS:
            continue
        w = _stem(w)
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out
