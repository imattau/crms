"""Exercise verified citation attribution on the interactive rule-teaching path."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def launch(root: Path, lines: list[str]) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--rules", str(root / "rules.json"),
        "--math", str(root / "math.json"),
        "--knowledge", str(root / "knowledge.json"),
        "--translations", str(root / "translations.json"),
        "--index", str(root / "index.json"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
    ]
    return subprocess.run(command, input="\n".join([*lines, "/quit", ""]),
                          text=True, capture_output=True, cwd=root,
                          timeout=30, check=False)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-chat-rule-source-") as folder:
        root = Path(folder)
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSTranslation().save(root / "translations.json")
        index = CRMSResearchIndex()
        sentence = "Sorting [3, 1, 2] produces [1, 2, 3]."
        index.add_document("procedure-example", "Sorting example", sentence,
                           "sources/sorting.txt")
        wrong_sentence = "Sorting [3, 1, 2] produces [3, 2, 1]."
        index.add_document("wrong-procedure-example", "Wrong sorting example",
                           wrong_sentence, "sources/wrong-sorting.txt")
        citation = index.citation(next(
            hit for hit in index.search(sentence, limit=10)
            if hit.document_id == "procedure-example"))
        mismatched_citation = index.citation(next(
            hit for hit in index.search(wrong_sentence, limit=10)
            if hit.document_id == "wrong-procedure-example"))
        require(index.resolve_citation(citation) == sentence,
                "test citation did not resolve to its exact source text")
        index.save(root / "index.json")

        run = launch(root, [
            f"/teach-rule sort the numbers|3,1,2|1,2,3|{citation}",
            "/teach-rule reverse the numbers|1,2,3|3,2,1",
        ])
        require(run.returncode == 0,
                f"chat exited {run.returncode}: {run.stderr}")
        require("Recorded source attribution for this example: " + citation
                in run.stdout
                and "has not independently checked that its wording" in run.stdout,
                "chat did not explain the attribution and its verification limit")

        rules = CRMSModel(root / "rules.json", max_workers=1)
        sort_records = rules.example_records("sort the numbers")
        reverse_records = rules.example_records("reverse the numbers")
        require(len(sort_records) == 1
                and sort_records[0]["source_id"] == citation,
                f"chat did not persist the verified citation: {sort_records!r}")
        require(len(reverse_records) == 1
                and reverse_records[0]["source_id"] is None,
                "chat fabricated source attribution for an unlabeled example")

        invalid = citation.replace("procedure-example", "missing-source")
        rejected = launch(root, [
            f"/teach-rule invalid source|1,2|1,2|{invalid}",
        ])
        require("Could not teach rule:" in rejected.stdout,
                "chat accepted a citation that failed source verification")
        after_rejection = CRMSModel(root / "rules.json", max_workers=1)
        require(not after_rejection.example_records("invalid source"),
                "invalid source citation left an example in rule memory")

        mismatched = launch(root, [
            f"/teach-rule mismatched source|3,1,2|1,2,3|{mismatched_citation}",
        ])
        require("does not contain this exact input/output pair" in mismatched.stdout,
                "chat accepted a citation that states a different output")
        after_mismatch = CRMSModel(root / "rules.json", max_workers=1)
        require(not after_mismatch.example_records("mismatched source"),
                "mismatched citation left an example in rule memory")

    print("chat records a citation containing the exact numeric demonstration: PASS")
    print("chat states that instruction licensing is still unverified: PASS")
    print("unattributed teaching remains explicitly unattributed: PASS")
    print("stale and output-mismatched citations are rejected: PASS")


if __name__ == "__main__":
    main()
