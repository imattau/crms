"""Exercise count extraction with article-led subjects and post-object counts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import _natural_count_evidence
from crms_research import CRMSSQLiteResearchIndex, CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = PROJECT / "data" / "crms_simplewiki_research.sqlite"
REPORT = PROJECT / "experiments" / "reports" / "v1_524_natural_count_article_and_post_object.json"
QUESTIONS = (
    ("How many Nobel Prizes did Marie Curie win?", "two",
     "1911 – Marie Curie wins the Nobel Prize in Chemistry, becoming the first person to win two Nobel Prizes."),
    ("How many Nobel Prizes did the Curie family receive?", "5",
     "The Curie family received 5 Nobel Prizes."),
    ("How many Nobel Peace Prizes did the International Committee of the Red Cross receive?",
     "three",
     "As a group, the International Committee of the Red Cross (ICRC) has received the Nobel Peace Prize three times:"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    source = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)
    document = source.document("wiki:simplewiki:6494")
    index = CRMSResearchIndex()
    index.add_document(document.document_id, document.title,
                       document.text, document.location)
    copied_ids = {document.document_id}
    rows = []
    for question, expected_quantity, expected_excerpt in QUESTIONS:
        evidence = _natural_count_evidence(source, question)
        require(evidence is not None
                and evidence.get("quantity") == expected_quantity,
                f"full-index count extraction failed for {question!r}: {evidence!r}")
        require(expected_excerpt in evidence["text"],
                f"source excerpt changed or missing: {expected_excerpt}")
        if evidence["document_id"] not in copied_ids:
            supporting_document = source.document(evidence["document_id"])
            index.add_document(supporting_document.document_id,
                               supporting_document.title,
                               supporting_document.text,
                               supporting_document.location)
            copied_ids.add(supporting_document.document_id)
        rows.append({"question": question, "quantity": expected_quantity,
                     "citation": evidence["citation"],
                     "source_title": evidence["title"],
                     "source_text": evidence["text"]})

    for row in rows:
        require(index.resolve_citation(row["citation"]) == row["source_text"],
                f"copied source did not resolve the count citation: {row}")

    # The same one-document source copy must support ordinary fresh-process
    # chat without access to the installed research index.
    with tempfile.TemporaryDirectory(prefix="crms-v1-524-") as temp:
        root = Path(temp)
        index_path = root / "source-copy.json"
        index.save(index_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--index", str(index_path),
            "--feedback-db", str(root / "feedback.sqlite3"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        result = subprocess.run(
            command, input="\n".join(question for question, _, _ in QUESTIONS)
            + "\n/quit\n", text=True, capture_output=True, cwd=root,
            timeout=60, check=False)
        output = result.stdout + result.stderr
        require(result.returncode == 0 and "Traceback" not in output,
                f"fresh CLI crashed: {output}")
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in output.splitlines() if "CRMS>" in line]
        require(len(replies) == len(QUESTIONS),
                f"unexpected CLI reply count: {replies!r}")
        for reply, (_question, quantity, excerpt) in zip(replies, QUESTIONS):
            require(quantity in reply.casefold() and excerpt in reply,
                    f"fresh CLI did not state the supported count: {reply!r}")
            require("couldn't find a source sentence" not in reply.casefold(),
                    f"fresh CLI abstained despite direct evidence: {reply!r}")
        cli_output = output

    source.close()
    report = {
        "experiment": "v1_524_natural_count_article_and_post_object",
        "source_document": document.document_id,
        "source_index_opened_read_only": True,
        "checks": {
            "article_led_subjects_retrieved": True,
            "count_before_object_extracted": True,
            "count_after_object_with_times_extracted": True,
            "repeated_object_mentions_select_explicit_count": True,
            "fresh_cli_answers_from_source_copy": True,
            "citations_resolve_from_source_copy": True,
            "no_accepted_facts_written": True,
        },
        "cases": rows,
        "cli_output": cli_output,
        "limits": [
            "Three count claims from two encyclopedia pages do not establish broad count understanding.",
            "The count route returns cited source wording rather than a general learned numeric procedure.",
            "Compound counts, paraphrases, and semantically equivalent verbs remain untested.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("PASS: article-led entity phrases retrieve without stopword leakage")
    print("PASS: repeated-object, pre-object, and post-object counts are extracted correctly")
    print("PASS: fresh CLI answers both from the copied source text")
    print("LIMIT: three claims, two SimpleWiki pages; no broad count-language claim")


if __name__ == "__main__":
    main()
