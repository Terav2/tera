"""Web-layer tests. Run with:  python tests/test_web.py   (or pytest -q)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tera.config import TeraConfig
from tera.webapp import create_app


def client():
    app = create_app(TeraConfig(db_path=":memory:"))
    app.config["TESTING"] = True
    return app.test_client()


def test_index_page():
    c = client()
    r = c.get("/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Tera" in body and "composer" in body and "/api/chat" in body


def test_health():
    c = client()
    d = c.get("/api/health").get_json()
    assert d["status"] == "ok"
    assert d["offline"] is True          # no model attached in tests


def test_learn_and_ask_roundtrip():
    c = client()
    r = c.post("/api/learn", json={"text": "The Eiffel Tower is located in Paris."})
    assert r.status_code == 200 and r.get_json()["stored"] is True

    r = c.post("/api/learn", json={"text": "What is the capital of France?"})
    assert r.get_json()["stored"] is False
    assert r.get_json()["decision"].startswith("reject")

    r = c.post("/api/ask", json={"question": "Where is the Eiffel Tower?"})
    d = r.get_json()
    assert d["grounded"] is True and "Paris" in d["answer"]


def test_chat_routing_via_api():
    c = client()
    assert c.post("/api/chat", json={"message": "hi"}).get_json()["kind"] == "chitchat"
    assert c.post("/api/chat", json={"message": "ISRO was founded in 1969."}).get_json()["kind"] == "stored"
    d = c.post("/api/chat", json={"message": "When was ISRO founded?"}).get_json()
    assert d["kind"] == "answered" and "1969" in d["answer"]


def test_stats_and_facts():
    c = client()
    c.post("/api/learn", json={"text": "Water boils at 100 degrees Celsius."})
    c.post("/api/learn", json={"text": "Is water wet?"})
    s = c.get("/api/stats").get_json()
    assert s["added"] == 1 and s["rejected"] >= 1
    facts = c.get("/api/facts").get_json()
    assert any("Water boils" in f["content"] for f in facts)


def test_validation_errors():
    c = client()
    assert c.post("/api/learn", json={}).status_code == 400
    assert c.post("/api/ask", json={}).status_code == 400
    assert c.post("/api/chat", json={}).status_code == 400


if __name__ == "__main__":
    import inspect

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
