"""LLM factory. Picks a backend by name and falls back to offline mode safely."""

from __future__ import annotations

from typing import Optional

from .base import LLM
from .mock import MockLLM


def build_llm(backend: str = "mock", model: Optional[str] = None) -> LLM:
    """Return an LLM for the given backend name.

    If a real backend is requested but is not usable (missing key / server),
    Tera still works: we fall back to the offline MockLLM so the knowledge
    base keeps functioning. The engine records the fallback.
    """
    backend = (backend or "mock").lower().strip()

    if backend in ("mock", "offline", "none", ""):
        return MockLLM()

    try:
        if backend == "openai":
            from .openai_adapter import OpenAILLM
            llm = OpenAILLM(model=model) if model else OpenAILLM()
        elif backend == "anthropic":
            from .anthropic_adapter import AnthropicLLM
            llm = AnthropicLLM(model=model) if model else AnthropicLLM()
        elif backend == "ollama":
            from .ollama_adapter import OllamaLLM
            llm = OllamaLLM(model=model) if model else OllamaLLM()
        else:
            return MockLLM()
    except Exception:
        return MockLLM()

    if not llm.available():
        return MockLLM()
    return llm


__all__ = ["LLM", "MockLLM", "build_llm"]
