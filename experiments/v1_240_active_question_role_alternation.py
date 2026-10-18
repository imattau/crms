"""Audit report-only induction of a regular active-voice question alternation."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_question_role_induction import propose_active_role_alternation_frames
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def build_kb(*, share_target_source: bool = False) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    relations = [
        ("designed", "design", [
            ("Ada", "the Engine", "sources/design-a"),
            ("Grace", "the Compiler", "sources/design-b")], True),
        ("painted", "paint", [
            ("Claude", "the Mural", "sources/paint-a"),
            ("Mary", "the Portrait", "sources/paint-b")], True),
        ("kicked", "kick", [
            ("Ella", "the Ball", "sources/kick-a"),
            ("Fred", "the Door", "sources/kick-b")], True),
        ("walked", "walk", [
            ("Ana", "the Dog", "sources/design-a" if share_target_source
             else "sources/walk-a"),
            ("Ben", "the Cat", "sources/walk-b")], False),
    ]
    for relation, base, rows, paired in relations:
        for subject, obj, source in rows:
            kb.add_fact(subject, relation, obj, source)
            kb.teach_question(
                f"Who {relation} {obj}?", relation=relation,
                answer_field="subject", bound_entity=obj, answer=subject)
            if paired:
                kb.teach_question(
                    f"What did {subject} {base}?", relation=relation,
                    answer_field="object", bound_entity=subject, answer=obj)
    return kb


def main() -> None:
    kb = build_kb()
    facts_before = [(fact.subject, fact.relation, fact.object,
                     fact.sources, fact.qualifiers) for fact in kb.facts()]
    frames_before = {key: dict(rows) for key, rows in kb._question_examples.items()}
    proposals = propose_active_role_alternation_frames(kb)
    proposal = next((item for item in proposals
                     if item["target_relation"] == "walked"), None)
    if proposal is None:
        raise SystemExit(f"no held-out active role alternation proposal: {proposals}")
    lineage = proposal["lineage"]
    if (proposal["validation_passed"] is not True
            or proposal["report_only"] is not True
            or proposal["answer_field"] != "object"
            or proposal["prefix"] != ["what", "did"]
            or proposal["suffix"] != ["walk"]
            or len(lineage["training_relations"]) != 2
            or lineage["heldout_relation"]["relation"] not in {"kicked", "painted"}
            or len(lineage["target_validation"]) != 2
            or not all(row["passed"] for row in lineage["target_validation"])
            or not lineage["source_separation"]):
        raise SystemExit(f"role alternation failed its declared gates: {proposal}")
    if facts_before != [(fact.subject, fact.relation, fact.object,
                         fact.sources, fact.qualifiers) for fact in kb.facts()]:
        raise SystemExit("proposal generation mutated source facts")
    if frames_before != {key: dict(rows) for key, rows in kb._question_examples.items()}:
        raise SystemExit("proposal generation mutated taught question frames")
    if propose_active_role_alternation_frames(build_kb(share_target_source=True)):
        raise SystemExit("source overlap between training and target was accepted")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        run = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json"),
             "--rule-session", str(root / "rule-session.json")],
            input="/suggest-question-role-rules\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20, cwd=root)
        if (proposal["artifact_id"] not in run.stdout
                or "target relation=walked" not in run.stdout
                or "held-out relations=1" not in run.stdout
                or "report-only" not in run.stdout):
            raise SystemExit(f"terminal role-rule review failed:\n{run.stdout}")
        if CRMSKnowledgeBase.load(knowledge_path)._question_examples != frames_before:
            raise SystemExit("report-only CLI command changed learned frames")
        accepted_run = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--dialogue-state", str(root / "accepted-dialogue.json"),
             "--rules", str(root / "rules.json"),
             "--rule-session", str(root / "rule-session.json")],
            input=(f"Accept question frame proposal {proposal['artifact_id']}\n"
                   "What did Ana walk?\n/quit\n"), text=True,
            capture_output=True, check=True, timeout=20, cwd=root)
        if ("Accepted the current source-separated question frame" not in
                accepted_run.stdout
                or "Answer: the Dog." not in accepted_run.stdout
                or proposal["artifact_id"] not in accepted_run.stdout):
            raise SystemExit(f"terminal frame acceptance/use failed:\n"
                             f"{accepted_run.stdout}")

    if not kb.accept_question_frame_proposal(proposal["artifact_id"]):
        raise SystemExit("validated role alternation was not accepted")
    accepted = kb.ask("What did Ana walk?")
    if (accepted.status != "answered" or accepted.answer != "the Dog"
            or not any(item.get("kind") == "induced_question_frame"
                       and item.get("artifact_id") == proposal["artifact_id"]
                       for item in accepted.language_evidence or [])):
        raise SystemExit(f"accepted role-alternation frame did not answer: {accepted}")
    with tempfile.TemporaryDirectory() as directory:
        saved = Path(directory) / "role-alternation.json"
        kb.save(saved)
        restored = CRMSKnowledgeBase.load(saved)
        result = restored.ask("What did Ben walk?")
        if result.status != "answered" or result.answer != "the Cat":
            raise SystemExit(f"accepted role rule did not survive reload: {result}")

    kb.remove_fact("Ana", "walked", "the Dog", "sources/walk-a")
    stale = kb.ask("What did Ana walk?")
    if stale.status != "unknown":
        raise SystemExit("accepted question frame stayed active after source retraction")

    print(f"active question role alternation: {len(proposals)} proposal(s); PASS")
    print("two training relations, held-out relation, source separation, target "
          "answer/citation validation, report-only review, explicit acceptance, "
          "persistence, source invalidation: PASS")


if __name__ == "__main__":
    main()
