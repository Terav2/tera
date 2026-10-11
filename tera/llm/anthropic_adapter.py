"""Anthropic Claude adapter (optional). Needs ANTHROPIC_API_KEY."""

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


class AnthropicLLM(LLM):
    name = "anthropic"

    def __init__(self, model: str = "claude-haiku-4-5-20251001", api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def available(self) -> bool:
        return bool(self.api_key)

    def _chat(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        data = _http_post_json("https://api.anthropic.com/v1/messages", payload, headers)
        parts = data.get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()

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
