"""Check bounded same-origin page capture and exact per-page citations."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from email.message import Message
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crms_chat
import crms_research
from crms_research import CRMSResearchIndex


class FakeResponse:
    def __init__(self, body: bytes, *, url: str) -> None:
        self.body = body
        self.url = url
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


PAGES = {
    "https://example.test/start": (
        b"<title>Start</title><main>Research home"
        b"<a href='/facts/a#part'>A</a>"
        b"<a href='https://other.test/no'>External</a></main>"),
    "https://example.test/facts/a": (
        b"<title>Fact A</title><main>Ada designed a turbine.</main>"
        b"<a href='../facts/b'>B</a>"),
    "https://example.test/facts/b": (
        b"<title>Fact B</title><main>The turbine uses steam.</main>"),
}


def fetch(request, timeout):
    url = request.full_url.split("#", 1)[0]
    if url not in PAGES:
        raise OSError(f"unexpected network request: {url}")
    return FakeResponse(PAGES[url], url=url)


def main() -> None:
    index = CRMSResearchIndex()
    with patch.object(crms_research, "urlopen", fetch):
        result = index.add_site(
            "https://example.test/start", max_pages=5, max_depth=2)
    if result.captured != tuple(PAGES) or len(result.visited) != 3:
        raise SystemExit(f"same-origin traversal failed: {result}")
    if len(index.documents()) != 3:
        raise SystemExit("crawl did not store each page separately")
    hits = index.search("Ada designed turbine", limit=1)
    if not hits or hits[0].document_id != "https://example.test/facts/a":
        raise SystemExit(f"page-specific retrieval failed: {hits}")
    citation = index.citation(hits[0])
    if index.resolve_citation(citation) != hits[0].snippet:
        raise SystemExit("crawled-page citation did not resolve to exact text")

    limited = CRMSResearchIndex()
    with patch.object(crms_research, "urlopen", fetch):
        result = limited.add_site(
            "https://example.test/start", max_pages=2, max_depth=2)
    if len(result.visited) != 2 or len(result.captured) != 2:
        raise SystemExit(f"page limit was not enforced: {result}")

    shallow = CRMSResearchIndex()
    with patch.object(crms_research, "urlopen", fetch):
        result = shallow.add_site(
            "https://example.test/start", max_pages=5, max_depth=0)
    if result.visited != ("https://example.test/start",):
        raise SystemExit(f"depth zero followed links: {result}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        paths = [root / name for name in (
            "knowledge.json", "research.json", "dialogue.json",
            "rules.json", "session.json")]
        cli_args = ["crms_chat.py", "--knowledge", str(paths[0]),
                    "--index", str(paths[1]), "--dialogue-state", str(paths[2]),
                    "--rules", str(paths[3]), "--rule-session", str(paths[4])]
        with patch.object(crms_research, "urlopen", fetch), \
                patch("builtins.input", side_effect=[
                    "/crawl https://example.test/start|3|2", "/sources", "/quit"]), \
                patch.object(sys, "argv", cli_args), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            status = crms_chat.main()
        if status != 0 or "Crawl captured 3 new page(s)" not in output.getvalue():
            raise SystemExit(f"crawl CLI failed: {output.getvalue()}")
        restored = CRMSResearchIndex.load(paths[1])
        if len(restored.documents()) != 3:
            raise SystemExit("CLI crawl did not persist all pages")

    redirected = CRMSResearchIndex()
    with patch.object(crms_research, "urlopen", lambda *_args, **_kwargs:
                      FakeResponse(b"Away", url="https://other.test/page")):
        result = redirected.add_site("https://example.test/start")
    if not result.failures or redirected.documents():
        raise SystemExit("cross-origin redirect was captured")

    print("bounded site research diagnostic: PASS")
    print("same-origin links, depth/page limits, per-page citations, CLI persistence, redirect guard: PASS")


if __name__ == "__main__":
    main()
