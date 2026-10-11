"""Tera Search — a self-contained web search engine.

It crawls from seed pages, builds its own inverted index, and answers queries
from that index. Nothing here calls Google, DuckDuckGo, Bing or any other
search API — the only network traffic is our own crawler fetching pages.

Honest scope: a search engine can only answer from what it has crawled. This
one covers the seeds you give it (and, optionally, links it finds from them).
Point it at more pages to widen its world.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from typing import Dict, List, Optional

from ..kb.text import tokenize
from .crawler import extract, fetch
from .index import InvertedIndex


def _domain(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


class WebSearch:
    def __init__(self, path: Optional[str] = "web_index.json"):
        self.path = path
        self.index = InvertedIndex()
        self.crawled: List[str] = []
        if path and os.path.exists(path):
            self.load()

    # ------------------------------------------------------------------ #
    # crawling
    # ------------------------------------------------------------------ #
    def crawl(
        self,
        seeds: List[str],
        depth: int = 1,
        max_pages: int = 40,
        same_domain: bool = True,
        delay: float = 0.0,
        timeout: int = 15,
        max_text_chars: int = 20000,
    ) -> int:
        """Breadth-first crawl. Returns how many pages are in the index."""
        allowed = {_domain(s) for s in seeds}
        queue = [(s, 0) for s in seeds]
        queued = set(seeds)

        while queue and len(self.index.docs) < max_pages:
            url, level = queue.pop(0)
            if url in self.crawled:
                continue
            self.crawled.append(url)

            try:
                html = fetch(url, timeout=timeout)
            except Exception:
                continue
            if not html:
                continue

            page = extract(html, url)
            if not page["text"]:
                continue
            if max_text_chars and len(page["text"]) > max_text_chars:
                page["text"] = page["text"][:max_text_chars]

            title = page["title"] or url
            self.index.add(
                doc_id=url,
                url=url,
                title=title,
                text=page["text"],
                tokens=tokenize(page["text"]),
                title_tokens=tokenize(title),
            )

            if delay:
                time.sleep(delay)

            if level < depth:
                for link in page["links"]:
                    if link in queued:
                        continue
                    if same_domain and _domain(link) not in allowed:
                        continue
                    if link.split("#")[0].endswith((".png", ".jpg", ".jpeg", ".gif",
                                                    ".svg", ".pdf", ".zip", ".css", ".js")):
                        continue
                    queued.add(link)
                    queue.append((link, level + 1))

        return self.index.n_docs

    # ------------------------------------------------------------------ #
    # searching
    # ------------------------------------------------------------------ #
    def search(self, query: str, k: int = 5, min_score: float = 0.0) -> List[dict]:
        results = self.index.search(tokenize(query), k=k * 2)
        results = [r for r in results if r["score"] >= min_score]
        for r in results:
            r["snippet"] = self._snippet(r.get("text", ""), query)
        return results[:k]

    @staticmethod
    def _snippet(text: str, query: str, width: int = 260) -> str:
        """Pick the sentence that best covers the query.

        Naive "first occurrence" grabs page furniture (navigation, language
        lists). Choosing the sentence containing the most query words gives a
        far more useful answer.
        """
        terms = [w for w in tokenize(query) if len(w) > 2]
        if not terms:
            return text[:width].strip() + ("…" if len(text) > width else "")

        best, best_key = None, (0, 0.0)
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            sentence = sentence.strip()
            if len(sentence) < 25:
                continue
            low = sentence.lower()
            count = sum(1 for t in terms if t in low)
            if not count:
                continue
            # Prefer the most query words; break ties by density, so a long
            # navigation/list blob loses to a real sentence mentioning the term.
            key = (count, count / max(1, len(sentence)))
            if key > best_key:
                best, best_key = sentence, key

        if best is None:
            best = text[:width].strip()
        return best[:width] + ("…" if len(best) > width else "")

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #
    def save(self, path: Optional[str] = None) -> str:
        target = path or self.path
        if not target:
            raise ValueError("no path to save the index to")
        payload = {"crawled": self.crawled, "index": self.index.to_dict()}
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return target

    def load(self, path: Optional[str] = None) -> "WebSearch":
        target = path or self.path
        with open(target, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self.index = InvertedIndex.from_dict(payload.get("index", {}))
        self.crawled = payload.get("crawled", [])
        return self

    def stats(self) -> Dict[str, int]:
        return {
            "pages": self.index.n_docs,
            "terms": len(self.index.postings),
            "avg_length": int(self.index.avg_len),
        }
