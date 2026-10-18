"""Check explicit practice/write-back from a grounded natural-language answer."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def seed(*, contextual: bool = False) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    rows = [("Ada", "Engine", "London", "2024", "a"),
            ("Bea", "Compiler", "Paris", "2025", "b"),
            ("Cal", "Device", "Rome", "2024", "c")]
    for person, designed, city, year, source in rows:
        scope = {"year": year} if contextual else None
        kb.add_fact(person, "designed", designed, source + "-design",
                    qualifiers=scope)
        kb.add_fact(designed, "located in", city, source + "-location",
                    qualifiers=scope)
    kb.add_inference_rule("design-location", "designed", "located in",
                          "designed in")
    if contextual:
        for person, _designed, city, year, _source in rows[:2]:
            kb.teach_qualified_question(
                f"Who designed in {city} during {year}?",
                relation="designed in", answer_field="subject",
                bound_entity=city, answer=person, qualifier={"year": year})
    else:
        for person, _designed, city, _year, _source in rows[:2]:
            kb.teach_question(
                f"Who designed in {city}?", relation="designed in",
                answer_field="subject", bound_entity=city, answer=person)
    return kb


def main() -> None:
    kb = seed()
    original_facts = kb.facts()
    before = kb.ask("Who designed in Rome?")
    if before.status != "answered" or before.answer != "Cal" or not before.inference_proofs:
        raise SystemExit(f"fixture did not produce a proof-backed language answer: {before}")
    if kb.derived_cases():
        raise SystemExit("ordinary ask() unexpectedly wrote a derived case")

    answer, retained = kb.practice_question("Who designed in Rome?")
    if answer.status != "answered" or answer.answer != "Cal" or not retained:
        raise SystemExit("explicit question practice did not retain its inferred answer")
    cases = kb.derived_cases()
    if (len(cases) != 1 or cases[0]["conclusion"] != {
            "subject": "Cal", "relation": "designed in", "object": "Rome"}
            or cases[0]["lineage"] != {
                "sources": ["c-design", "c-location"],
                "rule_ids": ["design-location"]}):
        raise SystemExit(f"derived question answer lost its proof lineage: {cases}")
    reused = kb.infer_relation("Cal", "designed in", "Rome")
    if reused.status != "answered" or reused.expansions != 0:
        raise SystemExit("practiced natural-language answer was not reusable")
    if kb.facts() != original_facts:
        raise SystemExit("question practice promoted a derived answer to a fact")
    answer2, retained2 = kb.practice_question("Who designed in Rome?")
    if not retained2 or len(kb.derived_cases()) != 1 or kb.derived_cases()[0][
            "practice_count"] != 2:
        raise SystemExit("repeated question practice did not deduplicate its artifact")

    scoped = seed(contextual=True)
    scoped_answer, scoped_retained = scoped.practice_question(
        "Who designed in Rome during 2024?")
    if (scoped_answer.status != "answered" or scoped_answer.answer != "Cal"
            or not scoped_retained or len(scoped.derived_cases()) != 1
            or scoped.derived_cases()[0]["qualifiers"] != [("year", "2024")]):
        raise SystemExit("qualified answer practice lost its exact proof scope")

    direct = CRMSKnowledgeBase()
    direct.add_fact("Ada", "designed", "Engine", "direct-a")
    direct.add_fact("Bea", "designed", "Compiler", "direct-b")
    direct.teach_question("Who designed Engine?", relation="designed",
                          answer_field="subject", bound_entity="Engine", answer="Ada")
    direct.teach_question("Who designed Compiler?", relation="designed",
                          answer_field="subject", bound_entity="Compiler", answer="Bea")
    direct_answer, direct_retained = direct.practice_question("Who designed Engine?")
    if (direct_answer.status != "answered" or direct_retained
            or direct.derived_cases()):
        raise SystemExit("directly taught fact was written as a derived case")

    ambiguous = seed()
    ambiguous.add_fact("Dana", "designed", "Device", "d-design")
    ambiguous.add_fact("Device", "located in", "Rome", "d-location")
    ambiguous_answer, ambiguous_retained = ambiguous.practice_question(
        "Who designed in Rome?")
    if (ambiguous_answer.status != "ambiguous" or ambiguous_retained
            or ambiguous.derived_cases()):
        raise SystemExit("ambiguous language answer was practiced")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        dialogue_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        cli_kb = seed()
        cli_kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(dialogue_path), "--rules", str(rules_path)],
            input="/practice-question Who designed in Rome?\n/derived-cases\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20)
        if ("Answer: Cal." not in process.stdout
                or "Verified answer stored as a separate derived case." not in process.stdout
                or "Derived case [verified]: Cal — designed in → Rome" not in process.stdout):
            raise SystemExit(f"question-practice CLI flow failed:\n{process.stdout}")
        restored = CRMSKnowledgeBase.load(knowledge_path)
        if len(restored.derived_cases()) != 1 or len(restored.facts()) != 6:
            raise SystemExit("CLI practice did not persist a separate derived artifact")

        natural_knowledge_path = root / "natural-knowledge.json"
        natural_index_path = root / "natural-index.json"
        natural_kb = seed()
        natural_kb.save(natural_knowledge_path)
        CRMSResearchIndex().save(natural_index_path)
        natural_process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(natural_knowledge_path),
             "--index", str(natural_index_path),
             "--dialogue-state", str(root / "natural-dialogue.json"),
             "--rules", str(root / "natural-rules.json")],
            input=("Who designed in Rome?\nPractice that answer.\n"
                   "/derived-cases\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if ("Answer: Cal." not in natural_process.stdout
                or "Verified answer stored as a separate derived case."
                not in natural_process.stdout
                or "Derived case [verified]: Cal — designed in → Rome"
                not in natural_process.stdout):
            raise SystemExit("natural-language answer practice failed:\n"
                             + natural_process.stdout)
        natural_restored = CRMSKnowledgeBase.load(natural_knowledge_path)
        if len(natural_restored.derived_cases()) != 1:
            raise SystemExit("natural-language practice did not persist its artifact")

        auto_knowledge_path = root / "auto-knowledge.json"
        auto_index_path = root / "auto-index.json"
        auto_cli_kb = seed()
        auto_cli_kb.save(auto_knowledge_path)
        CRMSResearchIndex().save(auto_index_path)
        auto_process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(auto_knowledge_path),
             "--index", str(auto_index_path),
             "--dialogue-state", str(root / "auto-dialogue.json"),
             "--rules", str(root / "auto-rules.json")],
            input=("Who designed in Rome?\nShow derived cases\n"
                   "Turn auto-practice on\nWho designed in Rome?\n"
                   "Show current derived cases\nTurn auto-practice off\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if (auto_process.stdout.count("Auto-practice stored the verified inference") != 1
                or "No derived cases are stored." not in auto_process.stdout
                or "Auto-practice enabled for this chat session." not in auto_process.stdout):
            raise SystemExit(f"session auto-practice policy failed:\n{auto_process.stdout}")
        auto_restored = CRMSKnowledgeBase.load(auto_knowledge_path)
        if len(auto_restored.derived_cases()) != 1:
            raise SystemExit("session auto-practice did not persist its verified artifact")

        context_path = root / "context-knowledge.json"
        context_index_path = root / "context-index.json"
        context_kb = seed(contextual=True)
        context_kb.save(context_path)
        CRMSResearchIndex().save(context_index_path)
        context_process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(context_path), "--index", str(context_index_path),
             "--dialogue-state", str(root / "context-dialogue.json"),
             "--rules", str(root / "context-rules.json")],
            input=("/auto-practice on\n"
                   "/ask-context Who designed in Rome during 2024?|year=2024\n"
                   "/derived-cases\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if ("Answer: Cal." not in context_process.stdout
                or context_process.stdout.count(
                    "Auto-practice stored the verified inference") != 1):
            raise SystemExit("context command did not use the opt-in practice loop:\n"
                             + context_process.stdout)
        context_restored = CRMSKnowledgeBase.load(context_path)
        if (len(context_restored.derived_cases()) != 1
                or context_restored.derived_cases()[0]["qualifiers"]
                != [("year", "2024")]):
            raise SystemExit("auto-practiced context query lost its exact scope")

    print("language-answer practice loop: PASS")
    print("read-only ask, explicit and session-opt-in write-back, scope, reuse, "
          "deduplication, no fact promotion, ambiguity gate, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
