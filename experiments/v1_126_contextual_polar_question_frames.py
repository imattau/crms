"""Check learned context slots in grounded yes/no question frames."""

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
    examples = [
        ("Ada", "Engine Alpha", "2024", "Europe", True),
        ("Bea", "Engine Beta", "2025", "Asia", False),
        ("Cal", "Engine Gamma", "2024", "Asia", True),
        ("Dee", "Engine Delta", "2025", "Europe", True),
    ]
    for person, engine, year, region, answer in examples:
        qualifiers = {"year": year, "region": region}
        if answer:
            kb.add_fact(person, "designed", engine, "design:" + engine,
                        qualifiers=qualifiers)
        else:
            kb.add_negative_fact(person, "designed", engine,
                                 "review:" + engine, qualifiers=qualifiers)

    for index, (person, engine, year, region, answer) in enumerate(examples[:3]):
        licensed = kb.teach_polar_question(
            f"Did {person} design {engine} in {year} for {region}?",
            subject=person, relation="designed", obj=engine, answer=answer,
            qualifiers={"year": year, "region": region})
        if licensed != (index > 0):
            raise SystemExit("contextual polar frame licensed at the wrong evidence threshold")

    held_out = kb.ask("Did Dee design Engine Delta in 2025 for Europe?")
    if held_out.status != "answered" or held_out.truth is not True:
        raise SystemExit(f"held-out contextual yes/no transfer failed: {held_out}")
    negative = kb.ask("Did Bea design Engine Beta in 2025 for Asia?")
    if negative.status != "answered" or negative.truth is not False:
        raise SystemExit(f"explicit negative context was not preserved: {negative}")
    conflict = kb.ask("Did Dee design Engine Delta in 2025 for Europe?",
                      qualifiers={"year": "2024"})
    if conflict.status != "unknown":
        raise SystemExit("explicit qualifier conflict did not abstain")
    unknown = kb.ask("Did Dee design Engine Delta in 2026 for Europe?")
    if unknown.status != "unknown":
        raise SystemExit("unsupported contextual yes/no query was answered")

    proof_kb = CRMSKnowledgeBase()
    proof_rows = [
        ("Root A", "Mid A", "Leaf A", "2024", "Europe"),
        ("Root B", "Mid B", "Leaf B", "2025", "Asia"),
        ("Root C", "Mid C", "Leaf C", "2024", "Asia"),
        ("Root D", "Mid D", "Leaf D", "2025", "Europe"),
    ]
    for root, middle, leaf, year, region in proof_rows:
        scope = {"year": year, "region": region}
        proof_kb.add_fact(root, "parent", middle, "family:" + root,
                          qualifiers=scope)
        proof_kb.add_fact(middle, "parent", leaf, "family:" + middle,
                          qualifiers=scope)
    proof_kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    for root, _middle, leaf, year, region in proof_rows[:3]:
        licensed = proof_kb.teach_polar_question(
            f"Is {root} an ancestor of {leaf} in {year} across {region}?",
            subject=root, relation="ancestor", obj=leaf, answer=True,
            qualifiers={"year": year, "region": region})
    inferred = proof_kb.ask(
        "Is Root D an ancestor of Leaf D in 2025 across Europe?")
    if (not licensed or inferred.status != "answered" or inferred.truth is not True
            or not inferred.inference_proofs):
        raise SystemExit("contextual polar frame did not transfer a verified rule proof")

    explicit_only = CRMSKnowledgeBase()
    for parent, child in (("Mara", "Nico"), ("Omar", "Pia"),
                          ("Rae", "Sol")):
        explicit_only.add_fact(
            parent, "parent", child, "family:" + parent,
            qualifiers={"year": "2024"})
    for parent, child in (("Mara", "Nico"), ("Omar", "Pia")):
        explicit_only.teach_polar_question(
            f"Is {parent} a parent of {child}?", subject=parent,
            relation="parent", obj=child, answer=True,
            qualifiers={"year": "2024"})
    explicit_context = explicit_only.ask(
        "Is Rae a parent of Sol?", qualifiers={"year": "2024"})
    if explicit_context.status != "answered" or explicit_context.truth is not True:
        raise SystemExit("explicit-context-only polar teaching regressed")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        loaded = restored.ask("Did Dee design Engine Delta in 2025 for Europe?")
        if loaded.status != "answered" or loaded.truth is not True:
            raise SystemExit("contextual polar frame did not survive persistence")
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json")],
            input=("/ask-context Did Dee design Engine Delta in 2025 for Europe?|year=2025|region=Europe\n"
                   "/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if "Yes" not in process.stdout:
            raise SystemExit(f"contextual polar CLI query failed:\n{process.stdout}")

    print("contextual polar question-frame diagnostic: PASS")
    print("grounded slots, held-out fact and proof transfer, positive/negative evidence, conflict and unknown abstention, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
