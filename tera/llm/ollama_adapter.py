"""Ollama adapter (optional). Talks to a local Ollama server — no API key."""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .base import LLM, SYSTEM_PROMPT, _http_post_json, build_grounding_prompt

_EXTRACT_SYSTEM = (
    "You extract durable, general facts from text. Return ONLY a JSON array. "
    "Each item: {\"content\": str, \"subject\": str|null, \"predicate\": str|null, "
    "\"object\": str|null}. Ignore questions, greetings, commands and small talk. "
    "If there is nothing worth storing, return []."
)


class OllamaLLM(LLM):
    name = "ollama"

    def __init__(self, model: str = "llama3.1", host: Optional[str] = None):
        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def _chat(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.2},
        }
        data = _http_post_json(f"{self.host}/api/chat", payload, {"Content-Type": "application/json"})
        return (data.get("message", {}).get("content") or "").strip()

    def answer(
        self, question: str, facts: List[str], system: Optional[str] = None
    ) -> str:
        return self._chat(system or SYSTEM_PROMPT, build_grounding_prompt(question, facts))

    def extract(self, text: str) -> List[Dict[str, Optional[str]]]:
        try:
            raw = self._chat(_EXTRACT_SYSTEM, text)
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            items = json.loads(raw)
            return items if isinstance(items, list) else []
        except Exception:
            return []
