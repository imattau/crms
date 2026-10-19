"""Reject lexical count matches unless entity, predicate, and object align."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import _natural_count_evidence, _natural_count_question
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-count-grounding-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "curie", "Marie Curie", "Marie Curie won two Nobel Prizes.",
            "curie.txt")
        index.add_document(
            "einstein", "Albert Einstein",
            "Albert Einstein won the Nobel Prize in Physics in 1921.",
            "einstein.txt")
        index.add_document(
            "noise", "Unrelated result",
            "The Nobel Prizes are discussed in this review.", "noise.txt")
        index.add_document(
            "wrong-predicate", "Curie biography",
            "Marie Curie received two awards.", "wrong-predicate.txt")
        index.add_document(
            "negative", "Counterfactual",
            "Marie Curie did not win three Nobel Prizes.", "negative.txt")
        index.add_document(
            "negative-contracted", "Counterfactual contraction",
            "Marie Curie didn't win four Nobel Prizes.", "negative-contracted.txt")
        query = "How many Nobel Prizes did Marie Curie win?"
        require(_natural_count_question(query)
                == ("Nobel Prizes", "Marie Curie", "win"),
                "count question was not parsed into its arguments")
        evidence = _natural_count_evidence(index, query)
        require(evidence is not None
                and evidence.get("quantity") == "two"
                and evidence.get("document_id") == "curie"
                and evidence.get("text") == "Marie Curie won two Nobel Prizes.",
                f"count retrieval did not select the matching Curie statement: {evidence}")
        require(_natural_count_evidence(
            index, "How many Nobel Prizes did Alice win?") is None,
            "lexically related sentences answered a question about an absent entity")
        require(_natural_count_evidence(
            index, "How many Nobel Prizes did Marie Curie receive?") is None,
            "a different predicate was treated as equivalent without a rule")

        index.add_document(
            "curie-conflict", "Curie alternate source",
            "Marie Curie won three Nobel Prizes.", "curie-alt.txt")
        conflict = _natural_count_evidence(index, query)
        require(conflict is not None and conflict.get("conflicting_counts")
                == ["three", "two"],
                f"conflicting source counts were not surfaced: {conflict}")
        index.close()

        # Exercise the user-facing route with isolated state files and a live
        # SQLite corpus, ensuring the wrong Einstein sentence is not shown.
        chat_index_path = root / "chat-research.sqlite"
        fresh_index = CRMSSQLiteResearchIndex(chat_index_path)
        fresh_index.add_document(
            "curie", "Marie Curie", "Marie Curie won two Nobel Prizes.",
            "curie.txt")
        fresh_index.add_document(
            "einstein", "Albert Einstein",
            "Albert Einstein won the Nobel Prize in Physics in 1921.",
            "einstein.txt")
        fresh_index.close()
        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        run = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--index", str(chat_index_path), "--knowledge", str(knowledge_path),
             "--rules", str(root / "rules.json"),
             "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rule-session", str(root / "rule-session.json")],
            input="/effort thorough\n" + query + "\n/quit\n",
            text=True, capture_output=True,
            cwd=root, timeout=30)
        require(run.returncode == 0, f"chat exited with error: {run.stderr}")
        require("Marie Curie won two Nobel Prizes." in run.stdout
                and "Albert Einstein won" not in run.stdout,
                f"chat did not stay grounded to the named subject:\n{run.stdout}")
        require("Reasoning effort set to thorough" in run.stdout,
                "chat did not accept the thorough effort setting")
        require("Plausibility check: the named entity, action, and item align"
                in run.stdout,
                "thorough chat omitted the relation plausibility result")

    print("count-question relation grounding: PASS")
    print("entity, predicate, object, negation, conflict and live chat checks: PASS")


if __name__ == "__main__":
    main()
