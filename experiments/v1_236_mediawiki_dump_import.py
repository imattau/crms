"""Exercise bounded plain and compressed MediaWiki dump ingestion."""

from __future__ import annotations

import bz2
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.sax.saxutils

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_import_wikidump import import_dump, render_wikitext
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def dump_xml() -> bytes:
    pages = [
        "<page><title>Commons page</title><ns>1</ns><id>9001</id>"
        "<revision><id>9002</id><text>not main namespace</text></revision></page>",
        "<page><title>Redirect page</title><ns>0</ns><id>9003</id>"
        "<redirect title=\"Commons page\"/><revision><id>9004</id>"
        "<text>#REDIRECT [[Commons page]]</text></revision></page>",
    ]
    for number in range(260):
        text = fixture_text(number)
        escaped = xml.sax.saxutils.escape(text)
        if number == 0:
            pages.append(
                "<page><title>Fixture article 0</title><ns>0</ns><id>0</id>"
                "<revision><id>1</id><text>outdated version</text></revision>"
                f"<revision><id>2</id><text>{escaped}</text></revision></page>")
        else:
            pages.append(
                f"<page><title>Fixture article {number}</title><ns>0</ns>"
                f"<id>{number}</id><revision><id>{number + 1000}</id>"
                f"<text>{escaped}</text></revision></page>")
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<mediawiki><siteinfo><dbname>fixturewiki</dbname>"
            "<base>https://fixturewiki.example/wiki/Main_Page</base></siteinfo>"
            + "".join(pages) + "</mediawiki>").encode("utf-8")


def fixture_text(number: int) -> str:
    if number == 259:
        return ("'''Fixture article 259''' describes a deterministic machine. "
                "Zephyrlark capacitor specification: "
                "[[Capacitor|47 microfarads]] in [[electronics]]."
                "<ref>citation noise</ref>")
    return (f"Fixture article {number} describes a deterministic "
            "machine component. It is used for test coverage.")


def check_index(path: Path) -> None:
    index = CRMSSQLiteResearchIndex.load(path)
    try:
        require(index.document_count() == 260,
                f"namespace or redirect filtering failed: {index.document_count()}")
        hit = index.search("Zephyrlark capacitor specification", limit=1)[0]
        readable = index.document(hit.document_id).text
        require(hit.document_id == "wiki:fixturewiki:259"
                and "47 microfarads" in hit.snippet
                and "[[" not in readable and "'''" not in readable
                and "citation noise" not in readable
                and index.resolve_citation(index.citation(hit)) == hit.snippet,
                f"later-batch retrieval or citation failed: {hit}")
        initial = index.search("outdated version", limit=2)
        require(not initial,
                "import retained an earlier revision instead of the current revision")
        location = index.document("wiki:fixturewiki:259").location or ""
        require("https://fixturewiki.example/w/index.php?title=" in location
                and "oldid=1259" in location
                and "CC BY-SA 4.0" in location
                and "creativecommons.org/licenses/by-sa/4.0/" in location,
                f"revision citation or license attribution was lost: {location}")
    finally:
        index.close()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-wikidump-") as temporary:
        root = Path(temporary)
        source_bytes = dump_xml()
        plain = root / "fixture-pages-articles.xml"
        compressed = root / "fixture-pages-articles.xml.bz2"
        plain.write_bytes(source_bytes)
        compressed.write_bytes(bz2.compress(source_bytes))
        for source in (plain, compressed):
            destination = root / (source.name + ".sqlite")
            dbname, page_count, size = import_dump(
                source, destination, license_name="CC BY-SA 4.0",
                license_url="https://creativecommons.org/licenses/by-sa/4.0/")
            require((dbname, page_count, size) == (
                "fixturewiki", 260,
                sum(len(fixture_text(n).encode())
                    for n in range(260))),
                f"import summary was incorrect: {(dbname, page_count, size)}")
            check_index(destination)

        cli_output = root / "cli.sqlite"
        cli = subprocess.run(
            [sys.executable, str(PROJECT / "crms_import_wikidump.py"),
             str(compressed), "--output", str(cli_output),
             "--license-name", "CC BY-SA 4.0", "--license-url",
             "https://creativecommons.org/licenses/by-sa/4.0/"],
            text=True, capture_output=True, timeout=30)
        require(cli.returncode == 0 and "Imported 260 pages" in cli.stdout,
                f"dump importer CLI failed:\n{cli.stdout}\n{cli.stderr}")
        check_index(cli_output)

        malformed = root / "malformed.xml"
        malformed.write_text("<mediawiki><page>", encoding="utf-8")
        failed_output = root / "must-not-exist.sqlite"
        try:
            import_dump(
                malformed, failed_output, license_name="CC BY-SA 4.0",
                license_url="https://creativecommons.org/licenses/by-sa/4.0/")
        except ValueError:
            require(not failed_output.exists(),
                    "failed import published a partial index")
        else:
            raise AssertionError("malformed dump was accepted")

    print("MediaWiki dump import diagnostic: PASS")
    print("streaming XML/bzip2, main-namespace filtering, latest revision, "
          "batched retrieval, citations, CLI, and failed-import cleanup: PASS")


if __name__ == "__main__":
    main()
