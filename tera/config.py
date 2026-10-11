"""Configuration for Tera. Everything has a sane default so it runs with zero setup."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class TeraConfig:
    """Runtime configuration.

    All values fall back to environment variables, then to defaults that
    require no external services and no installation.
    """

    # --- Storage ---------------------------------------------------------
    # A document database (Mongita) that runs embedded in-process: no server,
    # no daemon, no setup. `db_path` is a folder the base lives in, or
    # ":memory:" for a throwaway base (handy for tests).
    # On serverless platforms (Vercel) the filesystem is ephemeral and only
    # /tmp is writable, so default there — the base won't persist, which is a
    # limitation of the host, not the app.
    db_path: str = field(
        default_factory=lambda: os.environ.get(
            "TERA_DB",
            "/tmp/tera_knowledge" if os.environ.get("VERCEL") else "tera_knowledge",
        )
    )

    # --- LLM (optional) --------------------------------------------------
    # "mock"     -> offline, rule-based, needs nothing (default).
    # "openai"   -> needs OPENAI_API_KEY.
    # "anthropic"-> needs ANTHROPIC_API_KEY.
    # "ollama"   -> needs a local Ollama server.
    llm_backend: str = field(
        default_factory=lambda: os.environ.get("TERA_LLM", "mock")
    )
    llm_model: str = field(
        default_factory=lambda: os.environ.get("TERA_LLM_MODEL", "")
    )

    # --- Curator (what gets stored) -------------------------------------
    # Store the user's own stated preferences/profile ("I prefer dark mode").
    store_user_preferences: bool = True
    # Ignore messages shorter than this, and truncate anything longer.
    min_fact_chars: int = 8
    max_fact_chars: int = 2000
    # Base confidence for a plainly stated fact.
    base_confidence: float = 0.6
    # Confidence penalty when the statement is hedged ("I think...", "maybe").
    hedge_penalty: float = 0.2
    # Confidence bump each time the same fact is seen again.
    reinforcement_boost: float = 0.05
    # Confidence ceiling.
    max_confidence: float = 0.99

    # --- Retrieval -------------------------------------------------------
    top_k: int = 5
    # Minimum combined score for a retrieved fact to be shown to the LLM.
    min_score: float = 0.0

    def resolved_db_path(self) -> str:
        return self.db_path
