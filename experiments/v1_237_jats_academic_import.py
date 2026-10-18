"""Runtime diagnostic for license-aware JATS import and retrieval."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_import_jats import import_corpus
from crms_chat import _render_main_result
from crms_package import export_model_database, model_database_has_research
from crms_research import CRMSSQLiteResearchIndex
import sqlite3


def article(license_href: str, license_text: str, pmcid: str, phrase: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
<article-id pub-id-type="pmc">{pmcid}</article-id>
<article-id pub-id-type="doi">10.1234/{pmcid.lower()}</article-id>
<title-group><article-title>Rules of {phrase}</article-title></title-group>
<contrib-group><contrib contrib-type="author"><string-name>Ada Author</string-name></contrib></contrib-group>
<abstract><p>We demonstrate that {phrase} improves source matching.</p></abstract>
<permissions><license xlink:href="{license_href}"><license-p>{license_text}</license-p></license></permissions>
</article-meta></front><body><sec><title>Finding</title><p>Distinctive finding: {phrase} changes the observed result.</p></sec></body></article>'''


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-jats-") as temporary:
        root = Path(temporary)
        corpus = root / "papers"
        corpus.mkdir()
        (corpus / "ccby.xml").write_text(article(
            "https://creativecommons.org/licenses/by/4.0/", "CC BY 4.0", "PMC111", "orbital retrieval"), encoding="utf-8")
        (corpus / "cc0.xml").write_text(article(
            "https://creativecommons.org/publicdomain/zero/1.0/", "CC0 1.0", "PMC222", "symbolic grammar"), encoding="utf-8")
        (corpus / "nc.xml").write_text(article(
            "https://creativecommons.org/licenses/by-nc/4.0/", "CC BY-NC 4.0", "PMC333", "restricted material"), encoding="utf-8")
        (corpus / "nd.xml").write_text(article(
            "https://creativecommons.org/licenses/by-nd/4.0/", "CC BY-ND 4.0", "PMC444", "no derivative material"), encoding="utf-8")
        (corpus / "unlicensed.xml").write_text(article("", "All rights reserved", "PMC555", "copyright material"), encoding="utf-8")
        (corpus / "broken.xml").write_text("<article>", encoding="utf-8")
        output = root / "papers.sqlite"
        accepted, skipped, errors = import_corpus(corpus, output)
        assert (accepted, skipped, errors) == (2, 3, 1)
        index = CRMSSQLiteResearchIndex(output)
        hits = index.search("Distinctive orbital retrieval", limit=5)
        assert (hits and "orbital" in hits[0].snippet
                and "retrieval" in hits[0].snippet
                and hits[0].snippet.rstrip().endswith("."))
        assert "10.1234/pmc111" in hits[0].location
        documents = index.documents()
        assert len(documents) == 2
        stored = next(document.text for document in documents
                      if document.document_id == "jats:PMC111")
        assert "CC BY: CC BY 4.0" in stored and "Ada Author" in stored
        assert "Abstract: We demonstrate that orbital retrieval improves source matching." in stored
        result_text, result_evidence = _render_main_result(
            index, "'Rules of orbital retrieval'")
        assert "We demonstrate that orbital retrieval improves source matching." in result_text
        assert result_evidence is not None and "chars=" in result_evidence["citation"]
        index.close()
        knowledge = root / "knowledge.json"
        rules = root / "rules.json"
        knowledge.write_text("[]", encoding="utf-8")
        rules.write_text("[]", encoding="utf-8")
        model = root / "model.sqlite"
        export_model_database(model, knowledge=knowledge, rules=rules,
                              research_index=output)
        assert model_database_has_research(model)
        with sqlite3.connect(model) as db:
            packaged = db.execute(
                "SELECT body FROM research_documents WHERE document_id='jats:PMC111'").fetchone()[0]
        assert "Distinctive finding: orbital retrieval" in packaged
        assert "CC BY: CC BY 4.0" in packaged
        print("JATS academic import diagnostic: PASS")
        print("CC0/CC BY allowlist, NC/ND/all-rights-reserved exclusion, malformed XML handling, attribution, DOI provenance, searchable citations, and portable model bundling: PASS")


if __name__ == "__main__":
    main()
