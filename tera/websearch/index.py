"""An inverted index with BM25 ranking — the heart of the search engine.

This is the classic design every search engine uses, in miniature: a map from
each word to the documents that contain it, plus a scoring function that
rewards rare words, frequent occurrences and short documents.
"""

from __future__ import annotations

import math
from typing import Dict, List

K1 = 1.2   # term-frequency saturation
B = 0.75   # length normalisation
TITLE_BOOST = 2.0


class InvertedIndex:
    def __init__(self):
        self.docs: Dict[str, dict] = {}          # doc_id -> {url,title,text,title_tokens}
        self.postings: Dict[str, Dict[str, int]] = {}  # token -> {doc_id: tf}
        self.lengths: Dict[str, int] = {}        # doc_id -> token count

    # ------------------------------------------------------------------ #
    def add(self, doc_id: str, url: str, title: str, text: str, tokens: List[str],
            title_tokens: List[str] = None) -> None:
        if doc_id in self.docs:
            self.remove(doc_id)
        self.docs[doc_id] = {
            "url": url,
            "title": title,
            "text": text,
            "title_tokens": list(dict.fromkeys(title_tokens or [])),
        }
        self.lengths[doc_id] = max(1, len(tokens))
        counts: Dict[str, int] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        for t, tf in counts.items():
            self.postings.setdefault(t, {})[doc_id] = tf

    def remove(self, doc_id: str) -> None:
        for t in list(self.postings):
            if doc_id in self.postings[t]:
                del self.postings[t][doc_id]
                if not self.postings[t]:
                    del self.postings[t]
        self.docs.pop(doc_id, None)
        self.lengths.pop(doc_id, None)

    # ------------------------------------------------------------------ #
    @property
    def n_docs(self) -> int:
        return len(self.docs)

    @property
    def avg_len(self) -> float:
        if not self.lengths:
            return 1.0
        return sum(self.lengths.values()) / len(self.lengths)

    def search(self, query_tokens: List[str], k: int = 5) -> List[dict]:
        if not query_tokens:
            return []
        n = max(1, self.n_docs)
        avgdl = self.avg_len or 1.0
        scores: Dict[str, float] = {}

        for term in dict.fromkeys(query_tokens):
            postings = self.postings.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
            for doc_id, tf in postings.items():
                dl = self.lengths.get(doc_id, 1)
                denom = tf + K1 * (1 - B + B * dl / avgdl)
                score = idf * (tf * (K1 + 1)) / denom
                if term in set(self.docs.get(doc_id, {}).get("title_tokens", [])):
                    score *= TITLE_BOOST
                scores[doc_id] = scores.get(doc_id, 0.0) + score

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        out = []
        for doc_id, score in ranked:
            doc = self.docs[doc_id]
            out.append({
                "doc_id": doc_id,
                "url": doc["url"],
                "title": doc["title"],
                "text": doc["text"],
                "score": round(score, 4),
            })
        return out

    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {"docs": self.docs, "postings": self.postings, "lengths": self.lengths}

    @classmethod
    def from_dict(cls, data: dict) -> "InvertedIndex":
        idx = cls()
        idx.docs = data.get("docs", {})
        idx.postings = data.get("postings", {})
        idx.lengths = data.get("lengths", {})
        return idx
