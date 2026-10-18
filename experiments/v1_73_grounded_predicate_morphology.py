"""Check productive predicate morphology induced from aligned examples.

Run from the project root with:
    python3 experiments/v1_73_grounded_predicate_morphology.py
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def teach_relation(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                   relation: str, surface: str, prefix: str) -> None:
    for number, (subject, obj) in enumerate((("Ada", "Engine"),
                                              ("Bea", "Compiler")), start=1):
        sentence = f"{subject} {surface} {obj}."
        document_id = f"{prefix}-{number}"
        index.add_document(document_id, document_id, sentence,
                           f"sources/{document_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document_id)
        kb.add_fact_from_hit(subject, relation, obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation=relation, obj=obj,
            predicate_phrase=surface, research_index=index, hit=hit)


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    teach_relation(kb, index, "design", "designed", "design")
    teach_relation(kb, index, "walk", "walked", "walk")
    teach_relation(kb, index, "manage", "managed", "manage")
    teach_relation(kb, index, "create", "created", "create")
    teach_relation(kb, index, "paint", "paint", "paint")
    teach_relation(kb, index, "bake", "bake", "bake")

    target = "The catalog lists painted sculpture surfaces."
    index.add_document("target", "target", target, "sources/target.txt")
    index.add_document("final-e-target", "final-e-target",
                       "The archive lists baked clay surfaces.",
                       "sources/final-e-target.txt")
    result = kb.research("paint", index, limit=10)
    ids = {passage["citation"].split("#", 1)[0]
           for passage in result.passages or []}
    if "target" not in ids:
        raise SystemExit("induced predicate form did not expand research retrieval")
    final_e_research = kb.research("bake", index, limit=10)
    final_e_ids = {passage["citation"].split("#", 1)[0]
                   for passage in final_e_research.passages or []}
    if "final-e-target" not in final_e_ids:
        raise SystemExit("final-e predicate form did not expand research retrieval")

    candidate = next((item for item in kb.propose_facts(
        "Sage painted Sculpture", source="review:heldout")
        if item.relation == "paint" and item.subject == "Sage"
        and item.object == "Sculpture"), None)
    if candidate is None:
        raise SystemExit("induced predicate form did not parse the held-out sentence")
    morphology = [item for item in candidate.language_evidence
                  if item.get("kind") == "induced_suffix"]
    if (len(morphology) != 1 or morphology[0]["suffix"] != "ed"
            or {item["relation"] for item in morphology[0]["support"]}
            != {"design", "walk"}
            or not all(item["sources"] for item in morphology[0]["support"])):
        raise SystemExit("candidate did not expose independent morphology support")

    final_e_candidate = next((item for item in kb.propose_facts(
        "Sage baked Sculpture", source="review:final-e")
        if item.relation == "bake" and item.subject == "Sage"), None)
    final_e_rule = next((item for item in (final_e_candidate.language_evidence
                                           if final_e_candidate else ())
                         if item.get("kind") == "induced_suffix"), None)
    if (final_e_rule is None or final_e_rule["suffix"] != "d"
            or final_e_rule["context"] != "final-e"
            or {item["relation"] for item in final_e_rule["support"]}
            != {"create", "manage"}):
        raise SystemExit("final-e suffix class was not learned from independent relations")

    kb.add_fact("Sage", "paint", "Sculpture", "source:sage")
    kb.teach_question("Who paint the Engine?", relation="paint",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who paint the Compiler?", relation="paint",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")
    answer = kb.ask("Who painted the Sculpture?")
    if answer.status != "answered" or answer.answer != "Sage":
        raise SystemExit(f"induced predicate form did not transfer to QA: {answer}")
    kb.add_fact("Sage", "bake", "Sculpture", "source:sage-bake")
    kb.teach_question("Who bake the Engine?", relation="bake",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who bake the Compiler?", relation="bake",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")
    baked_answer = kb.ask("Who baked the Sculpture?")
    if baked_answer.status != "answered" or baked_answer.answer != "Sage":
        raise SystemExit(f"final-e morphology did not transfer to QA: {baked_answer}")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        session_path = root / "rule-session.json"
        kb.save(path)
        index.save(index_path)
        restored = CRMSKnowledgeBase.load(path)
        restored_answer = restored.ask("Who painted the Sculpture?")
        if restored_answer.status != "answered" or restored_answer.answer != "Sage":
            raise SystemExit("predicate morphology did not survive QA persistence")
        restored_baked = restored.ask("Who baked the Sculpture?")
        if restored_baked.status != "answered" or restored_baked.answer != "Sage":
            raise SystemExit("final-e morphology did not survive QA persistence")
        if not any(item.get("kind") == "induced_suffix"
                   for item in next(item for item in restored.propose_facts(
                       "Sage painted Sculpture", source="review:heldout")
                       if item.relation == "paint").language_evidence):
            raise SystemExit("induced morphology did not survive persistence")
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(path), "--index", str(index_path),
             "--dialogue-state", str(state_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input="Who painted the Sculpture?\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "Sage" not in process.stdout or "please teach this question" in process.stdout.lower():
            raise SystemExit(f"held-out morphological QA failed in terminal dialogue:\n{process.stdout}")

    # One aligned relation cannot license a productive suffix by itself.
    cautious_index = CRMSResearchIndex()
    cautious = CRMSKnowledgeBase()
    teach_relation(cautious, cautious_index, "design", "designed", "design")
    teach_relation(cautious, cautious_index, "paint", "paint", "paint")
    cautious_index.add_document("control", "control", target,
                                "sources/control.txt")
    control = cautious.research("paint", cautious_index, limit=10)
    control_ids = {passage["citation"].split("#", 1)[0]
                   for passage in control.passages or []}
    if "control" in control_ids:
        raise SystemExit("one relation family licensed productive morphology")

    print("grounded predicate morphology diagnostic: PASS")
    print("cross-relation suffix induction, question-frame/terminal transfer, review-only parsing, retrieval, persistence, one-family abstention: PASS")


if __name__ == "__main__":
    main()
