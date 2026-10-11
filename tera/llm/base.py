"""The pluggable LLM interface.

Tera only ever needs two things from a model:
  * answer(question, facts)  -> a natural-language answer grounded in facts
  * extract(text)            -> optional structured fact extraction

`extract` is optional: the rule-based curator does the core work, and a real
model can improve on it when available. Keeping this surface tiny is what
makes the LLM genuinely swappable — and skippable.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class LLM(ABC):
    name: str = "base"

    @abstractmethod
    def answer(
        self, question: str, facts: List[str], system: Optional[str] = None
    ) -> str:
        """Produce an answer grounded in `facts` (already retrieved from the KB)."""

    def extract(self, text: str) -> List[Dict[str, Optional[str]]]:
        """Return candidate facts as dicts with keys content/subject/predicate/object.

        Default: no opinion — the rule-based curator handles it.
        """
        return []

    def available(self) -> bool:
        return True


def _http_post_json(url: str, payload: dict, headers: dict, timeout: int = 60) -> dict:
    """Minimal JSON POST using only the standard library (no dependencies)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"LLM HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise RuntimeError(f"LLM connection failed: {exc.reason}") from exc


def build_grounding_prompt(question: str, facts: List[str]) -> str:
    """The single prompt shape every real adapter uses."""
    if facts:
        fact_block = "\n".join(f"- {f}" for f in facts)
    else:
        fact_block = "(none)"
    return (
        "Known facts from the knowledge base:\n"
        f"{fact_block}\n\n"
        f"Question: {question}\n\n"
        "Answer using ONLY the known facts above. If they do not contain the "
        "answer, say plainly that you do not know yet. Do not invent details."
    )


SYSTEM_PROMPT = (
    "You are Tera, an assistant whose knowledge comes entirely from a curated, "
    "permanent knowledge base. You are honest about gaps, you never fabricate, "
    "and you prefer the stored facts over your own memory."
)
