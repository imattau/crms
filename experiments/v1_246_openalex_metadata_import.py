"""Offline contract for OpenAlex metadata and reconstructed abstract indexing."""

from __future__ import annotations

import json
import gzip
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crms_import_openalex as openalex
from crms_import_openalex import (import_openalex, reconstruct_abstract,
                                  import_openalex_snapshot, search_works)
from crms_research import CRMSSQLiteResearchIndex


def work(identifier: str, title: str) -> dict:
    return {
        "id": f"https://openalex.org/{identifier}",
        "doi": f"https://doi.org/10.5555/{identifier.casefold()}",
        "display_name": title,
        "publication_year": 2024,
        "type": "article",
        "authorships": [{"author": {"display_name": "Ada Researcher"}}],
        "open_access": {"is_oa": True, "oa_status": "green"},
        "best_oa_location": {
            "version": "acceptedVersion", "license": "cc-by",
            "landing_page_url": "https://repo.example/paper",
            "pdf_url": "https://repo.example/paper.pdf",
            "source": {"display_name": "Example Repository"},
        },
        "primary_location": None,
        "abstract_inverted_index": {
            "Proof": [0], "guards": [1], "preserve": [2],
            "explanation": [3], "citations": [4], ".": [5]},
    }


def response(rows: list[dict], next_cursor: str | None) -> bytes:
    return json.dumps({"results": rows,
                       "meta": {"next_cursor": next_cursor}}).encode()


