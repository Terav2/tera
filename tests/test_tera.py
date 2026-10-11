"""Tests for Tera. Run with:  pytest -q   (or: python tests/test_tera.py)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tera import Tera, TeraConfig
from tera.kb import curator as C


def new_tera():
    return Tera(config=TeraConfig(db_path=":memory:"))


# --------------------------------------------------------------------------- #
# curator: the "don't store questions" behaviour
# --------------------------------------------------------------------------- #
def test_rejects_questions():
    tera = new_tera()
    for q in [
        "What is the capital of France?",
        "Where is the Eiffel Tower",
        "How do you make tea?",
        "Can you help me",
        "Is it going to rain",
        "why",
    ]:
        assert tera.learn(q).stored is False, q
        assert tera.learn(q).decision == C.REJECT_QUESTION or not tera.learn(q).stored
    tera.close()


def test_rejects_chitchat_and_commands():
    tera = new_tera()
    for m in ["hi", "hello there", "thanks!", "ok", "Write me a poem", "Generate an image"]:
        assert tera.learn(m).stored is False, m
    tera.close()


def test_stores_statements():
    tera = new_tera()
    assert tera.learn("The Eiffel Tower is located in Paris.").stored is True
    assert tera.learn("Water boils at 100 degrees Celsius.").stored is True
    assert tera.store.active_count() == 2
    tera.close()


# --------------------------------------------------------------------------- #
# consolidation
# --------------------------------------------------------------------------- #
def test_deduplication_and_reinforcement():
    tera = new_tera()
    r1 = tera.learn("Paris is the capital of France.")
    r2 = tera.learn("Paris is the capital of France.")
    assert r1.action == "added"
    assert r2.action == "reinforced"
    assert tera.store.active_count() == 1
    fact = tera.store.all_active()[0]
    assert fact.reinforcements >= 1
    assert fact.confidence > 0.6
    tera.close()


def test_contradiction_supersedes():
    tera = new_tera()
    tera.learn("The Eiffel Tower is located in Paris.")
    res = tera.learn("The Eiffel Tower is located in Berlin.")
    assert res.action == "superseded"
    active = [f.content for f in tera.store.all_active()]
    assert any("Berlin" in c for c in active)
    assert not any("Paris" in c for c in active)          # old one versioned out
    assert tera.store.total_count() == 2                   # but history kept
    tera.close()


# --------------------------------------------------------------------------- #
# retrieval + answering
# --------------------------------------------------------------------------- #
def test_answers_from_base():
    tera = new_tera()
    tera.learn("The Eiffel Tower is located in Paris.")
    tera.learn("Paris is the capital of France.")
    ans = tera.ask("Where is the Eiffel Tower?")
    assert ans.grounded
    assert "Paris" in ans.text
    tera.close()


def test_honest_when_unknown():
    tera = new_tera()
    ans = tera.ask("What is the population of Mars?")
    assert ans.facts == []
    assert "don't have" in ans.text.lower() or "not" in ans.text.lower()
    tera.close()


def test_persistence_roundtrip(tmp_path):
    db = str(tmp_path / "kb")
    t1 = Tera(config=TeraConfig(db_path=db))
    t1.learn("ISRO was founded in 1969.")
    t1.close()
    t2 = Tera(config=TeraConfig(db_path=db))
    assert t2.store.active_count() == 1
    assert "1969" in t2.ask("When was ISRO founded?").text
    t2.close()


def test_chat_routing():
    tera = new_tera()
    assert tera.chat("hi").kind == "chitchat"
    assert tera.chat("The Ganga is a river in India.").kind == "stored"
    assert tera.chat("Where is the Ganga?").kind == "answered"
    tera.close()


def test_stats_counters():
    tera = new_tera()
    tera.learn("A fact about something here.")
    tera.learn("What is a fact?")
    s = tera.stats()
    assert s["added"] == 1
    assert s["rejected"] >= 1
    tera.close()


if __name__ == "__main__":
    import inspect
    import tempfile

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            kwargs = {}
            if "tmp_path" in inspect.signature(fn).parameters:
                kwargs["tmp_path"] = Path(tempfile.mkdtemp())
            try:
                fn(**kwargs)
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
