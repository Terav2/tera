"""Retrieval over the inverted index.

Scoring is BM25-style on the lexical match, then blended with the knowledge
base's own signals: how confident we are in a fact, how many times it has been
reinforced, and how recent it is. That blend is what makes a *curated* base
retrieve better than a pile of raw text — a fact confirmed five times outranks
one mentioned once.
"""

from __future__ import annotations

import math
from typing import Dict, List

from .models import Fact
from .text import normalize, tokenize


class Retriever:
    def __init__(self, store, config):
        self.store = store
        self.cfg = config

    def retrieve(self, question: str, top_k: int = None) -> List[Dict]:
        top_k = top_k or self.cfg.top_k
        q_tokens = tokenize(question)
        if not q_tokens:
            return []

        postings = self.store.postings_for(q_tokens)
        N = max(1, self.store.active_count())
        df = {p["token"]: p.get("df", len(p.get("ids", []))) for p in postings}

        candidate_ids = set()
        for p in postings:
            candidate_ids.update(p.get("ids", []))

        if not candidate_ids:
            return self._fallback(question, top_k)

        docs = [
            d for d in self.store.get_many(list(candidate_ids))
            if d.get("status") == "active"
        ]

        results = []
        for d in docs:
            dtokens = set(d.get("tokens", []))
            lexical = 0.0
            for t in set(q_tokens):
                if t in dtokens:
                    idf = math.log(1 + (N - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
                    lexical += idf
            conf = float(d.get("confidence", 0.6))
            reinf = min(int(d.get("reinforcements", 0)), 5) / 5.0
            final = lexical + 0.5 * conf + 0.3 * reinf
            results.append({
                "fact": self.store._to_fact(d),
                "score": round(final, 4),
                "lexical": round(lexical, 4),
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def _fallback(self, question: str, top_k: int) -> List[Dict]:
        """Linear substring scan when no index tokens match (e.g. typos)."""
        q = normalize(question)
        q_words = [w for w in q.split() if len(w) > 3]
        if not q_words:
            return []
        hits = []
        for fact in self.store.all_active(limit=2000):
            content = normalize(fact.content)
            overlap = sum(1 for w in q_words if w in content)
            if overlap:
                hits.append({
                    "fact": fact,
                    "score": float(overlap),
                    "lexical": float(overlap),
                })
        hits.sort(key=lambda r: r["score"], reverse=True)
        return hits[:top_k]
