"""Consolidation: how the base gets *stronger* rather than just *bigger*.

Three behaviours, applied on every stored candidate:

  reinforce  — the same fact seen again raises its confidence instead of
               creating a duplicate row.
  supersede  — a genuine *correction* to the same relation is not an overwrite;
               the old fact is versioned (`superseded`) and points at the new
               one, so history is never lost.
  add        — genuinely new knowledge is inserted and indexed.

The hard part is telling a correction apart from a *complement*. "The Eiffel
Tower is located in Paris" and "The Eiffel Tower was completed in 1889" share a
subject but are not in conflict. We compare a *relation frame* — the predicate
plus the leading content word of the object — and only supersede when the
frames match ("located in X" vs "located in Y"). Two single-word objects with
the same subject+predicate ("the sky is blue" / "the sky is green") are also
treated as conflicting. A real LLM extractor, when attached, sharpens this.
"""

from __future__ import annotations

from typing import Dict, List

from .models import Candidate
from .text import content_hash, normalize

_ARTICLES = {"the", "a", "an"}


def _relation_frame(text: str) -> str:
    """The leading content word of an object phrase, articles stripped."""
    for w in normalize(text or "").split():
        if w not in _ARTICLES:
            return w
    return ""


def _relation_key(predicate: str, obj: str) -> str:
    return f"{(predicate or '').strip().lower()}::{_relation_frame(obj)}"


class Consolidator:
    def __init__(self, store, config):
        self.store = store
        self.cfg = config

    def consolidate(self, cand: Candidate) -> Dict:
        h = content_hash(cand.content)

        # 1. exact duplicate -> reinforce
        existing = self.store.find_by_hash(h)
        if existing:
            self.store.reinforce(
                existing["_id"], boost=self.cfg.reinforcement_boost, source=cand.source
            )
            return {"action": "reinforced", "id": existing["_id"],
                    "content": cand.content}

        # 2. same subject+predicate -> reinforce (same object) or supersede
        to_supersede: List[dict] = []
        if cand.subject and cand.predicate:
            new_obj = normalize(cand.object or "")
            new_key = _relation_key(cand.predicate, cand.object)
            for old in self.store.find_active_by_sp(cand.subject, cand.predicate):
                old_obj = normalize(old.get("object") or "")
                if old_obj == new_obj:
                    self.store.reinforce(
                        old["_id"], boost=self.cfg.reinforcement_boost, source=cand.source
                    )
                    return {"action": "reinforced", "id": old["_id"],
                            "content": old.get("content", cand.content)}
                same_frame = new_key and new_key == _relation_key(
                    old.get("predicate"), old.get("object"))
                both_single = (
                    len(new_obj.split()) == 1 and len(old_obj.split()) == 1
                    and bool(new_obj) and bool(old_obj)
                )
                if same_frame or both_single:
                    to_supersede.append(old)

        # 3. new fact
        fid = self.store.add_fact(
            content=cand.content,
            subject=cand.subject,
            predicate=cand.predicate,
            object=cand.object,
            category=cand.category,
            confidence=cand.confidence,
            source=cand.source,
        )

        for old in to_supersede:
            self.store.supersede(old["_id"], fid)

        action = "superseded" if to_supersede else "added"
        return {"action": action, "id": fid, "content": cand.content,
                "superseded_ids": [o["_id"] for o in to_supersede]}
