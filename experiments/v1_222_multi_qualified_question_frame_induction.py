"""Test source-grounded induction of multi-qualifier question frames."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_question_induction import (
    propose_analogical_multi_qualified_question_frames,
    question_frame_proposal_sources_current,
)


PROJECT = Path(__file__).resolve().parents[1]


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for subject, obj, city, year, source in (
            ("Ada", "Engine", "London", "2001", "design-a"),
            ("Bea", "Compiler", "Paris", "2002", "design-b")):
        qualifiers = {"location": city, "year": year}
        kb.add_fact(subject, "designed", obj, source,
                    qualifiers=qualifiers)
        question = f"Who designed {obj} in {city} during {year}?"
        kb.teach_qualified_question(
            question, relation="designed", answer_field="subject",
            bound_entity=obj, answer=subject, qualifier=qualifiers)
    for subject, obj, city, year, source in (
            ("Gus", "Bridge", "Rome", "2005", "build-a"),
            ("Hal", "Tower", "Berlin", "2006", "build-b"),
            ("Ivy", "Road", "Tokyo", "2007", "build-c"),
            ("Jo", "Tunnel", "Sydney", "2008", "build-d")):
        qualifiers = {"location": city, "year": year}
        kb.add_fact(subject, "built", obj, source, qualifiers=qualifiers)
        kb.add_fact(subject, "built", obj, source)
        kb.teach_fact_pattern(
            f"{subject} built {obj}.", subject=subject, relation="built",
            obj=obj, source=source)
    return kb


def main() -> None:
    kb = seed()
    facts_before = [(fact.subject, fact.relation, fact.object,
                     fact.qualifiers, fact.sources) for fact in kb.facts()]
    frames_before = dict(kb._multi_qualified_question_examples)
    proposals = propose_analogical_multi_qualified_question_frames(kb)
    proposal = next((item for item in proposals
                     if item["base_relation"] == "designed"
                     and item["target_relation"] == "built"), None)
    if (proposal is None or proposal["validation_passed"] is not True
            or len(proposal["qualifier_names"]) != 2
            or proposal["training_entities"] != 2
            or proposal["heldout_entities"] != 2):
        raise SystemExit(f"multi-qualified frame failed its gates: {proposals}")
    lineage = proposal["lineage"]
    if set(lineage["training_source_documents"]).intersection(
            lineage["holdout_source_documents"]):
        raise SystemExit("multi-qualifier train and holdout documents overlap")
    if (facts_before != [(fact.subject, fact.relation, fact.object,
                          fact.qualifiers, fact.sources) for fact in kb.facts()]
            or frames_before != kb._multi_qualified_question_examples):
        raise SystemExit("multi-qualified proposal generation mutated source knowledge")
    if not question_frame_proposal_sources_current(kb, proposal):
        raise SystemExit("multi-qualified proposal lineage did not validate")

    if not kb.accept_question_frame_proposal(proposal["artifact_id"]):
        raise SystemExit("validated multi-qualified frame was not accepted")
    if kb._multi_qualified_question_examples != frames_before:
        raise SystemExit("induced frame was mixed into teacher examples")
    answer = kb.ask("Who built Tunnel in Sydney during 2008?")
    if (answer.status != "answered" or answer.answer != "Jo"
            or not any(item.get("kind")
                       == "induced_multi_qualified_question_frame"
                       and item.get("artifact_id") == proposal["artifact_id"]
                       for item in answer.language_evidence or [])):
        raise SystemExit(f"induced multi-qualified frame failed held-out query: {answer}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        kb.save(knowledge_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        restored_answer = restored.ask(
            "Who built Tunnel in Sydney during 2008?")
        if (restored_answer.status != "answered"
                or restored_answer.answer != "Jo"
                or not restored._induced_multi_qualified_question_frames):
            raise SystemExit("multi-qualified induced frame failed persistence")

        seed().save(knowledge_path)
        paths = {name: root / name for name in (
            "index.json", "dialogue.json", "rules.json", "session.json",
            "math.json", "translations.json")}
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path),
             "--index", str(paths["index.json"]),
             "--dialogue-state", str(paths["dialogue.json"]),
             "--rules", str(paths["rules.json"]),
             "--rule-session", str(paths["session.json"]),
             "--rule-depth", "1", "--rule-max-add", "30",
             "--math", str(paths["math.json"]),
             "--translations", str(paths["translations.json"])],
            input=("Review question frame proposals\n"
                   "Learn the current validated question frame proposals\n"
                   "Who built Tunnel in Sydney during 2008?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if ("qualifiers=location, year" not in process.stdout
                or "Accepted 1 source-backed question frame(s)" not in process.stdout
                or not ("Answer: Jo." in process.stdout
                        or "Jo built Tunnel. [context: location=Sydney, year=2008]"
                        in process.stdout)):
            raise SystemExit(
                f"multi-qualified natural-language training failed:\n{process.stdout}")

    kb.remove_fact("Gus", "built", "Bridge", "build-a")
    stale = kb.ask("Who built Tunnel in Sydney during 2008?")
    if stale.status != "unknown" or stale.matched_templates:
        raise SystemExit("multi-qualified induced frame survived evidence retraction")

    print(f"multi-qualified question-frame induction: {len(proposals)} proposal(s); PASS")
    print("all qualifier slots varied, source-separated holdout, lineage audit, "
          "natural-language training, persistence, evidence attribution, "
          "and invalidation after retraction: PASS")


if __name__ == "__main__":
    main()