def main() -> None:
    calls: list[str] = []

    def fetch(url: str, *, max_bytes: int):
        calls.append(url)
        query = parse_qs(urlsplit(url).query)
        if int(query.get("per_page", ["0"])[0]) not in {2, 3}:
            raise SystemExit(f"OpenAlex paging parameter mismatch: {query}")
        if query.get("api_key") != ["fake-key"]:
            raise SystemExit("API key was not sent for cursor pagination")
        if query.get("cursor") == ["*"]:
            return response([work("W100", "Rule Learning in CRMS")], "cursor-2")
        return response([work("W200", "Evidence-Bounded Language Learning"),
                         work("W100", "Rule Learning in CRMS")], None)

    with tempfile.TemporaryDirectory(prefix="crms-openalex-") as folder:
        db = Path(folder) / "research.sqlite"
        added, duplicates, invalid = import_openalex(
            "rule learning", db, max_results=3, mailto="research@example.org",
            api_key="fake-key", fetch=fetch)
        if (added, duplicates, invalid) != (2, 0, 0):
            raise SystemExit(f"unexpected import counts: {(added, duplicates, invalid)}")
        if (len(calls) != 2 or any(
                "abstract_inverted_index" not in parse_qs(
                    urlsplit(call).query).get("select", [""])[0]
                for call in calls)):
            raise SystemExit(f"paging/select request contract failed: {calls}")
        if any(parse_qs(urlsplit(call).query).get("mailto") != ["research@example.org"]
               for call in calls):
            raise SystemExit("mailto was not forwarded to OpenAlex")
        index = CRMSSQLiteResearchIndex(db)
        try:
            abstract_hits = index.search("explanation citations", limit=3)
            if not any(item.document_id == "openalex:W200"
                       for item in abstract_hits):
                raise SystemExit("reconstructed abstract was not searchable")
            hit = index.search("Evidence Bounded Language", limit=3)
            if not any(item.document_id == "openalex:W200" for item in hit):
                raise SystemExit("metadata record was not searchable in SQLite")
            doc = index.document("openalex:W200")
            if ("Metadata license: CC0" not in doc.text
                    or "license: cc-by" not in doc.text
                    or "acceptedVersion" not in doc.text
                    or "paper.pdf" not in doc.text
                    or "Abstract: Proof guards preserve explanation citations." not in doc.text
                    or "Full text was not downloaded" not in doc.text):
                raise SystemExit("metadata/license boundary was not preserved")
        finally:
            index.close()

        added_again, duplicates_again, invalid_again = import_openalex(
            "rule learning", db, max_results=3, append=True,
            api_key="fake-key",
            fetch=lambda _url, **_kwargs: response(
                [work("W100", "Rule Learning in CRMS")], None))
        if (added_again, duplicates_again, invalid_again) != (0, 1, 0):
            raise SystemExit("append did not deduplicate by stable OpenAlex work ID")

    with tempfile.TemporaryDirectory(prefix="crms-openalex-snapshot-") as folder:
        root = Path(folder)
        part_a, part_b = root / "part_a.jsonl.gz", root / "part_b.jsonl.gz"
        with gzip.open(part_a, "wt", encoding="utf-8") as out:
            out.write(json.dumps(work("W401", "Snapshot Evidence One")) + "\n")
            out.write("{malformed json}\n")
            out.write(json.dumps({"display_name": "Missing stable ID"}) + "\n")
        with gzip.open(part_b, "wt", encoding="utf-8") as out:
            out.write(json.dumps(work("W402", "Snapshot Evidence Two")) + "\n")
            out.write(json.dumps(work("W401", "Snapshot Evidence One")) + "\n")
        snapshot_db = root / "snapshot.sqlite"

        def interrupt_after_first_commit(processed, *_args):
            if processed >= 1:
                raise RuntimeError("simulated interruption after committed batch")

        try:
            import_openalex_snapshot(
                [root], snapshot_db, batch_size=1,
                progress=interrupt_after_first_commit)
        except RuntimeError as error:
            if "simulated interruption" not in str(error):
                raise
        else:
            raise SystemExit("snapshot interruption fixture did not stop")
        counts = import_openalex_snapshot(
            [root], snapshot_db, append=True, batch_size=1)
        if counts != (1, 2, 2, 5):
            raise SystemExit(f"snapshot resume counts are wrong: {counts}")

        original_format_work = openalex.format_work
        def reject_reparse(_work):
            raise AssertionError("unchanged completed snapshot part was rescanned")
        openalex.format_work = reject_reparse
        try:
            cached_counts = import_openalex_snapshot(
                [root], snapshot_db, append=True, batch_size=1)
        finally:
            openalex.format_work = original_format_work
        if cached_counts != counts:
            raise SystemExit(
                f"checkpointed snapshot counts changed on cached run: {cached_counts}")

        # A changed input part invalidates only its own checkpoint. Unchanged
        # parts remain reusable while the changed part is parsed and appended.
        changed_part = "\n".join((
            json.dumps(work("W401", "Snapshot Evidence One Revised")),
            json.dumps(work("W403", "Snapshot Evidence Three")),
        )) + "\n"
        with gzip.open(part_a, "wt", encoding="utf-8") as out:
            out.write(changed_part)
        os.utime(part_a, ns=(part_a.stat().st_atime_ns,
                             part_a.stat().st_mtime_ns + 1_000_000_000))
        changed_counts = import_openalex_snapshot(
            [root], snapshot_db, append=True, batch_size=1)
        if changed_counts != (3, 1, 0, 4):
            raise SystemExit(
                f"changed-part checkpoint was not selectively refreshed: {changed_counts}")
        index = CRMSSQLiteResearchIndex(snapshot_db)
        try:
            if index.document_count() != 3:
                raise SystemExit("snapshot append created duplicate work documents")
            if not any(hit.document_id == "openalex:W402"
                       for hit in index.search("explanation citations", limit=5)):
                raise SystemExit("snapshot abstract was not searchable after resume")
            if not any(hit.document_id == "openalex:W403"
                       for hit in index.search("Snapshot Evidence Three", limit=5)):
                raise SystemExit("changed snapshot part was not reprocessed")
            if (index.document("openalex:W401").title
                    != "Snapshot Evidence One Revised"):
                raise SystemExit("changed snapshot work was not refreshed by stable ID")
        finally:
            index.close()

    try:
        import_openalex("x", Path("unused.sqlite"), max_results=1001,
                        fetch=fetch)
    except ValueError:
        pass
    else:
        raise SystemExit("result limit was not enforced")
    try:
        search_works("x", max_results=2, page_size=1,
                     fetch=lambda _url, **_kwargs: response(
                         [work("W300", "One keyless result")], "next"))
    except ValueError as error:
        if "API key" not in str(error):
            raise
    else:
        raise SystemExit("keyless cursor paging did not explain its API-key requirement")
    if reconstruct_abstract({"Hello": [0], ",": [1], "world": [2], ".": [3]}) != "Hello, world.":
        raise SystemExit("abstract reconstruction lost token order or punctuation")
    if reconstruct_abstract({"left": [0], "right": [2]}):
        raise SystemExit("malformed abstract positions were accepted")
    print("OpenAlex metadata import diagnostic: PASS")
    print("bounded cursor paging, CC0 metadata/abstract indexing, ordered abstract reconstruction, gzip JSONL streaming, bounded batch commits, interruption/resume deduplication, unchanged-part skipping, changed-part invalidation, per-copy license/version/URL retention, SQLite search: PASS")


if __name__ == "__main__":
    main()
