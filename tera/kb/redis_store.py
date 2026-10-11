"""A Redis-backed knowledge-base store, for stateless hosts such as Vercel.

This is the easiest way to make Tera persist on Vercel: add the Redis
integration from the Vercel dashboard (one click) and it injects the REST URL
and token automatically. No separate account, no cluster to create.

Talks to Redis over its **REST API** (Upstash-style), which is ideal for
serverless functions because every call is a stateless HTTP request — no
connection pool to keep alive.

Recognised environment variables (any of these):
    UPSTASH_REDIS_REST_URL   / UPSTASH_REDIS_REST_TOKEN
    KV_REST_API_URL          / KV_REST_API_TOKEN
    TERA_REDIS_URL           / TERA_REDIS_TOKEN

Data model
----------
tera:seq              counter for fact ids
tera:facts            hash  id -> JSON document
tera:byhash           hash  content_hash -> id   (de-duplication)
tera:sp:<s>|<p>       set   subject+predicate -> ids
tera:tok:<token>      set   token -> ids         (inverted index)
tera:meta             hash  counters
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .models import Fact
from .text import content_hash, tokenize

PREFIX = "tera:"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UpstashTransport:
    """Sends a Redis command to the Upstash REST endpoint and returns the reply."""

    def __init__(self, url: str, token: str, timeout: int = 20):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def __call__(self, *args):
        body = json.dumps([str(a) for a in args]).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            raise RuntimeError(f"Redis HTTP {exc.code}: {exc.read()[:200]!r}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - network path
            raise RuntimeError(f"Redis connection failed: {exc.reason}") from exc
        if isinstance(out, dict) and out.get("error"):
            raise RuntimeError(f"Redis error: {out['error']}")
        return out.get("result") if isinstance(out, dict) else out


_CLIENTS = {}


def _tcp_client(url: str):
    """A cached redis-py client — reused across warm serverless invocations."""
    if url not in _CLIENTS:
        import redis  # from the `redis` package
        _CLIENTS[url] = redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=10,
            health_check_interval=30,
        )
    return _CLIENTS[url]


class RedisTcpTransport:
    """Talks to Redis over TCP using redis-py (for a redis:// or rediss:// URL)."""

    def __init__(self, url: str):
        self._client = _tcp_client(url)

    def __call__(self, *args):
        return self._client.execute_command(*args)


def redis_spec():
    """Work out how to reach Redis.

    Returns one of:
        ("rest", url, token)  -- HTTP REST endpoint (ideal for serverless)
        ("tcp",  url)         -- a redis:// or rediss:// URL (needs redis-py)
        None                  -- nothing configured
    """
    env = os.environ

    # 1. the known REST pairs (Vercel KV / Upstash integration)
    for url_key, tok_key in (
        ("TERA_REDIS_URL", "TERA_REDIS_TOKEN"),
        ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"),
        ("KV_REST_API_URL", "KV_REST_API_TOKEN"),
    ):
        if env.get(url_key) and env.get(tok_key):
            return ("rest", env[url_key], env[tok_key])

    # 2. heuristic: any https endpoint that looks like Upstash, plus its token.
    for key, val in env.items():
        ku = key.upper()
        if not val or not val.startswith("https://"):
            continue
        if "upstash" in val.lower() or "UPSTASH" in ku or ("KV" in ku and "REST" in ku):
            if ku.endswith("_URL"):
                base = ku[:-3]  # strip "URL"
                token = env.get(base + "TOKEN") or env.get(base + "_TOKEN")
                if token:
                    return ("rest", val, token)

    # 3. a plain TCP connection string — what Vercel's Redis integration gives.
    for key in ("TERA_REDIS_TCP_URL", "REDIS_URL", "KV_URL"):
        val = env.get(key)
        if val and val.startswith(("redis://", "rediss://")):
            return ("tcp", val)
    return None


def redis_env_names() -> list:
    """Names (never values) of env vars that look Redis/KV related — diagnostics."""
    names = []
    for k in os.environ:
        ku = k.upper()
        if ku.startswith("KV_") or "REDIS" in ku or "UPSTASH" in ku:
            names.append(k)
    return sorted(names)


class RedisFactStore:
    def __init__(self, transport: Optional[Callable] = None, url: str = None,
                 token: str = None, tcp_url: str = None):
        self.mode = "rest"
        if transport is not None:
            self._cmd = transport
            return
        if tcp_url:
            self.mode = "tcp"
            self._cmd = RedisTcpTransport(tcp_url)
            return
        if url and token:
            self._cmd = UpstashTransport(url, token)
            return
        spec = redis_spec()
        if not spec:
            raise ValueError("RedisFactStore needs a REST url+token or a REDIS_URL")
        if spec[0] == "rest":
            self._cmd = UpstashTransport(spec[1], spec[2])
        else:
            self.mode = "tcp"
            self._cmd = RedisTcpTransport(spec[1])

    # ------------------------------------------------------------------ #
    # small helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_pairs(raw) -> Dict[str, str]:
        """HGETALL may come back as a dict or a flat [k,v,k,v] list."""
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        return {raw[i]: raw[i + 1] for i in range(0, len(raw) - 1, 2)}

    def _get_raw(self, fact_id) -> Optional[dict]:
        raw = self._cmd("HGET", PREFIX + "facts", str(fact_id))
        return json.loads(raw) if raw else None

    def _put_raw(self, doc: dict) -> None:
        self._cmd("HSET", PREFIX + "facts", str(doc["_id"]), json.dumps(doc))

    # ------------------------------------------------------------------ #
    # inverted index
    # ------------------------------------------------------------------ #
    def _index_tokens(self, fact_id, tokens: List[str]) -> None:
        for tok in tokens:
            added = self._cmd("SADD", f"{PREFIX}tok:{tok}", str(fact_id))
            if added == 1 and self._cmd("SCARD", f"{PREFIX}tok:{tok}") == 1:
                self._cmd("HINCRBY", PREFIX + "meta", "vocab", 1)

    def postings_for(self, tokens: List[str]) -> List[dict]:
        out = []
        for tok in tokens:
            ids = self._cmd("SMEMBERS", f"{PREFIX}tok:{tok}") or []
            if ids:
                out.append({"token": tok, "ids": ids, "df": len(ids)})
        return out

    def vocabulary_size(self) -> int:
        return self.meta_get("vocab", 0)

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

        fid = str(self._cmd("INCR", PREFIX + "seq"))
        tokens = tokenize(" ".join(filter(None, [content, subject, object])))
        now = _now()
        doc = {
            "_id": fid,
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
        self._put_raw(doc)
        self._cmd("HSET", PREFIX + "byhash", h, fid)
        self._index_tokens(fid, tokens)
        if subject and predicate:
            self._cmd("SADD", f"{PREFIX}sp:{doc['subject_lc']}|{doc['predicate_lc']}", fid)
        self._cmd("HINCRBY", PREFIX + "meta", "facts_added", 1)
        self._cmd("HINCRBY", PREFIX + "meta", "active", 1)
        return fid

    def reinforce(self, fact_id, boost: float = 0.05, source: Optional[str] = None) -> None:
        doc = self._get_raw(fact_id)
        if not doc:
            return
        doc["confidence"] = min(0.99, float(doc.get("confidence", 0.6)) + boost)
        doc["reinforcements"] = int(doc.get("reinforcements", 0)) + 1
        doc["updated_at"] = _now()
        self._put_raw(doc)
        self._cmd("HINCRBY", PREFIX + "meta", "facts_reinforced", 1)

    def supersede(self, old_id, new_id) -> None:
        doc = self._get_raw(old_id)
        if not doc:
            return
        doc["status"] = "superseded"
        doc["superseded_by"] = str(new_id)
        doc["updated_at"] = _now()
        self._put_raw(doc)
        if doc.get("subject_lc") and doc.get("predicate_lc"):
            self._cmd("SREM", f"{PREFIX}sp:{doc['subject_lc']}|{doc['predicate_lc']}", str(old_id))
        self._cmd("HINCRBY", PREFIX + "meta", "active", -1)
        self._cmd("HINCRBY", PREFIX + "meta", "facts_superseded", 1)

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def find_by_hash(self, h: str) -> Optional[dict]:
        fid = self._cmd("HGET", PREFIX + "byhash", h)
        return self._get_raw(fid) if fid else None

    def find_active_by_sp(self, subject: str, predicate: str) -> List[dict]:
        key = f"{PREFIX}sp:{(subject or '').lower()}|{(predicate or '').lower()}"
        ids = self._cmd("SMEMBERS", key) or []
        return [d for d in self.get_many(ids) if d.get("status") == "active"]

    def get(self, fact_id) -> Optional[Fact]:
        raw = self._get_raw(fact_id)
        return self._to_fact(raw) if raw else None

    def get_many(self, ids: List) -> List[dict]:
        ids = [str(i) for i in ids]
        if not ids:
            return []
        raw = self._cmd("HMGET", PREFIX + "facts", *ids) or []
        return [json.loads(r) for r in raw if r]

    def active_count(self) -> int:
        return self.meta_get("active", 0)

    def total_count(self) -> int:
        return self.meta_get("facts_added", 0)

    def all_active(self, limit: int = 1000) -> List[Fact]:
        pairs = self._to_pairs(self._cmd("HGETALL", PREFIX + "facts"))
        docs = [json.loads(v) for v in pairs.values()]
        docs = [d for d in docs if d.get("status") == "active"]
        docs.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
        return [self._to_fact(d) for d in docs[:limit]]

    # ------------------------------------------------------------------ #
    # meta counters
    # ------------------------------------------------------------------ #
    def meta_inc(self, key: str, n: int = 1) -> None:
        self._cmd("HINCRBY", PREFIX + "meta", key, n)

    def meta_get(self, key: str, default: int = 0) -> int:
        val = self._cmd("HGET", PREFIX + "meta", key)
        return int(val) if val is not None else default

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
        pass
