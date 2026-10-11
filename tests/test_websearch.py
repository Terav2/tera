"""Tests for Tera Search (crawler + inverted index + ranking). No network needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tera.kb.text import tokenize
from tera.websearch import WebSearch, InvertedIndex, extract
from tera.websearch import engine as engine_mod

PAGES = {
    "https://en.wikipedia.org/wiki/ISRO": (
        "<html><head><title>ISRO</title></head><body>"
        "<p>The Indian Space Research Organisation was founded in 1969.</p>"
        "<a href='/wiki/Chandrayaan-3'>Chandrayaan</a>"
        "<script>var x = 'ignore me';</script></body></html>"
    ),
    "https://en.wikipedia.org/wiki/Chandrayaan-3": (
        "<html><head><title>Chandrayaan-3</title></head><body>"
        "<p>Chandrayaan-3 landed near the south pole of the Moon in 2023.</p>"
        "</body></html>"
    ),
    "https://example.com/about": (
        "<html><head><title>About</title></head><body>"
        "<p>Bananas are a good source of potassium.</p></body></html>"
    ),
}


def fake_fetch(url, timeout=15):
    return PAGES.get(url)


def test_extract_pulls_title_text_links():
    page = extract(PAGES["https://en.wikipedia.org/wiki/ISRO"],
                   "https://en.wikipedia.org/wiki/ISRO")
    assert page["title"] == "ISRO"
    assert "founded in 1969" in page["text"]
    assert "ignore me" not in page["text"]          # scripts skipped
    assert "https://en.wikipedia.org/wiki/Chandrayaan-3" in page["links"]


def test_inverted_index_ranks_by_relevance():
    idx = InvertedIndex()
    idx.add("a", "u1", "ISRO", "The Indian Space Research Organisation was founded in 1969.",
            tokenize("The Indian Space Research Organisation was founded in 1969."),
            tokenize("ISRO"))
    idx.add("b", "u2", "Bananas", "Bananas are a good source of potassium.",
            tokenize("Bananas are a good source of potassium."), tokenize("Bananas"))
    hits = idx.search(tokenize("when was ISRO founded"), k=5)
    assert hits and hits[0]["doc_id"] == "a"


def test_crawl_and_search(monkeypatch=None):
    original = engine_mod.fetch
    engine_mod.fetch = fake_fetch
    try:
        ws = WebSearch(path=None)
        pages = ws.crawl(["https://en.wikipedia.org/wiki/ISRO"], depth=1, max_pages=10)
        assert pages == 2                              # followed the same-domain link
        assert "https://example.com/about" not in ws.index.docs
        hits = ws.search("when was ISRO founded", k=3)
        assert hits and "ISRO" in hits[0]["title"]
        assert hits[0]["snippet"]
    finally:
        engine_mod.fetch = original


def test_save_and_load(tmp_path=None):
    import tempfile, os
    original = engine_mod.fetch
    engine_mod.fetch = fake_fetch
    try:
        ws = WebSearch(path=None)
        ws.crawl(["https://en.wikipedia.org/wiki/ISRO"], depth=1, max_pages=10)
        path = os.path.join(tempfile.mkdtemp(), "idx.json")
        ws.save(path)
        again = WebSearch(path)
        assert again.index.n_docs == ws.index.n_docs
        assert again.search("chandrayaan moon", k=1)
    finally:
        engine_mod.fetch = original


def test_unrelated_query_scores_low():
    original = engine_mod.fetch
    engine_mod.fetch = fake_fetch
    try:
        ws = WebSearch(path=None)
        ws.crawl(["https://en.wikipedia.org/wiki/ISRO"], depth=1, max_pages=10)
        hits = ws.search("who won the 2050 world cup", k=3)
        assert all(h["score"] < 1.0 for h in hits)     # nothing meaningful matches
    finally:
        engine_mod.fetch = original


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
            except Exception as e:
                failures += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
