"""Offline contract for arXiv Atom discovery and metadata-only indexing."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_import_arxiv import (
    API, OAI, import_arxiv, parse_feed, resolve_arxiv_license,
    upgrade_existing_arxiv_full_text,
)
from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_package import (export_model_database, install_model_database,
                          model_database_has_research)
from crms_research import CRMSSQLiteResearchIndex


ATOM = "http://www.w3.org/2005/Atom"
ARXIV = "http://arxiv.org/schemas/atom"


def feed() -> bytes:
    return f'''<?xml version="1.0"?>
<feed xmlns="{ATOM}" xmlns:arxiv="{ARXIV}">
  <entry>
    <id>http://arxiv.org/abs/2601.01234v2</id>
    <title>Proof Search for Symbolic Systems</title>
    <summary>We describe bounded proof search and evidence provenance.</summary>
    <published>2026-01-02T00:00:00Z</published>
    <updated>2026-02-03T00:00:00Z</updated>
    <author><name>Ada Researcher</name></author>
    <author><name>Grace Scientist</name></author>
    <category term="cs.AI"/><category term="cs.LO"/>
    <arxiv:primary_category term="cs.AI"/>
    <arxiv:doi>10.1234/example</arxiv:doi>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2601.01234v2</id>
    <title>duplicate</title><summary>duplicate</summary>
  </entry>
  <entry>
    <id>http://evil.example/abs/2601.99999v1</id>
    <title>invalid host</title><summary>ignore me</summary>
  </entry>
</feed>'''.encode()


def two_paper_feed() -> bytes:
    extra = f'''  <entry>
    <id>http://arxiv.org/abs/2601.88888v1</id>
    <title>Evidence Frames for Search</title>
    <summary>A second independently sourced example.</summary>
    <published>2026-01-03T00:00:00Z</published>
    <updated>2026-02-03T00:00:00Z</updated>
    <author><name>Bea Researcher</name></author>
    <category term="cs.AI"/><arxiv:primary_category term="cs.AI"/>
  </entry>
'''
    return feed().decode().replace("</feed>", extra + "</feed>").encode()


def oai_record(*, base_id: str = "2601.01234", version: str = "v2",
               license_uri: str = "https://creativecommons.org/licenses/by/4.0/") -> bytes:
    return f'''<?xml version="1.0"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:raw="http://arxiv.org/OAI/arXivRaw/">
  <GetRecord><record>
    <header><identifier>oai:arXiv.org:{base_id}</identifier>
      <datestamp>2026-02-03</datestamp></header>
    <metadata><raw:arXivRaw><raw:id>{base_id}</raw:id>
      <raw:version version="v1" /><raw:version version="{version}" />
      <raw:license>{license_uri}</raw:license>
    </raw:arXivRaw></metadata>
  </record></GetRecord>
</OAI-PMH>'''.encode()


def sample_pdf(page_two: str =
               "Second page contains the distinctive arxiv fulltext evidence phrase.") -> bytes:
    texts = ["First page about symbolic systems.", page_two]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        7: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index, content in enumerate(texts):
        page_id = 3 + index * 2
        stream_id = page_id + 1
        stream = f"BT /F1 12 Tf 72 720 Td ({content}) Tj ET".encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 7 0 R >> >> "
            f"/Contents {stream_id} 0 R >>").encode("ascii")
        objects[stream_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream + b"\nendstream")
    output = bytearray(b"%PDF-1.4\n%CRMS\n")
    offsets = [0] * 8
    for object_id in sorted(objects):
        offsets[object_id] = len(output)
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id] + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 8\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend((f"trailer\n<< /Size 8 /Root 1 0 R >>\n"
                   f"startxref\n{xref}\n%%EOF\n").encode("ascii"))
    return bytes(output)


def main() -> None:
    calls: list[str] = []

    def fetch(url: str, *, max_bytes: int):
        calls.append(url)
        return feed()

    records = parse_feed(feed())
    if (len(records) != 1 or records[0]["arxiv_id"] != "2601.01234v2"
            or records[0]["authors"] != "Ada Researcher, Grace Scientist"
            or records[0]["primary_category"] != "cs.AI"
            or records[0]["doi"] != "10.1234/example"):
        raise SystemExit(f"Atom metadata parsing failed: {records}")

    with tempfile.TemporaryDirectory(prefix="crms-arxiv-") as folder:
        db = Path(folder) / "research.sqlite"
        counts = import_arxiv("all:symbolic systems", db, fetch=fetch)
        if counts != (1, 0, 0):
            raise SystemExit(f"unexpected arXiv import counts: {counts}")
        parsed = parse_qs(urlsplit(calls[0]).query)
        if (urlsplit(calls[0]).scheme != "https"
                or urlsplit(calls[0]).netloc != "export.arxiv.org"
                or parsed.get("search_query") != ["all:symbolic systems"]
                or parsed.get("start") != ["0"]
                or parsed.get("max_results") != ["100"]):
            raise SystemExit(f"arXiv API request was not bounded correctly: {calls[0]}")
        index = CRMSSQLiteResearchIndex(db)
        try:
            hits = index.search("bounded proof search", limit=3)
            if not any(hit.document_id == "arxiv:2601.01234v2" for hit in hits):
                raise SystemExit("CC0 arXiv metadata abstract was not searchable")
            text = index.document("arxiv:2601.01234v2").text
            for value in ("Metadata license: CC0", "version: 2601.01234v2",
                          "Article license: not checked", "/abs/2601.01234v2",
                          "/pdf/2601.01234v2"):
                if value not in text:
                    raise SystemExit(f"indexed metadata lost {value!r}")
            if "Full text" in text:
                raise SystemExit("article full text was unexpectedly indexed")
        finally:
            index.close()
        again = import_arxiv(
            "all:symbolic systems", db, append=True,
            fetch=lambda _url, **_kwargs: feed())
        if again != (0, 1, 0):
            raise SystemExit("version-specific records did not deduplicate")

        # Explicit offsets let separate append runs acquire successive pages.
        page_calls: list[str] = []
        def paged_fetch(url: str, *, max_bytes: int):
            page_calls.append(url)
            if parse_qs(urlsplit(url).query).get("start") == ["1"]:
                return two_paper_feed()
            return feed()
        page_db = Path(folder) / "paged.sqlite"
        first_page = import_arxiv(
            "all:symbolic systems", page_db, start=0, max_results=1,
            fetch=paged_fetch)
        second_page = import_arxiv(
            "all:symbolic systems", page_db, start=1, max_results=1,
            append=True, fetch=paged_fetch)
        offsets = [parse_qs(urlsplit(url).query).get("start")
                   for url in page_calls]
        if first_page != (1, 0, 0) or second_page != (1, 1, 0) or offsets != [["0"], ["1"]]:
            raise SystemExit(f"arXiv offset paging failed: {first_page}, {second_page}, {offsets}")
        try:
            import_arxiv("all:symbolic systems", Path(folder) / "bad.sqlite",
                         start=-1, fetch=paged_fetch)
        except ValueError:
            pass
        else:
            raise SystemExit("negative arXiv page offset was accepted")

        valid_license = resolve_arxiv_license(
            oai_record(), "2601.01234v2")
        if valid_license["license_name"] != "CC BY":
            raise SystemExit(f"CC BY paper license was not recognized: {valid_license}")
        cc0 = resolve_arxiv_license(
            oai_record(license_uri=
                       "http://creativecommons.org/publicdomain/zero/1.0/"),
            "2601.01234v2")
        if cc0["license_name"] != "CC0":
            raise SystemExit(f"canonical CC0 paper license was not recognized: {cc0}")
        for uri in (
                "https://creativecommons.org/licenses/by-nc/4.0/",
                "https://creativecommons.org/licenses/by-sa/4.0/",
                "https://creativecommons.org/licenses/by/nd/4.0/",
                "https://creativecommons.org/licenses/by/99.0/",
                "https://creativecommons.org/publicdomain/",
                "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
                "ftp://creativecommons.org/licenses/by/4.0/"):
            if resolve_arxiv_license(oai_record(license_uri=uri),
                                     "2601.01234v2")["license_name"]:
                raise SystemExit(f"non-redistributable license was accepted: {uri}")
        try:
            resolve_arxiv_license(oai_record(version="v3"), "2601.01234v2")
        except ValueError as error:
            if "version changed" not in str(error):
                raise
        else:
            raise SystemExit("version-mismatched OAI metadata was accepted")

        upgraded = Path(folder) / "upgraded.sqlite"
        if import_arxiv("all:symbolic systems", upgraded,
                        fetch=lambda _url, **_kwargs: feed()) != (1, 0, 0):
            raise SystemExit("metadata-only source was not imported for upgrade")
        sleeps: list[float] = []
        oai_calls: list[str] = []

        def license_fetch(url: str, *, max_bytes: int):
            oai_calls.append(url)
            return oai_record()

        pdf_payload = sample_pdf()
        full_counts = import_arxiv(
            "all:symbolic systems", upgraded, append=True, full_text=True,
            fetch=lambda _url, **_kwargs: feed(), license_fetch=license_fetch,
            pdf_fetch=lambda _url, *, max_bytes: pdf_payload,
            sleep_fn=sleeps.append, request_delay=3)
        if full_counts != (1, 0, 0):
            raise SystemExit(f"licensed PDF did not upgrade metadata record: {full_counts}")
        if (len(oai_calls) != 1 or urlsplit(oai_calls[0]).netloc !=
                "oaipmh.arxiv.org"
                or parse_qs(urlsplit(oai_calls[0]).query).get("metadataPrefix") !=
                ["arXivRaw"] or sleeps):
            raise SystemExit(f"full-text license lookup was malformed or throttled incorrectly: {oai_calls}, {sleeps}")
        full_index = CRMSSQLiteResearchIndex(upgraded)
        try:
            document = full_index.document("arxiv:2601.01234v2")
            if (len(document.pages) != 2
                    or "Declared license: CC BY" not in document.pages[0]
                    or "Downloaded PDF SHA-256:" not in document.pages[0]):
                raise SystemExit("full-text attribution or page boundaries were lost")
            hit = full_index.search("distinctive arxiv fulltext evidence", limit=1)[0]
            if (hit.document_id != "arxiv:2601.01234v2" or hit.page_number != 2
                    or "&page=2" not in full_index.citation(hit)):
                raise SystemExit(f"full-text citation lost its source page: {hit}")
        finally:
            full_index.close()
        knowledge_path = Path(folder) / "knowledge.json"
        rules_path = Path(folder) / "rules.json"
        CRMSKnowledgeBase().save(knowledge_path)
        CRMSModel().save(rules_path)
        model_path = Path(folder) / "arxiv-model.sqlite"
        export_model_database(model_path, knowledge=knowledge_path,
                              rules=rules_path, research_index=upgraded)
        if not model_database_has_research(model_path):
            raise SystemExit("portable model omitted licensed arXiv source text")
        installed = install_model_database(
            model_path, Path(folder) / "installed-model")
        installed_index = CRMSSQLiteResearchIndex(installed["research_index"])
        try:
            model_hit = installed_index.search(
                "distinctive arxiv fulltext evidence", limit=1)
            if (not model_hit
                    or model_hit[0].document_id != "arxiv:2601.01234v2"
                    or model_hit[0].page_number != 2):
                raise SystemExit("installed model lost searchable arXiv text or page citation")
        finally:
            installed_index.close()
        duplicate_full = import_arxiv(
            "all:symbolic systems", upgraded, append=True, full_text=True,
            fetch=lambda _url, **_kwargs: feed(),
            license_fetch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("duplicate full text rechecked its license")))
        if duplicate_full != (0, 1, 0):
            raise SystemExit(f"full-text record did not deduplicate: {duplicate_full}")

        sweep_db = Path(folder) / "sweep.sqlite"
        if import_arxiv(
                "all:search", sweep_db,
                fetch=lambda _url, **_kwargs: two_paper_feed()) != (2, 0, 0):
            raise SystemExit("metadata records for the local sweep were not imported")
        sweep_oai_calls: list[str] = []
        sweep_pdf_calls: list[str] = []

        def sweep_license_fetch(url: str, *, max_bytes: int):
            sweep_oai_calls.append(url)
            base_id = parse_qs(urlsplit(url).query)["identifier"][0].removeprefix(
                "oai:arXiv.org:")
            if base_id == "2601.01234":
                return oai_record(
                    base_id=base_id,
                    license_uri="https://creativecommons.org/licenses/by-nc/4.0/")
            return oai_record(base_id=base_id, version="v1")

        def sweep_pdf_fetch(url: str, *, max_bytes: int):
            sweep_pdf_calls.append(url)
            return pdf_payload

        first_sweep = upgrade_existing_arxiv_full_text(
            sweep_db, max_records=1, request_delay=0,
            license_fetch=sweep_license_fetch, pdf_fetch=sweep_pdf_fetch,
            sleep_fn=lambda _seconds: None)
        second_sweep = upgrade_existing_arxiv_full_text(
            sweep_db, max_records=1, request_delay=0,
            license_fetch=sweep_license_fetch, pdf_fetch=sweep_pdf_fetch,
            sleep_fn=lambda _seconds: None)
        finished_sweep = upgrade_existing_arxiv_full_text(
            sweep_db, max_records=1, request_delay=0,
            license_fetch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("completed license sweep made another OAI request")),
            pdf_fetch=sweep_pdf_fetch, sleep_fn=lambda _seconds: None)
        if (first_sweep != (0, 0, 1) or second_sweep != (1, 0, 0)
                or finished_sweep != (0, 0, 0)
                or len(sweep_oai_calls) != 2 or len(sweep_pdf_calls) != 1):
            raise SystemExit(
                "bounded arXiv license sweep did not resume past a restricted paper: "
                f"{first_sweep}, {second_sweep}, {finished_sweep}, "
                f"OAI={len(sweep_oai_calls)}, PDF={len(sweep_pdf_calls)}")
        sweep_index = CRMSSQLiteResearchIndex(sweep_db)
        try:
            restricted_text = sweep_index.document("arxiv:2601.01234v2").text
            licensed_text = sweep_index.document("arxiv:2601.88888v1").text
            if ("Article license observed via OAI:" not in restricted_text
                    or "creativecommons.org/licenses/by-nc/4.0" not in restricted_text
                    or "Source: arXiv paper full text" not in licensed_text):
                raise SystemExit("resumed sweep lost license evidence or indexed text")
        finally:
            sweep_index.close()

        for suffix, license_payload in (
                ("restricted", oai_record(license_uri=
                  "https://creativecommons.org/licenses/by-nc/4.0/")),
                ("version-mismatch", oai_record(version="v3"))):
            gated = Path(folder) / f"{suffix}.sqlite"
            pdf_calls: list[str] = []
            result = import_arxiv(
                "all:symbolic systems", gated, full_text=True,
                fetch=lambda _url, **_kwargs: feed(),
                license_fetch=lambda _url, *, max_bytes: license_payload,
                pdf_fetch=lambda url, *, max_bytes: pdf_calls.append(url) or pdf_payload,
                request_delay=0)
            if result != (1, 0, 1) or pdf_calls:
                raise SystemExit(f"license/version gate allowed PDF acquisition: {suffix} {result}")
            gated_index = CRMSSQLiteResearchIndex(gated)
            try:
                gated_text = gated_index.document("arxiv:2601.01234v2").text
                if "Metadata license: CC0" not in gated_text or "Source: arXiv paper full text" in gated_text:
                    raise SystemExit(f"gated article text leaked into the index: {suffix}")
                if suffix == "restricted" and (
                        "Article license observed via OAI: "
                        "https://creativecommons.org/licenses/by-nc/4.0/" not in gated_text):
                    raise SystemExit("restricted license evidence was not retained")
                if suffix == "version-mismatch" and "not verified for the searched version" not in gated_text:
                    raise SystemExit("version-mismatch reason was not retained")
            finally:
                gated_index.close()

        failed_license_db = Path(folder) / "version-mismatch.sqlite"
        deferred_retry = upgrade_existing_arxiv_full_text(
            failed_license_db, max_records=1, request_delay=0,
            license_fetch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("prior OAI failure retried without opt-in")),
            pdf_fetch=lambda _url, **_kwargs: pdf_payload,
            sleep_fn=lambda _seconds: None)
        explicit_retry = upgrade_existing_arxiv_full_text(
            failed_license_db, max_records=1, retry_failed=True,
            request_delay=0,
            license_fetch=lambda _url, *, max_bytes: oai_record(),
            pdf_fetch=lambda _url, **_kwargs: pdf_payload,
            sleep_fn=lambda _seconds: None)
        if deferred_retry != (0, 0, 0) or explicit_retry != (1, 0, 0):
            raise SystemExit(
                f"failed license retry policy was not explicit: "
                f"{deferred_retry}, {explicit_retry}")

        pipeline_db = Path(folder) / "arxiv-learning.sqlite"

        def pipeline_license_fetch(url: str, *, max_bytes: int):
            params = parse_qs(urlsplit(url).query)
            base_id = params["identifier"][0].removeprefix("oai:arXiv.org:")
            version = "v2" if base_id == "2601.01234" else "v1"
            return oai_record(base_id=base_id, version=version)

        def pipeline_pdf_fetch(url: str, *, max_bytes: int):
            if "2601.01234v2" in url:
                return sample_pdf("Ada created Graph Atlas.")
            if "2601.88888v1" in url:
                return sample_pdf("Bea created Signal Atlas.")
            raise AssertionError(f"unexpected arXiv PDF URL: {url}")

        if import_arxiv(
                "all:search", pipeline_db, max_results=2, full_text=True,
                fetch=lambda _url, **_kwargs: two_paper_feed(),
                license_fetch=pipeline_license_fetch,
                pdf_fetch=pipeline_pdf_fetch, sleep_fn=lambda _seconds: None
                ) != (2, 0, 0):
            raise SystemExit("licensed paper corpus was not indexed")
        research = CRMSSQLiteResearchIndex(pipeline_db)
        try:
            learner = CRMSKnowledgeBase()
            if learner.facts():
                raise SystemExit("paper import wrote claims before review")
            proposals = learner.propose_corpus_relation_frames(research)
            proposal = next((item for item in proposals
                             if item["relation"] == "created"), None)
            if proposal is None or proposal["independent_documents"] < 2:
                raise SystemExit(f"paper corpus did not propose a repeated frame: {proposals}")
            learner.accept_corpus_relation_frame(proposal["proposal_id"], research)
            for question, expected in (
                    ("Who created Graph Atlas?", "Ada"),
                    ("Who created Signal Atlas?", "Bea")):
                answer = learner.ask(question)
                if answer.status != "answered" or answer.answer != expected:
                    raise SystemExit(f"accepted paper frame did not answer {question}: {answer}")
                citations = {source for evidence in answer.evidence or []
                             for source in evidence.get("sources", [])}
                if not any(source.startswith("arxiv:") and "page=2" in source
                           for source in citations):
                    raise SystemExit(f"paper-derived answer lost page citation: {answer}")
            if len(learner.facts()) != 2:
                raise SystemExit("paper-derived frame acceptance stored unexpected facts")
        finally:
            research.close()

    try:
        parse_feed(b"<feed><entry><title>bad</title></entry></feed>")
    except ValueError:
        pass
    else:
        raise SystemExit("malformed Atom namespace was accepted")
    print("arXiv metadata and licensed full-text import diagnostic: PASS")
    print("bounded Atom search, CC0 metadata, exact-version OAI license lookup, CC0/CC BY allowlist, restricted-license/version rejection, metadata upgrade, PDF attribution/page citations, corpus-frame induction from separate papers, portable SQLite model round-trip, and append deduplication: PASS")


if __name__ == "__main__":
    main()
