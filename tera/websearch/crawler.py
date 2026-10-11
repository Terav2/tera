"""A small web crawler — HTTP plus the standard library, nothing else.

It fetches a page, then pulls out its title, its readable text and its links.
No third-party search service is involved anywhere: this is our own fetcher.
"""

from __future__ import annotations

import gzip
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Dict, List, Optional

USER_AGENT = "TeraBot/0.1 (+https://github.com/Terav2/tera)"

# Elements whose text is not readable content.
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "nav", "footer", "form"}


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: List[str] = []
        self.chunks: List[str] = []
        self.links: List[str] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            for key, value in attrs:
                if key == "href" and value:
                    self.links.append(value)

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if not self._skip:
            text = data.strip()
            if text:
                self.chunks.append(text)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())

    @property
    def text(self) -> str:
        return " ".join(self.chunks)


def fetch(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch a URL and return its HTML, or None if it isn't HTML."""
    scheme = urllib.parse.urlparse(url).scheme
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}

    if scheme in ("http", "https"):
        headers["Accept-Encoding"] = "gzip"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        ctype = (resp.headers.get("Content-Type") or "").lower()

    if scheme not in ("http", "https"):
        return raw.decode("utf-8", "replace")
    if ctype and "html" not in ctype and "text" not in ctype:
        return None
    if "gzip" in encoding:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    return raw.decode("utf-8", "replace")


def extract(html: str, base_url: str) -> Dict:
    """Turn HTML into {title, text, links} (links made absolute)."""
    parser = _Extractor()
    try:
        parser.feed(html)
    except Exception:
        pass

    links: List[str] = []
    seen = set()
    for href in parser.links:
        absolute, _ = urllib.parse.urldefrag(urllib.parse.urljoin(base_url, href))
        if absolute.startswith(("http://", "https://")) and absolute not in seen:
            seen.add(absolute)
            links.append(absolute)

    return {"title": parser.title, "text": parser.text, "links": links}
