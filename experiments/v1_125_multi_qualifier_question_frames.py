"""Check language transfer for questions with multiple context slots."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    kb = CRMSKnowledgeBase()
    rows = [
        ("Ada", "Project Alpha", "2024", "Europe"),
        ("Bea", "Project Beta", "2025", "Asia"),
        ("Cal", "Project Gamma", "2024", "Asia"),
        ("Dee", "Project Delta", "2025", "Europe"),
    ]
    for person, project, year, region in rows:
        kb.add_fact(person, "managed", project, "source:" + project,
                    qualifiers={"year": year, "region": region})

    for index, (person, project, year, region) in enumerate(rows[:3]):
        licensed = kb.teach_qualified_question(
            f"Who managed {project} in {year} across {region}?",
            relation="managed", answer_field="subject", bound_entity=project,
            answer=person, qualifier={"year": year, "region": region})
        if licensed != (index > 0):
            raise SystemExit("multi-context frame licensed at the wrong evidence threshold")

    held_out = kb.ask("Who managed Project Delta in 2025 across Europe?")
    if held_out.status != "answered" or held_out.answer != "Dee":
        raise SystemExit(f"held-out qualifier combination failed: {held_out}")
    conflict = kb.ask("Who managed Project Delta in 2025 across Europe?",
                      qualifiers={"year": "2024"})
    if conflict.status != "unknown":
        raise SystemExit("explicit context conflict did not abstain")
    unknown_scope = kb.ask("Who managed Project Delta in 2026 across Europe?")
    if unknown_scope.status != "unknown":
        raise SystemExit("unsupported multi-context values produced an answer")

    proof_kb = CRMSKnowledgeBase()
    proof_rows = [
        ("Root A", "Mid A", "Leaf A", "2024", "Europe"),
        ("Root B", "Mid B", "Leaf B", "2025", "Asia"),
        ("Root C", "Mid C", "Leaf C", "2024", "Asia"),
        ("Root D", "Mid D", "Leaf D", "2025", "Europe"),
    ]
    for root, middle, leaf, year, region in proof_rows:
        qualifiers = {"year": year, "region": region}
        proof_kb.add_fact(root, "parent", middle, "family:" + root,
                          qualifiers=qualifiers)
        proof_kb.add_fact(middle, "parent", leaf, "family:" + middle,
                          qualifiers=qualifiers)
    proof_kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    for root, _middle, leaf, year, region in proof_rows[:3]:
        licensed = proof_kb.teach_qualified_question(
            f"Who is an ancestor of {leaf} in {year} across {region}?",
            relation="ancestor", answer_field="subject", bound_entity=leaf,
            answer=root, qualifier={"year": year, "region": region})
    proof_result = proof_kb.ask(
        "Who is an ancestor of Leaf D in 2025 across Europe?")
    if (not licensed or proof_result.status != "answered"
            or proof_result.answer != "Root D"
            or not proof_result.inference_proofs):
        raise SystemExit("multi-context frame did not transfer through a verified rule proof")

    folded = CRMSKnowledgeBase()
    for person, project in (("Eli", "Project Epsilon"),
                            ("Fay", "Project Zeta"),
                            ("Gus", "Project Eta")):
        folded.add_fact(person, "managed", project, "source:" + project,
                        qualifiers={"year": "2024", "region": "Europe"})
        if project != "Project Eta":
            folded.teach_question(
                f"Who managed {project}?", relation="managed",
                answer_field="subject", bound_entity=project, answer=person)
    casefold_result = folded.ask(
        "Who managed Project Eta?", qualifiers={"year": "2024", "region": "europe"})
    if casefold_result.status != "answered" or casefold_result.answer != "Gus":
        raise SystemExit("standard question frame lost case-insensitive qualifier matching")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        result = restored.ask("Who managed Project Delta in 2025 across Europe?")
        if result.status != "answered" or result.answer != "Dee":
            raise SystemExit("multi-context question frame did not survive persistence")
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json")],
            input=("/ask-context Who managed Project Delta in 2025 across Europe?|year=2025|region=Europe\n"
                   "/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if "Dee" not in process.stdout:
            raise SystemExit(f"CLI multi-context query failed:\n{process.stdout}")

    print("multi-qualifier question-frame diagnostic: PASS")
    print("grounded licensing, held-out combinations, proof-backed transfer, scope case-folding, conflict abstention, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
