"""Publisher-disjoint excerpt probe for generic procedure phrase extraction.

The frozen candidate grammar is exercised on a Microsoft Learn source excerpt
not used to develop it. Only two short sentences are retained; this is not a
complete-document or precision estimate.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_research import CRMSResearchIndex, SearchHit
from crms_translation import CRMSTranslation


SOURCE_ID = "microsoft-tools-json"
TITLE = "tools.json for discovering nuget.exe versions"
URL = "https://learn.microsoft.com/en-us/nuget/api/tools-json"
POSITIVE = (
    "The items in the array will be sorted in descending, SemVer 2.0.0 order.")
NEGATIVE = "The root JSON object has the following property."


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document(SOURCE_ID, TITLE, POSITIVE + " " + NEGATIVE, URL)
    hit = next((row for row in index.search(
        "array sorted descending SemVer", limit=10, context_chars=0)
        if row.document_id == SOURCE_ID), None)
    require(hit is not None, "retrieval missed held-out Microsoft Learn excerpt")
    exact_hit = SearchHit(SOURCE_ID, TITLE, URL, hit.score, POSITIVE,
                          0, len(POSITIVE), ())
    citation = index.citation(exact_hit)
    evidence = index.resolve_citation(citation)
    require(evidence == POSITIVE,
            f"candidate did not retain the exact source sentence: {evidence!r}")
    candidates = propose_procedure_phrase_candidates(
        evidence, source_citation=citation)
    require(len(candidates) == 1
            and candidates[0].subject.casefold() == "the items in the array"
            and candidates[0].predicate_phrase
                == "be sorted in descending, SemVer 2.0.0 order"
            and candidates[0].polarity
            and candidates[0].assertion_status == "asserted"
            and not candidates[0].quoted,
            f"held-out publisher subject or phrase was misread: {candidates!r}")
    require(not propose_procedure_phrase_candidates(
        NEGATIVE, source_citation=citation),
        "unrelated sentence was emitted as a procedure candidate")

    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="crms-publisher-transfer-") as tmp:
        root = Path(tmp)
        index.save(root / "index.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSMath().save(root / "math.json")
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSTranslation().save(root / "translations.json")
        process = subprocess.run(
            [sys.executable, str(project / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--math", str(root / "math.json"),
             "--rules", str(root / "rules.json"),
             "--translations", str(root / "translations.json"),
             "--index", str(root / "index.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--candidate-session", str(root / "candidates.json"),
             "--rule-session", str(root / "rule-session.json")],
            input=("/suggest-procedure-phrases array sorted descending SemVer\n"
                   "/rules\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        require("'be sorted in descending, SemVer 2.0.0 order'" in process.stdout
                and citation in process.stdout
                and "No transformation rules are committed yet." in process.stdout,
                f"chat lost the qualifier/citation or taught a rule: {process.stdout}")

    print("PASS: frozen extractor transfers to one new publisher excerpt")
    print("PASS: comma-delimited qualifier and exact local source citation survive")
    print("PASS: unrelated sentence abstains and the candidate remains inert")
    print("LIMIT: one excerpt and one matched candidate; full-document transfer untested")


if __name__ == "__main__":
    main()
