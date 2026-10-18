"""Audit report-only question-frame induction from source-backed relations."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_question_induction import propose_analogical_question_frames


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_kb() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    rows = [
        ("Ada", "designed", "Engine", "design-a"),
        ("Bea", "designed", "Compiler", "design-b"),
        ("Gus", "built", "Bridge", "build-a"),
        ("Hal", "built", "Tower", "build-b"),
        ("Ivy", "built", "Road", "build-c"),
        ("Jo", "built", "Road", "build-d"),
        ("Kim", "built", "Tunnel", "build-e"),
        ("Lee", "built", "Hangar", "build-f"),
    ]
    for subject, relation, obj, source in rows:
        kb.add_fact(subject, relation, obj, source)
    for question, entity, answer in (
            ("Who designed Engine?", "Engine", "Ada"),
            ("Who designed Compiler?", "Compiler", "Bea")):
        kb.teach_question(question, relation="designed", answer_field="subject",
                          bound_entity=entity, answer=answer)
    for subject, relation, obj, source in rows[2:]:
        kb.teach_fact_pattern(
            f"{subject} built {obj}.", subject=subject, relation=relation,
            obj=obj, source=source)
    return kb


def main() -> None:
    kb = make_kb()
    facts_before = [(fact.subject, fact.relation, fact.object,
                     fact.sources, fact.qualifiers) for fact in kb.facts()]
    question_frames_before = {key: dict(rows)
                              for key, rows in kb._question_examples.items()}
    candidates = propose_analogical_question_frames(kb)
    proposal = next((item for item in candidates
                     if item["target_relation"] == "built"
                     and item["base_relation"] == "designed"), None)
    require(proposal is not None,
            f"no source-backed question-frame analogy passed checks: {candidates}")
    require(proposal["validation_passed"] is True
            and proposal["report_only"] is True
            and proposal["training_entities"] == 2
            and proposal["heldout_entities"] == 2,
            f"proposal did not pass its declared mechanical gates: {proposal}")
    lineage = proposal["lineage"]
    training_sources = {source for row in lineage["training_examples"]
                        for source in row["sources"]}
    holdout_sources = {source for row in lineage["holdout_results"]
                       for source in row["expected_sources"]}
    training_documents = {source.split("#", 1)[0] for source in training_sources}
    holdout_documents = {source.split("#", 1)[0] for source in holdout_sources}
    require(not training_documents.intersection(holdout_documents),
            "training and holdout sources overlap")
    require(any(row["expected_status"] == "ambiguous"
                and row["passed"] for row in lineage["holdout_results"]),
            "proposal did not preserve a conflicting held-out answer")
    shared_source = make_kb()
    shared_source.add_fact("Ivy", "built", "Road", "build-a")
    shared_proposals = propose_analogical_question_frames(shared_source)
    shared = next((item for item in shared_proposals
                   if item["target_relation"] == "built"), None)
    require(shared is not None,
            "valid proposal disappeared when one candidate was source-overlapped")
    shared_train_docs = {source.split("#", 1)[0]
                         for row in shared["lineage"]["training_examples"]
                         for source in row["sources"]}
    shared_holdout_docs = {source.split("#", 1)[0]
                           for row in shared["lineage"]["holdout_results"]
                           for source in row["expected_sources"]}
    require(not shared_train_docs.intersection(shared_holdout_docs),
            "source overlap on a fact leaked across the train/holdout split")
    if facts_before != [(fact.subject, fact.relation, fact.object,
                         fact.sources, fact.qualifiers) for fact in kb.facts()]:
        raise SystemExit("proposal generation mutated source facts")
    if question_frames_before != {key: dict(rows)
                                  for key, rows in kb._question_examples.items()}:
        raise SystemExit("proposal generation mutated licensed question frames")

    require(kb.accept_question_frame_proposal(str(proposal["artifact_id"])),
            "validated frame proposal was not accepted into the derived store")
    require(question_frames_before == {
                key: dict(rows) for key, rows in kb._question_examples.items()},
            "induced frame was merged into teacher-provided examples")
    induced_answer = kb.ask("Who built Bridge?")
    require(induced_answer.status == "answered" and induced_answer.answer == "Gus"
            and any(item.get("kind") == "induced_question_frame"
                    and item.get("artifact_id") == proposal["artifact_id"]
                    for item in induced_answer.language_evidence or []),
            f"accepted frame did not answer with its lineage: {induced_answer}")

    # Without a licensed source-backed predicate frame, the analogy is not
    # generated, even when relation facts happen to exist.
    ungrounded = make_kb()
    ungrounded._fact_pattern_examples.clear()
    ungrounded._fact_pattern_predicates.clear()
    ungrounded._fact_pattern_predicate_sources.clear()
    require(not propose_analogical_question_frames(ungrounded),
            "relation names without source-backed predicate frames proposed syntax")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        kb.save(knowledge_path)
        restored_kb = CRMSKnowledgeBase.load(knowledge_path)
        restored_answer = restored_kb.ask("Who built Tunnel?")
        require(restored_answer.status == "answered"
                and restored_answer.answer == "Kim"
                and any(item.get("kind") == "induced_question_frame"
                        for item in restored_answer.language_evidence or []),
                "accepted frame or lineage did not survive persistence")
        # Exercise automatic training from a fresh teacher-only knowledge base.
        make_kb().save(knowledge_path)
        paths = {name: root / name for name in (
            "index.json", "dialogue.json", "rules.json", "session.json",
            "math.json", "translations.json")}
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(knowledge_path),
               "--index", str(paths["index.json"]),
               "--dialogue-state", str(paths["dialogue.json"]),
               "--rules", str(paths["rules.json"]),
               "--rule-session", str(paths["session.json"]),
               "--rule-depth", "1", "--rule-max-add", "30",
               "--math", str(paths["math.json"]),
               "--translations", str(paths["translations.json"])]
        run = subprocess.run(cli, input=("Review question frame proposals\n"
                                         f"Accept question frame proposal {proposal['artifact_id']}\n"
                                         "Who built Bridge?\n/quit\n"),
                             text=True, capture_output=True, check=True, timeout=20)
        require(proposal["artifact_id"] in run.stdout
                and "designed → built" in run.stdout
                and "source-separated=True" in run.stdout,
                f"report-only proposal command failed:\n{run.stdout}")
        require("Accepted the current source-separated question frame" in run.stdout
                and "Gus" in run.stdout,
                f"mechanical frame training failed to update chat:\n{run.stdout}")

        make_kb().save(knowledge_path)
        natural_run = subprocess.run(
            cli, input=("Learn the current validated question frame proposals\n"
                        "Who built Bridge?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        require("Accepted 1 source-backed question frame(s)" in natural_run.stdout
                and "Answer: Gus." in natural_run.stdout,
                "ordinary-language question-frame training did not learn and apply "
                f"the grounded frame:\n{natural_run.stdout}")

    kb.remove_fact("Gus", "built", "Bridge", "build-a")
    stale_answer = kb.ask("Who built Tunnel?")
    require(stale_answer.status == "unknown"
            and not stale_answer.matched_templates,
            "induced frame stayed active after its training source was retracted")
    try:
        kb.accept_question_frame_proposal(str(proposal["artifact_id"]))
    except ValueError:
        pass
    else:
        raise SystemExit("stale question-frame artifact was accepted again")

    print(f"analogical question-frame proposals: {len(candidates)} candidate(s); PASS")
    print("predicate grounding, source-separated training and holdout, answer/evidence "
          "checks, ambiguity preservation, read-only source state, CLI report: PASS")


if __name__ == "__main__":
    main()
