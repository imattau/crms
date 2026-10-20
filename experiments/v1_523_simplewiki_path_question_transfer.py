"""Check source-backed multi-hop question-frame transfer on SimpleWiki."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex, CRMSResearchIndex, SearchHit


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = PROJECT / "data" / "crms_simplewiki_research.sqlite"
REPORT = PROJECT / "experiments" / "reports" / "v1_523_simplewiki_path_question_transfer.json"
QUESTION = "Through the capital of which country does the {river} flow?"
PATH = ("flows through", "capital city of")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(root: Path, kb_path: Path, index_path: Path,
             question: str, name: str) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(kb_path), "--index", str(index_path),
        "--feedback-db", str(root / f"{name}-feedback.sqlite3"),
        "--dialogue-state", str(root / f"{name}-dialogue.json"),
        "--rules", str(root / f"{name}-rules.json"),
        "--rule-session", str(root / f"{name}-rule-session.json"),
        "--math", str(root / f"{name}-math.json"),
        "--translations", str(root / f"{name}-translations.json"),
    ]
    result = subprocess.run(command, input=question + "\n/quit\n", text=True,
                            capture_output=True, cwd=root, timeout=60,
                            check=False)
    require(result.returncode == 0,
            f"{name} chat failed: {result.stderr}\n{result.stdout}")
    chunks = result.stdout.split("you> ")
    require(len(chunks) >= 2, f"{name} chat emitted no answer: {result.stdout}")
    return chunks[1].strip()


def main() -> None:
    source = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)
    source_facts = (
        # Two licensed examples. The Thames citation keeps the explicit
        # antecedent and its follow-up sentence in one source span.
        ("wiki:simplewiki:3308", "flows through", "River Thames", "London",
         "The River Thames is a large river in England. It goes through London, the capital city of the United Kingdom."),
        ("wiki:simplewiki:3308", "capital city of", "London", "United Kingdom",
         "The River Thames is a large river in England. It goes through London, the capital city of the United Kingdom."),
        ("wiki:simplewiki:4467", "capital city of", "Paris", "France",
         'Paris (nicknamed the "City of light") is the capital city of France, and the largest city in France.'),
        ("wiki:simplewiki:347271", "flows through", "Seine", "Paris",
         "The Seine rises near Dijon in eastern central France, and flows through Paris and into the English Channel."),
        # Held-out route, from two source documents not used by the frame.
        ("wiki:simplewiki:29790", "flows through", "Tiber River", "Rome",
         "The Tiber River that flows through Rome gets its name from Tiberinus."),
        ("wiki:simplewiki:2875", "capital city of", "Rome", "Italy",
         ") is the capital city of Italy. It is also the capital and largest city in the region of Lazio, and the geographical region of Latium."),
    )

    index = CRMSResearchIndex()
    knowledge = CRMSKnowledgeBase()
    evidence_records = []
    copied_documents: set[str] = set()
    for document_id, relation, subject, obj, expected_span in source_facts:
        document = source.document(document_id)
        require(expected_span in document.text,
                f"source span changed or missing in {document.title}")
        if document.document_id not in copied_documents:
            index.add_document(document.document_id, document.title,
                               document.text, document.location)
            copied_documents.add(document.document_id)
        start = document.text.index(expected_span)
        hit = SearchHit(document_id, document.title, document.location, 1.0,
                        expected_span, start, start + len(expected_span),
                        ())
        fact = knowledge.add_fact_from_hit(subject, relation, obj, index, hit)
        evidence_records.append({
            "document_id": document_id,
            "title": document.title,
            "claim": f"{subject} — {relation} → {obj}",
            "citation": fact.sources[0] if fact.sources else None,
            "span": expected_span,
        })

    # Train only on Thames and Seine, each requiring one source-backed path.
    first = knowledge.teach_path_question(
        QUESTION.format(river="River Thames"), relations=PATH,
        bound_entity="River Thames", answer="United Kingdom")
    second = knowledge.teach_path_question(
        QUESTION.format(river="Seine"), relations=PATH,
        bound_entity="Seine", answer="France")
    require(not first and second,
            f"unexpected path-frame licensing sequence: {first!r}, {second!r}")
    result = knowledge.ask_path_question(QUESTION.format(river="Tiber River"))
    require(result.status == "answered" and result.answer == "Italy",
            f"held-out source-backed path failed: {result!r}")
    require(len(result.proofs or ()) == 1,
            f"expected one composed proof: {result!r}")

    # An unsupported river has no complete chain and must not inherit Italy.
    unsupported = knowledge.ask_path_question(
        QUESTION.format(river="Danube"))
    require(unsupported.status != "answered",
            f"unsupported river received an answer: {unsupported!r}")

    with tempfile.TemporaryDirectory(prefix="crms-v1-523-") as temp:
        root = Path(temp)
        kb_path = root / "model.json"
        index_path = root / "sources.json"
        knowledge.save(kb_path)
        index.save(index_path)

        # The source index in the copy must resolve every serialized citation.
        for record in evidence_records:
            require(index.resolve_citation(record["citation"]) == record["span"],
                    f"citation did not resolve to its reviewed sentence: {record}")

        positive = run_chat(root, kb_path, index_path,
                            QUESTION.format(river="Tiber River"), "heldout")
        require("Italy" in positive,
                f"fresh CLI did not transfer the held-out path: {positive}")
        require(all(title in positive for title in ("Rhea Silvia", "Rome")),
                f"fresh CLI omitted one of the held-out sources: {positive}")
        negative = run_chat(root, kb_path, index_path,
                            QUESTION.format(river="Danube"), "unsupported")
        require("Italy" not in negative,
                f"fresh CLI guessed an unsupported answer: {negative}")

    source.close()
    report = {
        "experiment": "v1_523_simplewiki_path_question_transfer",
        "source_index": str(SOURCE_DB.relative_to(PROJECT)),
        "input_index_opened_read_only": True,
        "training_entities": ["River Thames", "Seine"],
        "heldout_entity": "Tiber River",
        "heldout_answer": "Italy",
        "path": list(PATH),
        "training_frame": QUESTION,
        "source_citations": evidence_records,
        "checks": {
            "two_examples_licensed_frame": True,
            "heldout_path_answered_by_engine": True,
            "heldout_path_answered_in_fresh_cli_from_copied_model": True,
            "heldout_sources_shown": True,
            "unknown_route_abstained_in_engine": True,
            "unknown_route_did_not_guess_in_fresh_cli": True,
            "source_citations_resolved_in_copy": True,
        },
        "responses": {"heldout": positive, "unsupported": negative},
        "limits": [
            "Codex manually labeled claims from cited SimpleWiki text; this does not test automatic extraction or rule induction.",
            "One question frame and one held-out route do not establish broad natural-language or reasoning transfer.",
            "The composed result is a two-edge path lookup; no downstream numeric/list procedure was tested.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("PASS: source citations for the five facts resolve in the copied model")
    print("PASS: two source-backed training paths license the frame")
    print("PASS: held-out Tiber → Rome → Italy path answers in engine and fresh CLI")
    print("PASS: unsupported Danube path does not guess")
    print(f"REPORT: {REPORT}")
    print("LIMIT: one manually labeled SimpleWiki frame; no procedure, automatic extraction, or broad transfer claim")


if __name__ == "__main__":
    main()
