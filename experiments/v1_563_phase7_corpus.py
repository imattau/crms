"""Phase 7 contract: manifest audit, filters, sharding, citations, abstention."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_corpus_program import (  # noqa: E402
    CorpusBuilder, CorpusReader, _shingle_sketch, audit_licence,
    clean_text, detect_language, detect_script, scan_sensitive, simhash64,
)
from crms_phase7_benchmark import evaluate, load_fixture  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


ALPHA = (
    "Alpha beta gamma describe a compact source passage used by the corpus "
    "contract. The passage contains enough ordinary words for retrieval and "
    "for a complete sentence citation. Alpha beta gamma also exercise the "
    "sharded index, the exact offset reference, and the abstention boundary. "
    "A second sentence keeps the document above the minimum word count and "
    "gives the ranker more than one chance to select a complete sentence. "
    "The final sentence repeats no expected answer but keeps the text stable. "
)
NEAR = ALPHA.replace("contract", "contracts")


def unit_contracts() -> None:
    cleaned, info = clean_text(
        "Title\n\nRetrieved from https://example.invalid\n"
        "This page was last changed on 1 January 2026.\n"
        "Kept sentence with useful content.\n",
        "crms-project")
    require("Kept sentence" in cleaned, "cleaning removed useful text")
    require("Retrieved from" not in cleaned, "cleaning kept boilerplate")
    require(info["boilerplate_removed"] >= 1, "boilerplate count is missing")

    redacted, findings, reason = scan_sensitive(
        "Contact person@example.org for a copy.")
    require(not reason and "[email]" in redacted and findings["email"] == 1,
            "email redaction failed")
    _, _, reason = scan_sensitive(
        "-----BEGIN RSA PRIVATE KEY-----\nsecret\n"
        "-----END RSA PRIVATE KEY-----")
    require(bool(reason), "private key was not rejected")

    require(detect_script("Plain English text") == "latin",
            "Latin script detection failed")
    require(detect_language("The source and the document are in the index")[0]
            == "en", "English language detection failed")
    require(simhash64(ALPHA) == simhash64(ALPHA), "SimHash is not stable")
    require(len(_shingle_sketch(ALPHA)) > 0, "shingle sketch is empty")

    accepted = audit_licence(
        "project:test.md", "CRMS project file: test.md", "Some text.")
    require(accepted.accepted and accepted.licence_class == "permissive",
            f"MIT source failed audit: {accepted.errors}")
    rejected = audit_licence(
        "conversation:test", "User attachment", "Some text.")
    require(not rejected.accepted, "unknown user text passed the licence audit")
    require(rejected.licence_class == "unknown",
            "unknown user text did not retain its class")


def build_and_read() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-phase7-test-") as temporary:
        output = Path(temporary) / "corpus"
        builder = CorpusBuilder(
            output, shards=2, holdout_ids=("project:heldout.md",))
        try:
            require(builder.add("project:alpha.md", "Alpha", ALPHA,
                                "CRMS project file: alpha.md") == "accepted",
                    "alpha document was not accepted")
            require(builder.add("project:near.md", "Near", NEAR,
                                "CRMS project file: near.md")
                    .startswith("duplicate_"),
                    "near duplicate was not rejected")
            require(builder.add("project:alpha-copy.md", "Copy", ALPHA,
                                "CRMS project file: alpha-copy.md")
                    .startswith("duplicate_"),
                    "exact duplicate was not rejected")
            pii_text = (
                "Contact records are retained only as redacted source text. "
                "The office address is deliberately different from the first "
                "passage so that deduplication does not hide the redaction "
                "test. Write to person@example.org for a copy of the policy. "
                "A telephone number such as 555-123-4567 and a social security "
                "number such as 123-45-6789 must also be removed. The rest of "
                "this paragraph keeps the document above the minimum length "
                "and supplies ordinary words for retrieval. It does not repeat "
                "the expected answer from any other synthetic document. The "
                "final sentence confirms that the cleaned text remains useful."
            )
            require(builder.add("project:pii.md", "Contact", pii_text,
                                "CRMS project file: pii.md") == "accepted",
                    "PII-bearing document was not accepted with redaction")
            require(builder.add("project:secret.md", "Secret",
                                ALPHA + " -----BEGIN RSA PRIVATE KEY-----",
                                "CRMS project file: secret.md")
                    == "sensitive_content",
                    "credential-bearing document was not rejected")
            require(builder.add("conversation:note", "Note", ALPHA,
                                "User attachment") == "licence_audit",
                    "unlicensed user note was not rejected")
            require(builder.add("project:heldout.md", "Held out", ALPHA,
                                "CRMS project file: heldout.md") == "held_out",
                    "held-out document was not excluded")
        finally:
            summary = builder.close()
        require(summary["documents"] == 2, "unexpected accepted document count")
        require(summary["licence_coverage"]["coverage"] == 1.0,
                "accepted corpus has incomplete licence coverage")
        require(summary["rejected_reasons"].get("duplicate_near") == 1,
                "near-duplicate count is wrong")
        require(summary["rejected_reasons"].get("duplicate_exact") == 1,
                "exact-duplicate count is wrong")
        require(summary["rejected_reasons"].get("sensitive_content") == 1,
                "sensitive-content count is wrong")
        require(summary["rejected_reasons"].get("licence_audit") == 1,
                "licence rejection count is wrong")
        require(summary["rejected_reasons"].get("held_out") == 1,
                "holdout rejection count is wrong")

        reader = CorpusReader(output)
        try:
            require(reader.document_count == 2, "reader count is wrong")
            require(not reader.contains_document("project:heldout.md"),
                    "reader exposed a held-out document")
            pii = reader.document("project:pii.md")
            require("[email]" in pii.text,
                    "reader returned unredacted PII")
            manifest = reader.manifest("project:alpha.md")
            require(manifest["licence_class"] == "permissive"
                    and manifest["revision"]
                    and manifest["attribution"]
                    and manifest["retrieval"]
                    == "local repository",
                    f"manifest is incomplete: {manifest}")
            result = reader.answer_question(
                "What does alpha beta gamma describe?")
            require(result["status"] == "answered",
                    f"grounded answer abstained: {result}")
            resolved = reader.resolve_citation(result["citation"])
            require("alpha" in resolved.casefold()
                    and "beta" in resolved.casefold()
                    and "gamma" in resolved.casefold(),
                    "citation does not resolve to the answer passage")
            absent = reader.answer_question(
                "What is the capital city of Atlantis?")
            require(absent["status"] == "abstained",
                    f"absent entity was answered: {absent}")
            hits = reader.search("alpha beta gamma", limit=3)
            require(len(hits) == 1,
                    "sharded search returned duplicate or missing documents")
        finally:
            reader.close()


def fixture_contracts() -> None:
    fixture = load_fixture(
        PROJECT / "corpus" / "phase7_eval" / "fixture.json")
    require(len(fixture["tasks"]) == 39,
            f"unexpected positive task count: {len(fixture['tasks'])}")
    require(len(fixture["negative_controls"]) == 10,
            "unexpected negative control count")
    require(len(fixture["evaluation_documents"]) == 39,
            "unexpected held-out document count")
    domains = {task["domain"] for task in fixture["tasks"]}
    require({"reference", "science", "math", "code", "docs", "research"}
            <= domains, f"fixture is missing a domain: {domains}")
    for document in fixture["evaluation_documents"]:
        require(len(document["sha256"]) == 64,
                "held-out document is not content-addressed")
    require(evaluate.__name__ == "evaluate", "benchmark import failed")


def main() -> None:
    unit_contracts()
    build_and_read()
    fixture_contracts()
    print("licence audit, cleaning, PII, language, and script filters: PASS")
    print("exact and near deduplication, optional holdout exclusion: PASS")
    print("sharded FTS search, manifest fields, and citation verification: PASS")
    print("grounded answer and absent-entity abstention: PASS")
    print("frozen Phase 7 fixture shape and domains: PASS")
    print("Phase 7 corpus contract: PASS")


if __name__ == "__main__":
    main()
