"""The knowledge-base layer: store, curator, retriever, consolidator."""

from __future__ import annotations

import os

from .models import Fact, Candidate
from .store import FactStore
from .curator import Curator, CuratorResult
from .retriever import Retriever
from .consolidator import Consolidator

__all__ = [
    "Fact",
    "Candidate",
    "FactStore",
    "MongoFactStore",
    "RedisFactStore",
    "open_store",
    "Curator",
    "CuratorResult",
    "Retriever",
    "Consolidator",
]


def open_store(config):
    """Return the right store for the environment.

    If a MongoDB connection string is configured, use MongoDB (persists on
    stateless hosts such as Vercel). Otherwise use the embedded document store,
    which needs no setup at all.
    """
    uri = (
        getattr(config, "mongodb_uri", "")
        or os.environ.get("TERA_MONGODB_URI")
        or os.environ.get("MONGODB_URI")
        or ""
    )
    if uri:
        from .mongo_store import MongoFactStore  # imported lazily (needs pymongo)
        return MongoFactStore(uri=uri, db_name=getattr(config, "mongodb_db", None))

    from .redis_store import redis_spec
    if redis_spec():
        from .redis_store import RedisFactStore  # REST or TCP Redis
        return RedisFactStore()

    return FactStore(config.db_path)


def __getattr__(name):
    # Expose the optional remote stores without importing their drivers
    # unless they are actually asked for.
    if name == "MongoFactStore":
        from .mongo_store import MongoFactStore
        return MongoFactStore
    if name == "RedisFactStore":
        from .redis_store import RedisFactStore
        return RedisFactStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
