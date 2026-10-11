"""Offline, dependency-free 'LLM'.

This is not a language model — it is a deterministic answerer that composes a
reply purely from the facts the retriever hands it. It exists so Tera is fully
functional with zero setup, and so the knowledge-base layer can be tested and
demonstrated in isolation from any model.

Its honesty is the point: it says "I don't know" when the base is empty,
because that is exactly what a grounded assistant should do.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .base import LLM


class MockLLM(LLM):
    name = "mock"

    def answer(
        self, question: str, facts: List[str], system: Optional[str] = None
    ) -> str:
        if not facts:
            return (
                "I don't have anything in my knowledge base about that yet. "
                "Tell me about it and I'll remember it permanently."
            )
        if len(facts) == 1:
            return f"From what I've stored: {facts[0]}"
        body = "\n".join(f"  {i}. {f}" for i, f in enumerate(facts, 1))
        return f"Here is what I've stored that is relevant:\n{body}"

    def extract(self, text: str) -> List[Dict[str, Optional[str]]]:
        # Offline mode defers entirely to the rule-based curator.
        return []
