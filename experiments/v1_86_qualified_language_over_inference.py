"""Learn contextual question wording from and answer with rule proofs."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def teach_chain(kb: CRMSKnowledgeBase, subject: str, middle: str,
                obj: str, year: str) -> None:
    kb.add_fact(subject, "parent", middle, f"{subject}:parent-a",
                qualifiers={"year": year})
    kb.add_fact(middle, "parent", obj, f"{middle}:parent-b",
                qualifiers={"year": year})


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach_chain(kb, "Ada", "Bea", "Cal", "2024")
    teach_chain(kb, "Bob", "Dan", "Eli", "2025")
    teach_chain(kb, "Mia", "Nia", "Ora", "2024")
    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")

    if kb.teach_qualified_question(
            "Who is ancestor of Ada in 2024?", relation="ancestor",
            answer_field="object", bound_entity="Ada", answer="Cal",
            qualifier={"year": "2024"}):
        raise SystemExit("one proof-backed question example licensed transfer alone")
    if not kb.teach_qualified_question(
            "Who is ancestor of Bob in 2025?", relation="ancestor",
            answer_field="object", bound_entity="Bob", answer="Eli",
            qualifier={"year": "2025"}):
        raise SystemExit("second proof-backed question example did not license frame")

    answer = kb.ask("Who is ancestor of Mia in 2024?")
    if (answer.status != "answered" or answer.answer != "Ora"
            or not answer.inference_proofs):
        raise SystemExit(f"qualified language did not retrieve a rule-derived answer: {answer}")
    if any(fact.relation == "ancestor" for fact in kb.facts()):
        raise SystemExit("language QA promoted a derived relation to a source fact")
    wrong_context = kb.ask("Who is ancestor of Mia in 2025?")
    if wrong_context.status != "unknown":
        raise SystemExit(f"language query crossed qualifier contexts: {wrong_context}")

    index = CRMSResearchIndex()
    index.add_document("context-archive", "2024 archive",
                       "Ora appears in the 2024 archive index.",
                       "sources/archive.txt")
    research = kb.research("Who is ancestor of Mia in 2024?", index)
    if (research.response is None or research.response.status != "answered"
            or not research.derived_context
            or research.derived_context[0].get("qualifiers") != [["year", "2024"]]
            or "context: year=2024" not in kb.render_research(research)):
        raise SystemExit("research dropped the scope of its inferred answer")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        index.save(index_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        persisted = restored.ask("Who is ancestor of Mia in 2024?")
        if persisted.status != "answered" or persisted.answer != "Ora":
            raise SystemExit("proof-backed contextual QA did not persist")
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json")],
            input="Who is ancestor of Mia in 2024?\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20)
        if "Ora" not in process.stdout or "no matching" in process.stdout.lower():
            raise SystemExit(f"contextual inferred answer failed in chat:\n{process.stdout}")

    kb.add_negative_fact("Mia", "ancestor", "Ora", "counter:24",
                         qualifiers={"year": "2024"})
    conflict = kb.ask("Who is ancestor of Mia in 2024?")
    if conflict.status != "ambiguous":
        raise SystemExit("contextual language query hid conflicting negative evidence")

    print("qualified language over inference diagnostic: PASS")
    print("proof-backed frame teaching, held-out entity/context transfer, CLI, persistence, conflict abstention: PASS")


if __name__ == "__main__":
    main()
