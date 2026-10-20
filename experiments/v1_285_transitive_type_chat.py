"""Check typed source questions use only reviewed transitive is-a proofs."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-type-hierarchy-chat-") as temp:
        root = Path(temp)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        documents = (
            ("serein-route", "Serein River route",
             "The Serein River flows through Nacre City."),
            ("serein-kind", "Serein River classification",
             "The Serein River is a river."),
            ("river-kind", "Waterway taxonomy",
             "A river is a waterway."),
        )
        for document_id, title, sentence in documents:
            index.add_document(document_id, title, sentence,
                               f"fixture://{document_id}")
        citations = {}
        for document_id, _title, sentence in documents:
            hit = next(hit for hit in index.search(sentence, limit=10)
                       if hit.document_id == document_id)
            citations[document_id] = index.citation(hit)
        index.close()

        question = "Which waterway flows through Nacre City?"

        def run_chat(knowledge_path: Path, suffix: str) -> str:
            command = [
                sys.executable, str(PROJECT / "crms_chat.py"),
                "--index", str(index_path),
                "--knowledge", str(knowledge_path),
                "--rules", str(root / f"{suffix}-rules.json"),
                "--rule-session", str(root / f"{suffix}-rule-session.json"),
                "--candidate-session", str(root / f"{suffix}-candidates.json"),
                "--math", str(root / f"{suffix}-math.json"),
                "--math-session", str(root / f"{suffix}-math-session.json"),
                "--translations", str(root / f"{suffix}-translations.json"),
                "--translation-session",
                str(root / f"{suffix}-translation-session.json"),
                "--dialogue-state", str(root / f"{suffix}-dialogue.json"),
                "--feedback-db", str(root / f"{suffix}-feedback.sqlite3"),
            ]
            result = subprocess.run(
                command, input=question + "\n/quit\n", text=True,
                capture_output=True, check=False, cwd=root, timeout=45)
            require(result.returncode == 0,
                    f"{suffix} chat failed: {result.stderr}\n{result.stdout}")
            return result.stdout

        untyped = CRMSKnowledgeBase()
        untyped.add_fact(
            "The Serein River", "flows through", "Nacre City",
            citations["serein-route"])
        untyped.save(root / "untyped.json")
        abstention = run_chat(root / "untyped.json", "untyped")
        require("couldn't independently verify" in abstention
                and "is a waterway that flows through" not in abstention,
                f"missing type evidence was promoted to an answer: {abstention}")

        typed = CRMSKnowledgeBase()
        typed.add_fact(
            "The Serein River", "flows through", "Nacre City",
            citations["serein-route"])
        typed.add_fact(
            "The Serein River", "is-a", "river",
            citations["serein-kind"])
        typed.add_fact("river", "is-a", "waterway",
                       citations["river-kind"])
        typed.add_relation_type(
            "is-a", "transitive", "reviewed:transitive-type-schema")
        proof = typed.infer_relation(
            "The Serein River", "is-a", "waterway")
        require(proof.status == "answered" and proof.conclusion is not None
                and proof.conclusion["object"] == "waterway" and proof.proofs,
                f"reviewed type hierarchy did not produce a proof: {proof}")
        typed.save(root / "typed.json")
        answer = run_chat(root / "typed.json", "typed")
        require("The Serein River is a waterway that flows through Nacre City."
                in answer
                and "accepted transitive is-a proof" in answer,
                f"chat did not explain the derived type: {answer}")
        for title in ("Serein River route", "Serein River classification",
                      "Waterway taxonomy"):
            require(title in answer,
                    f"derived answer lost contributing source {title}: {answer}")

        conflict_index = CRMSSQLiteResearchIndex(index_path)
        conflict_index.add_document(
            "serein-objection", "Serein River disputed classification",
            "The Serein River is not a waterway.",
            "fixture://serein-objection")
        hit = next(hit for hit in conflict_index.search(
            "The Serein River is not a waterway.", limit=10)
                   if hit.document_id == "serein-objection")
        citations["serein-objection"] = conflict_index.citation(hit)
        conflict_index.close()

        conflicted = CRMSKnowledgeBase()
        conflicted.add_fact(
            "The Serein River", "flows through", "Nacre City",
            citations["serein-route"])
        conflicted.add_fact(
            "The Serein River", "is-a", "river",
            citations["serein-kind"])
        conflicted.add_fact("river", "is-a", "waterway",
                            citations["river-kind"])
        conflicted.add_relation_type(
            "is-a", "transitive", "reviewed:transitive-type-schema")
        conflicted.add_negative_fact(
            "The Serein River", "is-a", "waterway",
            citations["serein-objection"])
        conflicted.save(root / "conflicted.json")
        conflict_reply = run_chat(root / "conflicted.json", "conflicted")
        require("Sources conflict about whether The Serein River is a waterway"
                in conflict_reply
                and "The Serein River is a waterway that flows through" not in
                    conflict_reply
                and "Serein River disputed classification" in conflict_reply
                and "Serein River route" in conflict_reply
                and "Waterway taxonomy" in conflict_reply,
                f"conflicting type evidence did not block the derived answer: {conflict_reply}")

    print("transitive type hierarchy chat: PASS")
    print("untyped river evidence abstained; reviewed type facts plus an explicit "
          "transitivity schema produced a cited waterway answer; a conflicting "
          "negative type claim forced abstention")


if __name__ == "__main__":
    main()
