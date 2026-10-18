"""Test source-grounded induction and use of one-qualifier question frames."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_question_induction import (
    propose_analogical_qualified_question_frames,
    question_frame_proposal_sources_current,
)


PROJECT = Path(__file__).resolve().parents[1]


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for subject, obj, year, source in (
            ("Ada", "Engine", "2001", "design-a"),
            ("Bea", "Compiler", "2002", "design-b")):
        kb.add_fact(subject, "designed", obj, source,
                    qualifiers={"year": year})
        kb.teach_qualified_question(
            f"Who designed {obj} in {year}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject,
            qualifier={"year": year})
    for subject, obj, year, source in (
            ("Gus", "Bridge", "2005", "build-a"),
            ("Hal", "Tower", "2006", "build-b"),
            ("Ivy", "Road", "2007", "build-c"),
            ("Jo", "Tunnel", "2008", "build-d")):
        kb.add_fact(subject, "built", obj, source,
                    qualifiers={"year": year})
        # Predicate-language evidence is source-aligned with the qualified
        # fact, but is stored on the ordinary fact-pattern route.
        kb.add_fact(subject, "built", obj, source)
        kb.teach_fact_pattern(
            f"{subject} built {obj}.", subject=subject, relation="built",
            obj=obj, source=source)
    return kb


def main() -> None:
    kb = seed()
    before_facts = [(fact.subject, fact.relation, fact.object,
                     fact.qualifiers, fact.sources) for fact in kb.facts()]
    before_frames = dict(kb._qualified_question_examples)
    proposals = propose_analogical_qualified_question_frames(kb)
    proposal = next((item for item in proposals
                     if item["base_relation"] == "designed"
                     and item["target_relation"] == "built"), None)
    if (proposal is None or proposal["validation_passed"] is not True
            or proposal["training_entities"] != 2
            or proposal["heldout_entities"] != 2):
        raise SystemExit(f"qualified frame did not pass source-grounded gates: {proposals}")
    lineage = proposal["lineage"]
    if set(lineage["training_source_documents"]).intersection(
            lineage["holdout_source_documents"]):
        raise SystemExit("qualified question training and holdout sources overlap")
    if (before_facts != [(fact.subject, fact.relation, fact.object,
                          fact.qualifiers, fact.sources) for fact in kb.facts()]
            or before_frames != kb._qualified_question_examples):
        raise SystemExit("qualified proposal generation mutated source knowledge")
    if not question_frame_proposal_sources_current(kb, proposal):
        raise SystemExit("current qualified proposal failed its lineage audit")

    if not kb.accept_question_frame_proposal(proposal["artifact_id"]):
        raise SystemExit("validated qualified question frame was not accepted")
    if kb._qualified_question_examples != before_frames:
        raise SystemExit("induced qualified frame was merged into teacher examples")
    answer = kb.ask("Who built Tunnel in 2008?")
    if (answer.status != "answered" or answer.answer != "Jo"
            or not any(item.get("kind") == "induced_qualified_question_frame"
                       and item.get("artifact_id") == proposal["artifact_id"]
                       for item in answer.language_evidence or [])):
        raise SystemExit(f"induced qualified frame failed a held-out request: {answer}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        kb.save(knowledge_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        restored_answer = restored.ask("Who built Tunnel in 2008?")
        if (restored_answer.status != "answered"
                or restored_answer.answer != "Jo"
                or not restored._induced_qualified_question_frames):
            raise SystemExit("qualified induced frame did not persist and revalidate")

        make_cli_kb = seed()
        make_cli_kb.save(knowledge_path)
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
                   "Who built Tunnel in 2008?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        if process.returncode != 0:
            raise SystemExit(
                f"qualified frame CLI exited {process.returncode}: "
                f"{process.stdout}\n{process.stderr}")
        if ("designed → built; qualifier=year" not in process.stdout
                or "Accepted 1 source-backed question frame(s)" not in process.stdout
                or "Answer: Jo." not in process.stdout):
            raise SystemExit(
                f"natural-language qualified frame training failed:\n{process.stdout}")

    kb.remove_fact("Gus", "built", "Bridge", "build-a")
    stale = kb.ask("Who built Tunnel in 2008?")
    if stale.status != "unknown" or stale.matched_templates:
        raise SystemExit("qualified induced frame stayed active after evidence retraction")

    print(f"qualified question-frame induction: {len(proposals)} proposal(s); PASS")
    print("distinct qualifier/entity holdouts, source separation, lineage audit, "
          "natural-language training, persistence, evidence attribution, "
          "and invalidation after retraction: PASS")


if __name__ == "__main__":
    main()
