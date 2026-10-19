"""Regressions for entity-grounded retrieval and multi-turn chat failures."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (  # noqa: E402
    _exact_title_location_evidence, _natural_where_lookup,
    _natural_who_evidence)
from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


def chat_command(root: Path, index_path: Path, knowledge_path: Path) -> list[str]:
    return [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path), "--index", str(index_path),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rules", str(root / "rules.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--candidate-session", str(root / "candidate-session.json"),
        "--math", str(root / "math.json"),
        "--math-session", str(root / "math-session.json"),
        "--translations", str(root / "translations.json"),
        "--translation-session", str(root / "translation-session.json"),
    ]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-295-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "science", "Science notes",
            "Marie Curie won two Nobel Prizes. "
            "Albert Einstein won the Nobel Prize in Physics in 1921.",
            "science.txt")
        index.add_document(
            "geography", "Geography notes",
            "Mount Everest is located in the Himalayas.", "geography.txt")
        index.add_document(
            "computing", "Computing notes",
            "Alan Turing worked at Bletchley Park. "
            "Ada Lovelace created Python.", "computing.txt")
        index.add_document(
            "linux", "Operating systems notes",
            "Linus Torvalds developed Linux.", "linux.txt")
        index.add_document(
            "family", "Family notes", "Cara is a parent of Dan.",
            "family.txt")
        index.add_document(
            "quarn", "Quarn Beacon", "Bree Hollis created Quarn Beacon.",
            "quarn.txt")

        if _natural_who_evidence(index, "Who created?") is not None:
            raise SystemExit(
                "entity-less Who question returned an arbitrary source sentence")
        bounded_creator = _natural_who_evidence(
            index, "Who created Python?")
        if (bounded_creator is None
                or bounded_creator.get("text")
                != "Ada Lovelace created Python."):
            raise SystemExit(
                "bounded Who question did not preserve its full source sentence: "
                f"{bounded_creator}")

        knowledge = CRMSKnowledgeBase()
        count_result = knowledge.research(
            "How many Nobel Prizes did Marie Curie win?", index)
        count_text = " ".join(
            sentence.get("text", "")
            for sentence in (count_result.source_sentences or []))
        if ("Marie Curie won two Nobel Prizes." not in count_text
                or "Albert Einstein won" in count_text):
            raise SystemExit(
                "named-entity retrieval returned a competing person's sentence: "
                f"{count_text}")

        for question, expected in (
                ("Where is Mount Everest located?",
                 "Mount Everest is located in the Himalayas."),
                ("Where does Alan Turing work?",
                 "Alan Turing worked at Bletchley Park.")):
            parsed = _natural_where_lookup(question)
            evidence = (_exact_title_location_evidence(index, *parsed)
                        if parsed else None)
            if evidence is None or evidence["text"] != expected:
                raise SystemExit(
                    f"location query did not find its exact subject sentence: "
                    f"{question}: {evidence}")

        parent_candidates = knowledge._discover_surface_relation_candidates(
            "Cara is a parent of Dan.", source="family.txt")
        if any(candidate.relation == "is-a" for candidate in parent_candidates):
            raise SystemExit(
                "relational nominal 'parent of' was misclassified as a type: "
                f"{parent_candidates}")
        if not any((candidate.subject, candidate.relation, candidate.object)
                   == ("Cara", "parent of", "Dan")
                   for candidate in parent_candidates):
            raise SystemExit(
                f"parent-of relation was not retained: {parent_candidates}")
        reversed_candidates = knowledge._discover_surface_relation_candidates(
            "The Quarn Beacon designed Bree Hollis.", source="fixture:roles")
        role_warning = next((item for candidate in reversed_candidates
                             for item in candidate.language_evidence
                             if item.get("role_direction_suspicion")), None)
        if role_warning is None or not role_warning.get("review_required"):
            raise SystemExit(
                "article-led subject and name-shaped object did not surface a "
                f"role-direction warning: {reversed_candidates}")

        knowledge_path = root / "knowledge.json"
        knowledge.save(knowledge_path)
        turns = [
            "Who created Python?",
            "Who created?",
            "What created Quarn Beacon?",
            "Who created Linux?",
            "How many Nobel Prizes did Marie Curie win?",
            "Did Marie Curie win a Nobel Prize?",
            "Did Alan Turing work at Bletchley Park?",
            "Where is Mount Everest located?",
            "Where does Alan Turing work?",
            "Who created Python and Linux?",
            "/pending-candidates",
            "Who created Python?",
            "/quit",
        ]
        result = subprocess.run(
            chat_command(root, index_path, knowledge_path),
            input="\n".join(turns) + "\n", text=True,
            capture_output=True, cwd=root, timeout=60, check=False)
        if result.returncode:
            raise SystemExit(
                "multi-turn pending-candidate chat crashed:\n"
                + result.stderr + result.stdout)
        if "Traceback" in result.stdout or "Traceback" in result.stderr:
            raise SystemExit("multi-turn chat emitted a traceback")
        if ("I couldn't find evidence for Linux" not in result.stdout
                or "does not answer every part" not in result.stdout):
            raise SystemExit(
                "conjunctive Who question did not disclose the missing part:\n"
                + result.stdout)
        if "Which thing do you mean? Please include the object" not in result.stdout:
            raise SystemExit(
                "underspecified Who question did not ask for its missing object:\n"
                + result.stdout)
        if ("your question asks ‘what’" not in result.stdout
                or "Did you mean ‘who’ created it?" not in result.stdout
                or "Review candidate" in result.stdout
                   and "Bree Hollis — created → Quarn Beacon" in result.stdout):
            raise SystemExit(
                "What/Who role mismatch did not trigger clarification:\n"
                + result.stdout)
        if ("Mount Everest is located in the Himalayas." not in result.stdout
                or "Alan Turing worked at Bletchley Park." not in result.stdout):
            raise SystemExit(
                "chat did not quote the indexed location evidence:\n"
                + result.stdout)
        if "Albert Einstein won" in result.stdout:
            raise SystemExit(
                "chat showed a sentence about the wrong person:\n" + result.stdout)
        if ("The source states yes:" not in result.stdout
                or "Marie Curie won two Nobel Prizes." not in result.stdout
                or "Alan Turing worked at Bletchley Park." not in result.stdout):
            raise SystemExit(
                "matching do-support questions did not return cited yes answers:\n"
                + result.stdout)

        print("PASS: named-entity questions exclude competing subjects")
        print("PASS: underspecified Who questions abstain; matched evidence keeps the full sentence")
        print("PASS: person-shaped source subject prompts on a What question")
        print("PASS: location answers work from mixed-document sentences")
        print("PASS: parent-of extraction remains relational")
        print("PASS: suspicious active-clause role direction is flagged for review")
        print("PASS: matching do-support questions return cited yes evidence")
        print("PASS: conjunctive Who reply discloses a missing answer")
        print("PASS: repeated pending-candidate turns complete without crashing")
        index.close()


if __name__ == "__main__":
    main()
