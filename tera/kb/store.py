"""The knowledge-base store — a document database (Mongita), no SQL, no setup.

Mongita is a MongoDB-style document store that runs *embedded* in the process:
no server, no daemon, no configuration. The whole base lives in a folder on
disk (or in memory), so there is genuinely nothing for the user to set up.

Because Mongita's query language is a deliberate subset of Mongo's (no
`$regex`, no unique indexes, no upsert), Tera keeps two things in application
code instead:

  * an **inverted index** (`postings` collection: token -> [fact ids]) that
    gives fast keyword retrieval without a full scan; and
  * **uniqueness** on `content_hash`, enforced by lookup before insert.

Collections
-----------
facts     : one document per stored piece of knowledge
postings  : inverted index, token -> fact ids
meta      : small key/value counters
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from mongita import MongitaClientDisk, MongitaClientMemory

from .models import Fact
from .text import content_hash, tokenize


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FactStore:
    def __init__(self, path: str = "tera_knowledge"):
        self.path = path
        if path in (":memory:", "", None):
            self.client = MongitaClientMemory()
            self.path = ":memory:"
        else:
            Path(path).mkdir(parents=True, exist_ok=True)
            self.client = MongitaClientDisk(host=path)

        self.db = self.client.tera
        self.facts = self.db.facts
        self.postings = self.db.postings
        self.meta = self.db.meta

        # Non-unique indexes only (Mongita supports these).
        self.facts.create_index("content_hash")
        self.facts.create_index("status")
        self.postings.create_index("token")

    # ------------------------------------------------------------------ #
    # inverted index
    # ------------------------------------------------------------------ #
    def _index_tokens(self, fact_id, tokens: List[str]) -> None:
        for tok in tokens:
            row = self.postings.find_one({"token": tok})
            if row is None:
                self.postings.insert_one({"token": tok, "ids": [fact_id], "df": 1})
            else:
                ids = row.get("ids", [])
                if fact_id not in ids:
                    ids.append(fact_id)
                    self.postings.update_one(
                        {"_id": row["_id"]},
                        {"$set": {"ids": ids, "df": len(ids)}},
                    )

    def postings_for(self, tokens: List[str]) -> List[dict]:
        if not tokens:
            return []
        return list(self.postings.find({"token": {"$in": list(tokens)}}))

    def vocabulary_size(self) -> int:
        return self.postings.count_documents({})

    # ------------------------------------------------------------------ #
    # writes
    # ------------------------------------------------------------------ #
    def add_fact(
        self,
        content: str,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        object: Optional[str] = None,
        category: str = "fact",
        confidence: float = 0.6,
        source: Optional[str] = None,
    ):
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
        fid = self.facts.insert_one(doc).inserted_id
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
        rows = list(self.facts.find({"status": "active"}))
        s, p = (subject or "").lower(), (predicate or "").lower()
        return [
            r for r in rows
            if (r.get("subject") or "").lower() == s
            and (r.get("predicate") or "").lower() == p
        ]

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
        rows = list(self.facts.find({"status": "active"}).sort("updated_at", -1))
        return [self._to_fact(r) for r in rows[:limit]]

    # ------------------------------------------------------------------ #
    # meta counters (no upsert in Mongita — do it by hand)
    # ------------------------------------------------------------------ #
    def meta_inc(self, key: str, n: int = 1) -> None:
        row = self.meta.find_one({"key": key})
        if row is None:
            self.meta.insert_one({"key": key, "value": n})
        else:
            self.meta.update_one({"_id": row["_id"]}, {"$inc": {"value": n}})

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
