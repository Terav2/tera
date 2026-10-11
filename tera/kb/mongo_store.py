"""A MongoDB-backed knowledge-base store.

Drop-in replacement for the embedded `FactStore` (identical public interface),
used when a MongoDB connection string is configured. This is what lets Tera run
on a stateless host such as Vercel: the app has no local state, so any instance
can serve any request, and the knowledge base lives in a real database that
persists.

Use a free MongoDB Atlas cluster, then set:

    TERA_MONGODB_URI = mongodb+srv://user:pass@cluster.mongodb.net

The same collections are used as the embedded store (`facts`, `postings`,
`meta`), so the inverted index and counters behave identically.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .models import Fact
from .text import content_hash, tokenize


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MongoFactStore:
    def __init__(self, uri: Optional[str] = None, db_name: Optional[str] = None, client=None):
        from pymongo import MongoClient

        self.uri = uri or os.environ.get("TERA_MONGODB_URI") or os.environ.get("MONGODB_URI")
        self.db_name = db_name or os.environ.get("TERA_MONGODB_DB", "tera")
        if not self.uri and client is None:
            raise ValueError("MongoFactStore needs a MongoDB URI (TERA_MONGODB_URI)")
        # `client` can be injected (e.g. mongomock) for tests.
        self.client = client or MongoClient(self.uri)
        self.db = self.client[self.db_name]
        self.facts = self.db.facts
        self.postings = self.db.postings
        self.meta = self.db.meta
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            self.facts.create_index("content_hash", unique=True)
            self.facts.create_index("status")
            self.facts.create_index([("subject_lc", 1), ("predicate_lc", 1)])
            self.postings.create_index("token", unique=True)
            self.meta.create_index("key", unique=True)
        except Exception:
            # Index creation is an optimisation; never fatal.
            pass

    # ------------------------------------------------------------------ #
    # inverted index
    # ------------------------------------------------------------------ #
    def _index_tokens(self, fact_id, tokens: List[str]) -> None:
        for tok in tokens:
            self.postings.update_one(
                {"token": tok},
                {"$addToSet": {"ids": fact_id}},
                upsert=True,
            )

    def postings_for(self, tokens: List[str]) -> List[dict]:
        if not tokens:
            return []
        out = []
        for row in self.postings.find({"token": {"$in": list(tokens)}}):
            ids = row.get("ids", [])
            out.append({"token": row["token"], "ids": ids, "df": len(ids)})
        return out

    def vocabulary_size(self) -> int:
        return self.postings.count_documents({})

    # ------------------------------------------------------------------ #
    # writes
    # ------------------------------------------------------------------ #
    def add_fact(self, content, subject=None, predicate=None, object=None,
                 category="fact", confidence=0.6, source=None):
        h = content_hash(content)
        existing = self.find_by_hash(h)
        if existing:
            self.reinforce(existing["_id"], source=source)
            return existing["_id"]

        now = _now()
        tokens = tokenize(" ".join(filter(None, [content, subject, object])))
        doc = {
            "content": content,
            "subject": subject,
            "predicate": predicate,
            "object": object,
            "subject_lc": (subject or "").lower(),
            "predicate_lc": (predicate or "").lower(),
            "category": category,
            "confidence": float(confidence),
            "reinforcements": 0,
            "status": "active",
            "superseded_by": None,
            "source": source,
            "content_hash": h,
            "tokens": tokens,
            "created_at": now,
            "updated_at": now,
        }
        try:
            fid = self.facts.insert_one(doc).inserted_id
        except Exception:
            # Duplicate (race) — reinforce whatever is already there.
            existing = self.find_by_hash(h)
            if existing:
                self.reinforce(existing["_id"], source=source)
                return existing["_id"]
            raise
        self._index_tokens(fid, tokens)
        self.meta_inc("facts_added")
        return fid

    def reinforce(self, fact_id, boost: float = 0.05, source: Optional[str] = None) -> None:
        row = self.facts.find_one({"_id": fact_id})
        if not row:
            return
        new_conf = min(0.99, float(row.get("confidence", 0.6)) + boost)
        self.facts.update_one(
            {"_id": fact_id},
            {"$set": {"confidence": new_conf, "updated_at": _now()},
             "$inc": {"reinforcements": 1}},
        )
        self.meta_inc("facts_reinforced")

    def supersede(self, old_id, new_id) -> None:
        self.facts.update_one(
            {"_id": old_id},
            {"$set": {"status": "superseded", "superseded_by": new_id,
                      "updated_at": _now()}},
        )
        self.meta_inc("facts_superseded")

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def find_by_hash(self, h: str) -> Optional[dict]:
        return self.facts.find_one({"content_hash": h})

    def find_active_by_sp(self, subject: str, predicate: str) -> List[dict]:
        return list(self.facts.find({
            "status": "active",
            "subject_lc": (subject or "").lower(),
            "predicate_lc": (predicate or "").lower(),
        }))

    def get(self, fact_id) -> Optional[Fact]:
        row = self.facts.find_one({"_id": fact_id})
        return self._to_fact(row) if row else None

    def get_many(self, ids: List) -> List[dict]:
        if not ids:
            return []
        return list(self.facts.find({"_id": {"$in": list(ids)}}))

    def active_count(self) -> int:
        return self.facts.count_documents({"status": "active"})

    def total_count(self) -> int:
        return self.facts.count_documents({})

    def all_active(self, limit: int = 1000) -> List[Fact]:
        rows = list(self.facts.find({"status": "active"}).sort("updated_at", -1).limit(limit))
        return [self._to_fact(r) for r in rows]

    # ------------------------------------------------------------------ #
    # meta counters
    # ------------------------------------------------------------------ #
    def meta_inc(self, key: str, n: int = 1) -> None:
        self.meta.update_one({"key": key}, {"$inc": {"value": n}}, upsert=True)

    def meta_get(self, key: str, default: int = 0) -> int:
        row = self.meta.find_one({"key": key})
        return int(row["value"]) if row else default

    def stats(self) -> Dict[str, int]:
        return {
            "active_facts": self.active_count(),
            "total_facts": self.total_count(),
            "vocabulary": self.vocabulary_size(),
            "added": self.meta_get("facts_added"),
            "reinforced": self.meta_get("facts_reinforced"),
            "superseded": self.meta_get("facts_superseded"),
            "rejected": self.meta_get("rejected"),
            "queries": self.meta_get("queries"),
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_fact(row: dict) -> Fact:
        return Fact(
            id=str(row.get("_id")),
            content=row.get("content", ""),
            subject=row.get("subject"),
            predicate=row.get("predicate"),
            object=row.get("object"),
            category=row.get("category", "fact"),
            confidence=row.get("confidence", 0.6),
            reinforcements=row.get("reinforcements", 0),
            status=row.get("status", "active"),
            superseded_by=row.get("superseded_by"),
            source=row.get("source"),
            content_hash=row.get("content_hash", ""),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
