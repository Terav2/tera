"""OpenAI adapter (optional). Needs OPENAI_API_KEY in the environment."""

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


class OpenAILLM(LLM):
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def available(self) -> bool:
        return bool(self.api_key)

    def _chat(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = _http_post_json(
            "https://api.openai.com/v1/chat/completions", payload, headers
        )
        return data["choices"][0]["message"]["content"].strip()

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
