"""Data models for the knowledge base."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Fact:
    """A single stored piece of knowledge."""

    id: Optional[int]
    content: str
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    category: str = "fact"          # fact | definition | preference | profile
    confidence: float = 0.6
    reinforcements: int = 0
    status: str = "active"          # active | superseded
    superseded_by: Optional[int] = None
    source: Optional[str] = None
    content_hash: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row) -> "Fact":
        d = dict(row)
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Candidate:
    """A fact proposed by the curator, before consolidation."""

    content: str
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    category: str = "fact"
    confidence: float = 0.6
    source: str = "user"
    meta: dict = field(default_factory=dict)
