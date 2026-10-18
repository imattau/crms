"""Check disk-backed local corpus ingestion, retrieval, and exact citations."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import os
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_research import CRMSSQLiteResearchIndex
from experiments.v1_31_pdf_source_retrieval import make_pdf

PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-local-corpus-") as folder:
        root = Path(folder)
        corpus = root / "library"
        corpus.mkdir()
        nested = corpus / "manuals"
        nested.mkdir()
        for number in range(600):
            directory = corpus if number % 2 else nested
            (directory / f"document-{number:04}.txt").write_text(
                f"Local reference {number} describes ordinary material. "
                + ("Rarezeugma device 457 stores a calibrated measurement. "
                   if number == 457 else "General notes cover routine work. ")
                + f"Record number {number} remains part of the local library.",
                encoding="utf-8")
        (corpus / "architecture.md").write_text(
            "# Local architecture\n\nThe Quillforge index preserves exact citations.",
            encoding="utf-8")
        (corpus / "reference.rst").write_text(
            "Reference notes\n===============\n\nThe Vellum codec stores page offsets.",
            encoding="utf-8")
        (corpus / "long-reference.txt").write_text(
            ("general " * 900)
            + "The Zephyrion reactor uses a ceramic containment lattice.",
            encoding="utf-8")
        (corpus / "index.html").write_text(
            "<html><head><title>Helio index</title><script>hidden token</script>"
            "</head><body><h1>Helio archive</h1><p>The archive retains"
            " crystalline records.</p></body></html>", encoding="utf-8")
        docx_path = corpus / "maintenance.docx"
        with zipfile.ZipFile(docx_path, "w") as document:
            document.writestr(
                "word/document.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="urn:word"><w:body>'
                '<w:p><w:r><w:t>The Morrowstone gearbox requires '
                '0.25 mm clearance.</w:t></w:r></w:p>'
                '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Inspection cycle: '
                '120 hours.</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                '</w:body></w:document>')
            document.writestr(
                "docProps/core.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<cp:coreProperties xmlns:cp="urn:core" '
                'xmlns:dc="urn:dc"><dc:title>Gearbox Maintenance</dc:title>'
                '</cp:coreProperties>')
        odt_path = corpus / "maintenance.odt"
        with zipfile.ZipFile(odt_path, "w") as document:
            document.writestr("mimetype", "application/vnd.oasis.opendocument.text",
                              compress_type=zipfile.ZIP_STORED)
            document.writestr(
                "content.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<office:document-content xmlns:office="urn:office" '
                'xmlns:text="urn:text" xmlns:table="urn:table">'
                '<office:body><office:text><text:h>Airframe inspection</text:h>'
                '<text:p>The Kestrelion actuator requires two<text:s text:c="2"/>'
                'mounting bolts.</text:p><table:table><table:table-row>'
                '<table:table-cell><text:p>Inspection interval: 240 hours.'
                '</text:p></table:table-cell></table:table-row></table:table>'
                '</office:text></office:body></office:document-content>')
            document.writestr(
                "meta.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<office:document-meta xmlns:office="urn:office" '
                'xmlns:dc="urn:dc"><office:meta>'
                '<dc:title>Airframe Service Notes</dc:title>'
                '</office:meta></office:document-meta>')
        chat_export = {
            "title": "Propulsion Design Review",
            "current_node": "assistant-final-2",
            "mapping": {
                "system": {"parent": None, "message": {
                    "author": {"role": "system"},
                    "content": {"parts": ["internal preamble should be omitted"]}}},
                "user-1": {"parent": "system", "message": {
                    "author": {"role": "user"},
                    "content": {"parts": ["What clearance does the pump need?"]}}},
                "analysis": {"parent": "user-1", "message": {
                    "author": {"role": "assistant"},
                    "metadata": {"channel": "analysis"},
                    "content": {"parts": ["private reasoning should be omitted"]}}},
                "assistant-final-1": {"parent": "user-1", "message": {
                    "author": {"role": "assistant"},
                    "metadata": {"channel": "final"},
                    "content": {"parts": [
                        "The Thistledown pump uses a 17 mm ceramic sleeve."]}}},
                "alternate": {"parent": "user-1", "message": {
                    "author": {"role": "assistant"},
                    "content": {"parts": ["unselected branch should be omitted"]}}},
                "user-2": {"parent": "assistant-final-1", "message": {
                    "author": {"role": "user"},
                    "content": {"parts": ["Is the sleeve metallic?"]}}},
                "assistant-final-2": {"parent": "user-2", "message": {
                    "author": {"role": "assistant"},
                    "content": {"parts": ["No, it is ceramic."]}}},
            },
        }
        (corpus / "conversations.json").write_text(
            json.dumps([chat_export]), encoding="utf-8")
        (corpus / "unrelated.json").write_text(
            '{"configuration": "not a chat export"}', encoding="utf-8")
        (corpus / "calibration.csv").write_text(
            "\ufeffunit,range,material\n"
            "Thornvale sensor,0-18 kPa,borosilicate\n",
            encoding="utf-8")
        (corpus / "inspection.tsv").write_text(
            "assembly\tinterval\tstandard\n"
            "Windmere coupling\t360 hours\tISO-9421\n",
            encoding="utf-8")
        xlsx_path = corpus / "test-bench.xlsx"
        with zipfile.ZipFile(xlsx_path, "w") as workbook:
            workbook.writestr(
                "xl/workbook.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<workbook xmlns:r="urn:relationships"><sheets>'
                '<sheet name="Test Bench" sheetId="1" r:id="rId1"/>'
                '</sheets></workbook>')
            workbook.writestr(
                "xl/_rels/workbook.xml.rels",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships><Relationship Id="rId1" '
                'Target="worksheets/sheet1.xml"/></Relationships>')
            workbook.writestr(
                "xl/sharedStrings.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<sst><si><t>Instrument</t></si><si><t>Capacity</t></si>'
                '<si><t>Application</t></si><si><t>Sablethorn pump</t></si>'
                '<si><t>840 L/min</t></si><si><t>coolant loop</t></si></sst>')
            workbook.writestr(
                "xl/worksheets/sheet1.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet><sheetData><row r="1">'
                '<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
                '<c r="C1" t="s"><v>2</v></c></row><row r="2">'
                '<c r="A2" t="s"><v>3</v></c><c r="B2" t="s"><v>4</v></c>'
                '<c r="C2" t="s"><v>5</v></c></row></sheetData></worksheet>')
            workbook.writestr(
                "docProps/core.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<cp:coreProperties xmlns:cp="urn:core" '
                'xmlns:dc="urn:dc"><dc:title>Fluid Test Matrix</dc:title>'
                '</cp:coreProperties>')
        pptx_path = corpus / "validation-deck.pptx"
        with zipfile.ZipFile(pptx_path, "w") as presentation:
            presentation.writestr(
                "ppt/presentation.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<p:presentation xmlns:p="urn:presentation" '
                'xmlns:r="urn:relationships"><p:sldIdLst>'
                '<p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>')
            presentation.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships><Relationship Id="rId1" '
                'Target="slides/slide1.xml"/></Relationships>')
            presentation.writestr(
                "ppt/slides/slide1.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<p:sld xmlns:p="urn:presentation" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/><a:lstStyle/>'
                '<a:p><a:r><a:t>Rotor validation</a:t></a:r></a:p>'
                '<a:p><a:r><a:t>Starlingpoint turbine stalls at 3100 rpm.'
                '</a:t></a:r></a:p><a:p><a:r><a:t>Blade balancing threshold: '
                '0.8 mm.</a:t></a:r></a:p></p:txBody></p:sp>'
                '</p:spTree></p:cSld></p:sld>')
            presentation.writestr(
                "docProps/core.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<cp:coreProperties xmlns:cp="urn:core" '
                'xmlns:dc="urn:dc"><dc:title>Rotor Qualification</dc:title>'
                '</cp:coreProperties>')
        epub_path = corpus / "reference.epub"
        with zipfile.ZipFile(epub_path, "w") as epub:
            epub.writestr("mimetype", "application/epub+zip",
                          compress_type=zipfile.ZIP_STORED)
            epub.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container><rootfiles>'
                '<rootfile full-path="OPS/package.opf"/>'
                '</rootfiles></container>')
            epub.writestr(
                "OPS/package.opf",
                '<?xml version="1.0"?><package><metadata>'
                '<dc:title xmlns:dc="urn:dc">The Local Atlas</dc:title>'
                '</metadata><manifest><item id="c1" href="chapter1.xhtml" '
                'media-type="application/xhtml+xml"/><item id="c2" '
                'href="chapter2.xhtml" media-type="application/xhtml+xml"/>'
                '</manifest><spine><itemref idref="c2"/><itemref idref="c1"/>'
                '</spine></package>')
            epub.writestr(
                "OPS/chapter1.xhtml",
                "<html><head><script>hidden scriptterm</script></head>"
                "<body><p>Second chapter explains the Quartzwell engine.</p>"
                "</body></html>")
            epub.writestr(
                "OPS/chapter2.xhtml",
                "<html><body><p>First chapter describes the Larkspur archive.</p>"
                "</body></html>")
        (corpus / "broken.epub").write_bytes(b"not a valid EPUB archive")
        (corpus / "ignore.xml").write_text(
            "This file type is intentionally outside corpus ingestion.", encoding="utf-8")
        (corpus / "manual.pdf").write_bytes(make_pdf([
            "First page contains a general statement.",
            "Second page records an exact local finding."]))

        database = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(database)
        write_trace: list[str] = []
        index._db.set_trace_callback(write_trace.append)
        ingested = index.add_directory(corpus)
        index._db.set_trace_callback(None)
        require(len(ingested.added) == 613 and len(ingested.failures) == 1
                and ingested.failures[0][0].endswith("broken.epub"),
                "recursive corpus ingestion failed: "
                f"added={len(ingested.added)}, failures={ingested.failures}")
        require(sum(statement.strip().upper() == "BEGIN"
                    for statement in write_trace) == 3
                and sum(statement.strip().upper() == "COMMIT"
                        for statement in write_trace) == 3,
                "directory ingestion did not commit bounded SQLite batches")
        repeated = index.add_directory(corpus)
        require(not repeated.added and len(repeated.skipped) == 613
                and len(repeated.failures) == 1,
                f"repeated ingestion was not idempotent: {repeated}")
        require(index.document_count() == 613,
                "SQLite corpus count did not match indexed files")
        corpus_count, corpus_bytes = index.corpus_stats()
        require(corpus_count == 613 and corpus_bytes > 20_000
                and len(index.source_list(limit=25, offset=25)) == 25,
                "disk-backed corpus inventory or paging failed")
        long_hit = index.search("Zephyrion reactor containment lattice", limit=1)[0]
        long_id = str((corpus / "long-reference.txt").resolve())
        chunk_count = index._db.execute(
            "SELECT count(*) FROM source_chunks WHERE document_id=?",
            (long_id,)).fetchone()[0]
        require(long_hit.document_id == long_id and long_hit.start > 1000
                and chunk_count == 3
                and "Zephyrion" in index.resolve_citation(
                    index.citation(long_hit)),
                f"long-document chunk retrieval lost its localized exact citation: "
                f"hit={long_hit}, chunks={chunk_count}")
        markdown_hit = index.search("Quillforge exact citations", limit=1)[0]
        require(markdown_hit.document_id.endswith("architecture.md")
                and "Quillforge" in index.resolve_citation(
                    index.citation(markdown_hit)),
                "Markdown retrieval lost its exact citation")
        rst_hit = index.search("Vellum codec page offsets", limit=1)[0]
        require(rst_hit.document_id.endswith("reference.rst")
                and "Vellum" in index.resolve_citation(index.citation(rst_hit)),
                "reStructuredText retrieval lost its exact citation")
        html_hit = index.search("Helio crystalline records", limit=1)[0]
        require(html_hit.document_id.endswith("index.html")
                and html_hit.title == "Helio index"
                and "hidden" not in index.document(html_hit.document_id).text,
                f"HTML extraction retained hidden content or lost visible text: "
                f"{html_hit}; {index.document(html_hit.document_id)}")
        docx_hit = index.search("Morrowstone gearbox clearance", limit=1)[0]
        docx_doc = index.document(docx_hit.document_id)
        require(docx_hit.document_id.endswith("maintenance.docx")
                and docx_doc.title == "Gearbox Maintenance"
                and "Inspection cycle: 120 hours." in docx_doc.text
                and index.resolve_citation(index.citation(docx_hit))
                == docx_hit.snippet,
                f"DOCX body, table text, title, or citations failed: "
                f"{docx_hit}; {docx_doc}")
        odt_hit = index.search("Kestrelion actuator mounting bolts", limit=1)[0]
        odt_doc = index.document(odt_hit.document_id)
        require(odt_hit.document_id.endswith("maintenance.odt")
                and odt_doc.title == "Airframe Service Notes"
                and "requires two  mounting bolts" in odt_doc.text
                and "Inspection interval: 240 hours." in odt_doc.text
                and index.resolve_citation(index.citation(odt_hit))
                == odt_hit.snippet,
                f"ODT paragraph spacing, table, title, or citation failed: "
                f"{odt_hit}; {odt_doc}")
        chat_hit = index.search("Thistledown pump ceramic sleeve", limit=1)[0]
        chat_doc = index.document(chat_hit.document_id)
        require(chat_hit.document_id.endswith("conversations.json")
                and chat_doc.title == "Propulsion Design Review"
                and "What clearance does the pump need?" in chat_doc.text
                and "The Thistledown pump uses a 17 mm ceramic sleeve." in chat_doc.text
                and "internal preamble" not in chat_doc.text
                and "private reasoning" not in chat_doc.text
                and "unselected branch" not in chat_doc.text
                and index.resolve_citation(index.citation(chat_hit))
                == chat_hit.snippet,
                f"ChatGPT conversation extraction or citation failed: "
                f"{chat_hit}; {chat_doc}")
        csv_hit = index.search("Thornvale sensor borosilicate", limit=1)[0]
        csv_doc = index.document(csv_hit.document_id)
        require(csv_hit.document_id.endswith("calibration.csv")
                and csv_doc.text.startswith("unit,range,material\n")
                and "0-18 kPa" in index.resolve_citation(index.citation(csv_hit)),
                f"CSV BOM handling, retrieval, or citation failed: {csv_hit}")
        tsv_hit = index.search("Windmere coupling ISO-9421", limit=1)[0]
        tsv_doc = index.document(tsv_hit.document_id)
        require(tsv_hit.document_id.endswith("inspection.tsv")
                and "Windmere coupling\t360 hours\tISO-9421"
                in index.resolve_citation(index.citation(tsv_hit)),
                f"TSV retrieval or citation failed: {tsv_hit}")
        workbook_hit = index.search("Sablethorn pump coolant loop", limit=1)[0]
        workbook_doc = index.document(workbook_hit.document_id)
        require(workbook_hit.document_id.endswith("test-bench.xlsx")
                and workbook_doc.title == "Fluid Test Matrix"
                and "Sheet: Test Bench" in workbook_doc.text
                and "Instrument: Sablethorn pump" in workbook_doc.text
                and "Capacity: 840 L/min" in workbook_doc.text
                and index.resolve_citation(index.citation(workbook_hit))
                == workbook_hit.snippet,
                f"XLSX sheet, header, cell value, title, or citation failed: "
                f"{workbook_hit}; {workbook_doc}")
        presentation_hit = index.search(
            "Starlingpoint turbine stalls 3100 rpm", limit=1)[0]
        presentation_doc = index.document(presentation_hit.document_id)
        require(presentation_hit.document_id.endswith("validation-deck.pptx")
                and presentation_doc.title == "Rotor Qualification"
                and "Slide 1: Rotor validation" in presentation_doc.text
                and "Blade balancing threshold: 0.8 mm." in presentation_doc.text
                and index.resolve_citation(index.citation(presentation_hit))
                == presentation_hit.snippet,
                f"PPTX slide text, title, table content, or citation failed: "
                f"{presentation_hit}; {presentation_doc}")
        epub_hit = index.search("Quartzwell engine", limit=1)[0]
        epub_doc = index.document(epub_hit.document_id)
        require(epub_hit.document_id.endswith("reference.epub")
                and epub_doc.title == "The Local Atlas"
                and epub_doc.text.index("Larkspur") < epub_doc.text.index("Quartzwell")
                and "scriptterm" not in epub_doc.text
                and index.resolve_citation(index.citation(epub_hit)) == epub_hit.snippet,
                "EPUB metadata, spine order, hidden-content filtering, or citations failed")
        hits = index.search("Rarezeugma device calibrated measurement", limit=5)
        require(hits and hits[0].document_id.endswith("document-0457.txt"),
                f"rare local knowledge was not retrieved: {hits}")
        citation = index.citation(hits[0])
        excerpt = index.resolve_citation(citation)
        require(excerpt == hits[0].snippet and "Rarezeugma" in excerpt,
                "SQLite citation did not resolve to its exact local source span")
        summary = index.summarize("Rarezeugma calibrated measurement", limit=2)
        require(summary.sentences
                and "Rarezeugma device 457" in summary.sentences[0].text
                and "sha256=" in summary.render(),
                "disk-backed summary lost exact source wording or citation")
        page_hit = index.search("exact local finding", limit=1)[0]
        page_citation = index.citation(page_hit)
        require(page_hit.page_number == 2
                and "&page=2&match=" in page_citation
                and index.resolve_citation(page_citation) == page_hit.snippet,
                "disk-backed page citations lost page or exact-offset validation")
        document_id = hits[0].document_id
        index.close()

        restored = CRMSSQLiteResearchIndex.load(database)
        restored_hits = restored.search("Rarezeugma device calibrated measurement")
        require(restored_hits and restored_hits[0].document_id == document_id
                and restored.resolve_citation(citation) == excerpt,
                "SQLite search or citation did not survive process-style reopen")
        changed_source = Path(document_id)
        changed_source.write_text(
            "Replacement source now documents a distinct revised calibration protocol.",
            encoding="utf-8")
        refreshed = restored.add_directory(corpus)
        require(refreshed.added == (document_id,)
                and len(refreshed.skipped) == 612
                and len(refreshed.failures) == 1,
                f"incremental directory refresh touched the wrong files: {refreshed}")
        refreshed_hits = restored.search("revised calibration protocol", limit=1)
        require(refreshed_hits and refreshed_hits[0].document_id == document_id,
                "changed local source was not reindexed")
        refreshed_citation = restored.citation(refreshed_hits[0])
        prior_stat = changed_source.stat()
        changed_source.write_text(
            changed_source.read_text(encoding="utf-8").replace(
                "revised calibration", "updated calibration"),
            encoding="utf-8")
        os.utime(changed_source,
                 ns=(prior_stat.st_atime_ns, prior_stat.st_mtime_ns))
        metadata_only = restored.add_directory(corpus)
        require(document_id in metadata_only.skipped
                and document_id not in metadata_only.added,
                "metadata-only scan did not preserve its documented fast path")
        verified = restored.add_directory(corpus, verify_content=True)
        require(verified.added == (document_id,)
                and len(verified.skipped) == 612
                and len(verified.failures) == 1,
                f"content verification missed a same-metadata edit: {verified}")
        verified_hits = restored.search("updated calibration protocol", limit=1)
        require(verified_hits and verified_hits[0].document_id == document_id,
                "content verification did not refresh the indexed source")
        try:
            restored.resolve_citation(refreshed_citation)
        except ValueError as error:
            require("different source revision" in str(error),
                    f"stale citation failed for the wrong reason: {error}")
        else:
            raise SystemExit("stale local citation survived source replacement")
        restored.close()

        legacy_database = root / "legacy-v1.sqlite"
        legacy_body = "The Sable quasar emits a measurable radio pulse."
        legacy_connection = sqlite3.connect(legacy_database)
        legacy_connection.executescript(
            "CREATE TABLE corpus_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO corpus_meta VALUES ('schema_version','1');"
            "CREATE TABLE source_documents ("
            "document_id TEXT PRIMARY KEY,title TEXT NOT NULL,location TEXT,"
            "body TEXT NOT NULL,pages_json TEXT NOT NULL,sha256 TEXT NOT NULL);"
            "CREATE TABLE source_file_state ("
            "document_id TEXT PRIMARY KEY,size_bytes INTEGER NOT NULL,"
            "mtime_ns INTEGER NOT NULL);"
            "CREATE VIRTUAL TABLE source_fts USING fts5("
            "document_id UNINDEXED,title,body,tokenize='unicode61');")
        legacy_connection.execute(
            "INSERT INTO source_documents VALUES(?,?,?,?,?,?)",
            ("legacy-doc", "Legacy astronomy", None, legacy_body, "[]",
             hashlib.sha256(legacy_body.encode()).hexdigest()))
        legacy_connection.execute(
            "INSERT INTO source_fts(document_id,title,body) VALUES(?,?,?)",
            ("legacy-doc", "Legacy astronomy", legacy_body))
        legacy_connection.commit()
        legacy_connection.close()
        migrated = CRMSSQLiteResearchIndex(legacy_database)
        migrated_hits = migrated.search("Sable quasar radio pulse", limit=1)
        require(migrated_hits and migrated_hits[0].document_id == "legacy-doc"
                and migrated.resolve_citation(
                    migrated.citation(migrated_hits[0])) == migrated_hits[0].snippet
                and migrated._db.execute(
                    "SELECT value FROM corpus_meta WHERE key='schema_version'"
                ).fetchone()[0] == "2",
                "SQLite schema migration did not rebuild chunked retrieval")
        migrated.close()

        cli_corpus = root / "cli-library"
        cli_corpus.mkdir()
        (cli_corpus / "notes.txt").write_text(
            "The Lumen instrument measured ice grains. "
            "The instrument returned its results to the local archive.",
            encoding="utf-8")
        (cli_corpus / "manual.md").write_text(
            "# Instrument manual\n\nThe Lumen instrument stores a service log.",
            encoding="utf-8")
        cli_index = root / "cli.sqlite"
        run = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--index", str(cli_index),
             "--knowledge", str(root / "knowledge.json"),
             "--dialogue-state", str(root / "dialogue.json")],
            input=(f"/source-dir {cli_corpus}\n"
                   "Could you please summarize the Lumen instrument?\n"
                   "/sources\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=30)
        require(run.returncode == 0
                and "Indexed 2 source file(s)" in run.stdout
                and "The Lumen instrument measured ice grains." in run.stdout
                and "sha256=" in run.stdout
                and "Local corpus: 2 source document(s)" in run.stdout
                and "notes.txt" in run.stdout,
                f"terminal local corpus workflow failed:\n{run.stdout}\n{run.stderr}")
        verify_run = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--index", str(cli_index),
             "--knowledge", str(root / "knowledge.json"),
             "--dialogue-state", str(root / "dialogue.json")],
            input=f"/source-dir {cli_corpus} --verify\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=30)
        require(verify_run.returncode == 0
                and "Indexed 0 source file(s)" in verify_run.stdout
                and "skipped 2 existing file(s)" in verify_run.stdout,
                f"terminal source verification command failed:\n"
                f"{verify_run.stdout}\n{verify_run.stderr}")

    print("SQLite local corpus diagnostic: PASS")
    print("613-file recursive ingestion (including Markdown, tables, slides, HTML, DOCX, ODT, chats, EPUB, and PDF), idempotence, retrieval, "
          "extractive summary, "
          "exact/stale citation handling, v1-to-v2 migration, persistence, "
          "and CLI routing: PASS")


if __name__ == "__main__":
    main()
