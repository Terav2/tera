"""Tests for the MongoDB-backed store, using mongomock as an in-memory stand-in.

Run:  python tests/test_mongo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mongomock

from tera import Tera, TeraConfig
from tera.kb import MongoFactStore, open_store


def store():
    return MongoFactStore(client=mongomock.MongoClient())


def tera_with_mongo():
    return Tera(config=TeraConfig(db_path=":memory:", web_search_enabled=False),
                store=store())


def test_store_add_reinforce_supersede():
    s = store()
    id1 = s.add_fact("Paris is the capital of France.", subject="Paris",
                     predicate="is", object="the capital of France")
    assert s.active_count() == 1
    # exact repeat -> reinforce, no new row
    s.add_fact("Paris is the capital of France.", subject="Paris",
               predicate="is", object="the capital of France")
    assert s.active_count() == 1
    fact = s.get(id1)
    assert fact.reinforcements >= 1 and fact.confidence > 0.6
    # correction -> supersede
    id2 = s.add_fact("Paris is the capital of Italy.", subject="Paris",
                     predicate="is", object="the capital of Italy")
    assert s.active_count() == 2 and s.total_count() == 2   # both active until superseded
    s.supersede(id1, id2)
    assert s.active_count() == 1                            # old versioned out
    s.close()


def test_contradiction_through_engine():
    tera = tera_with_mongo()
    tera.learn("The Eiffel Tower is located in Paris.")
    res = tera.learn("The Eiffel Tower is located in Berlin.")
    assert res.action == "superseded"
    active = [f.content for f in tera.store.all_active()]
    assert any("Berlin" in c for c in active) and not any("Paris" in c for c in active)
    assert tera.store.total_count() == 2
    tera.close()


def test_full_pipeline_on_mongo():
    tera = tera_with_mongo()
    assert tera.learn("ISRO was founded in 1969.").stored
    assert tera.learn("When was ISRO founded?").stored is False     # question rejected
    ans = tera.ask("When was ISRO founded?")
    assert ans.grounded and "1969" in ans.text
    s = tera.stats()
    assert s["added"] == 1 and s["rejected"] >= 1
    tera.close()


def test_mongo_dedup_and_stats():
    tera = tera_with_mongo()
    tera.learn("Water boils at 100 degrees Celsius.")
    tera.learn("Water boils at 100 degrees Celsius.")
    s = tera.stats()
    assert s["active_facts"] == 1
    assert s["reinforced"] == 1
    tera.close()


def test_postings_index():
    s = store()
    s.add_fact("The Eiffel Tower is located in Paris.")
    hits = s.postings_for(["paris", "eiffel"])
    assert hits and all(h["df"] >= 1 for h in hits)
    s.close()


def test_open_store_falls_back_to_embedded(monkeypatch=None):
    # With no URI configured, the factory must return the embedded store.
    import os
    os.environ.pop("TERA_MONGODB_URI", None)
    os.environ.pop("MONGODB_URI", None)
    cfg = TeraConfig(db_path=":memory:", mongodb_uri="")
    st = open_store(cfg)
    assert type(st).__name__ == "FactStore"
    st.close()


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
