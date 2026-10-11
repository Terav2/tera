"""Tests for the Redis-backed store, using an in-memory fake of the Redis
REST protocol (so no server or network is needed).

Run:  python tests/test_redis.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tera import Tera, TeraConfig
from tera.kb import RedisFactStore


class FakeRedis:
    """Minimal in-memory stand-in for the Redis commands the store uses."""

    def __init__(self):
        self.hashes = {}
        self.sets = {}
        self.counters = {}

    def __call__(self, *args):
        cmd = str(args[0]).upper()
        a = list(args[1:])

        if cmd == "INCR":
            k = a[0]
            self.counters[k] = int(self.counters.get(k, 0)) + 1
            return self.counters[k]
        if cmd == "HINCRBY":
            k, f, n = a[0], a[1], int(a[2])
            h = self.hashes.setdefault(k, {})
            h[f] = int(h.get(f, 0)) + n
            return h[f]
        if cmd == "HSET":
            k = a[0]
            h = self.hashes.setdefault(k, {})
            added = 0
            for i in range(1, len(a), 2):
                if a[i] not in h:
                    added += 1
                h[a[i]] = a[i + 1]
            return added
        if cmd == "HGET":
            return self.hashes.get(a[0], {}).get(a[1])
        if cmd == "HGETALL":
            out = []
            for k, v in self.hashes.get(a[0], {}).items():
                out.extend([k, v])
            return out
        if cmd == "HMGET":
            h = self.hashes.get(a[0], {})
            return [h.get(f) for f in a[1:]]
        if cmd == "SADD":
            s = self.sets.setdefault(a[0], set())
            before = len(s)
            s.update(str(x) for x in a[1:])
            return 1 if len(s) > before else 0
        if cmd == "SMEMBERS":
            return list(self.sets.get(a[0], set()))
        if cmd == "SCARD":
            return len(self.sets.get(a[0], set()))
        if cmd == "SREM":
            s = self.sets.get(a[0], set())
            n = 0
            for m in a[1:]:
                if m in s:
                    s.discard(m)
                    n += 1
            return n
        raise ValueError(f"unsupported command {cmd}")


def store():
    return RedisFactStore(transport=FakeRedis())


def tera_with_redis():
    return Tera(config=TeraConfig(db_path=":memory:"), store=store())


def test_add_reinforce_supersede():
    s = store()
    id1 = s.add_fact("Paris is the capital of France.", subject="Paris",
                     predicate="is", object="the capital of France")
    assert s.active_count() == 1 and s.total_count() == 1
    s.add_fact("Paris is the capital of France.", subject="Paris",
               predicate="is", object="the capital of France")
    assert s.active_count() == 1                      # deduplicated
    assert s.get(id1).reinforcements >= 1
    id2 = s.add_fact("Paris is the capital of Italy.", subject="Paris",
                     predicate="is", object="the capital of Italy")
    assert s.active_count() == 2
    s.supersede(id1, id2)
    assert s.active_count() == 1                      # old versioned out
    s.close()


def test_full_pipeline_on_redis():
    tera = tera_with_redis()
    assert tera.learn("ISRO was founded in 1969.").stored
    assert tera.learn("When was ISRO founded?").stored is False
    ans = tera.ask("When was ISRO founded?")
    assert ans.grounded and "1969" in ans.text
    st = tera.stats()
    assert st["added"] == 1 and st["rejected"] >= 1
    tera.close()


def test_contradiction_through_engine():
    tera = tera_with_redis()
    tera.learn("The Eiffel Tower is located in Paris.")
    res = tera.learn("The Eiffel Tower is located in Berlin.")
    assert res.action == "superseded"
    active = [f.content for f in tera.store.all_active()]
    assert any("Berlin" in c for c in active) and not any("Paris" in c for c in active)
    tera.close()


def test_postings_and_vocab():
    from tera.kb.text import tokenize
    s = store()
    s.add_fact("The Eiffel Tower is located in Paris.")
    hits = s.postings_for(tokenize("paris eiffel"))
    assert len(hits) == 2 and all(h["df"] == 1 for h in hits)
    assert s.vocabulary_size() > 0
    s.close()


def test_find_active_by_sp():
    s = store()
    s.add_fact("Paris is the capital of France.", subject="Paris",
               predicate="is", object="the capital of France")
    rows = s.find_active_by_sp("Paris", "is")
    assert len(rows) == 1 and rows[0]["object"] == "the capital of France"
    s.close()


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                failures += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
