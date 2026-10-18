"""Check explicit single-page web capture and snapshot citations."""

from __future__ import annotations

import contextlib
import io
import json
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
    def __init__(self, body: bytes, content_type: str | None = "text/html; charset=utf-8",
                 url: str = "https://example.test/final") -> None:
        self.body = body
        self.url = url
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def main() -> None:
    page = (b"<html><head><title>Engine Notes</title>"
            b"<script>secret-token</script></head><body>"
            b"<main><h1>Engine</h1><p>Ada designed the test engine.</p>"
            b"</main></body></html>")
    index = CRMSResearchIndex()
    calls = []

    def fetch(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse(page)

    with patch.object(crms_research, "urlopen", fetch):
        index.add_url("https://example.test/start", timeout=3)
    doc = index.document("https://example.test/start")
    if doc.title != "Engine Notes" or doc.location != "https://example.test/final":
        raise SystemExit(f"captured page metadata is incorrect: {doc}")
    if "secret-token" in doc.text or "Ada designed the test engine." not in doc.text:
        raise SystemExit(f"readable page extraction failed: {doc.text!r}")
    if calls != [("https://example.test/start", 3)]:
        raise SystemExit(f"fetch request did not preserve explicit URL/timeout: {calls}")
    hits = index.search("Ada designed engine", limit=1)
    if not hits or index.resolve_citation(index.citation(hits[0])) != hits[0].snippet:
        raise SystemExit("URL snapshot search citation did not resolve exactly")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        saved = root / "index.json"
        index.save(saved)
        restored = CRMSResearchIndex.load(saved)
        citation = restored.citation(restored.search("designed engine", limit=1)[0])
        if restored.resolve_citation(citation) != hits[0].snippet:
            raise SystemExit("URL snapshot citation failed after save/load")

        # Exercise the real terminal command path with network I/O mocked.
        paths = [root / name for name in (
            "knowledge.json", "research.json", "dialogue.json",
            "rules.json", "session.json")]
        cli_args = ["crms_chat.py", "--knowledge", str(paths[0]),
                    "--index", str(paths[1]), "--dialogue-state", str(paths[2]),
                    "--rules", str(paths[3]), "--rule-session", str(paths[4])]
        with patch.object(crms_research, "urlopen", fetch), \
                patch("builtins.input", side_effect=[
                    "/source https://example.test/start", "/sources", "/quit"]), \
                patch.object(sys, "argv", cli_args), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            status = crms_chat.main()
        if status != 0 or "Indexed Engine Notes" not in output.getvalue():
            raise SystemExit(f"terminal URL ingestion failed: {output.getvalue()}")
        stored = json.loads(paths[1].read_text(encoding="utf-8"))
        if stored["documents"][0]["location"] != "https://example.test/final":
            raise SystemExit("terminal did not persist the final source URL")

    invalid = ("file:///etc/passwd", "https://user:pass@example.test/page")
    for url in invalid:
        try:
            index.add_url(url)
        except ValueError:
            pass
        else:
            raise SystemExit(f"unsafe URL form was accepted: {url}")

    invalid_responses = (
        (FakeResponse(b"x" * 20, content_type="text/html"), 10,
         "capture limit"),
        (FakeResponse(b"%PDF", content_type="application/pdf"), 100,
         "content type"),
        (FakeResponse(b"page", content_type=None), 100,
         "missing a content type"),
        (FakeResponse(b"page", url="https://user:pass@example.test/page"), 100,
         "redirected outside HTTP(S)"),
    )
    for response, max_bytes, message in invalid_responses:
        with patch.object(crms_research, "urlopen",
                          lambda *_args, _response=response, **_kwargs: _response):
            try:
                CRMSResearchIndex().add_url("https://example.test/page",
                                            max_bytes=max_bytes)
            except ValueError as error:
                if message not in str(error):
                    raise SystemExit(f"unexpected ingestion error: {error}")
            else:
                raise SystemExit(f"invalid capture was accepted: {message}")

    print("explicit URL research diagnostic: PASS")
    print("readable extraction, exact snapshot citations, persistence, CLI, limits, URL/content guards: PASS")


if __name__ == "__main__":
    main()
