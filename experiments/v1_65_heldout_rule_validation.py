"""Validate discovered rules on source-separated evidence before acceptance."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_inference import validate_rule_candidate
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def add_chain(kb: CRMSKnowledgeBase, subject: str, middle: str, target: str,
              prefix: str, *, label: str | None = "positive") -> None:
    kb.add_fact(subject, "parent", middle, f"{prefix}:p1")
    kb.add_fact(middle, "parent", target, f"{prefix}:p2")
    if label == "positive":
        kb.add_fact(subject, "ancestor", target, f"{prefix}:label")
    elif label == "negative":
        kb.add_negative_fact(subject, "ancestor", target, f"{prefix}:label")


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    add_chain(kb, "Ada", "Bea", "Cal", "train:one")
    add_chain(kb, "Dee", "Eli", "Fay", "train:two")
    add_chain(kb, "Gus", "Hal", "Ivy", "holdout:one")
    add_chain(kb, "Jo", "Kim", "Lou", "holdout:two")
    add_chain(kb, "Nia", "Oren", "Pia", "runtime", label=None)
    return kb


def main() -> None:
    kb = seed()
    reviews = kb.review_inference_rules("holdout:")
    if not reviews.complete or len(reviews.reviews) != 1:
        raise SystemExit(f"source split produced an unexpected review: {reviews}")
    review = reviews.reviews[0]
    if review.validation is None or review.validation.status != "validated":
        raise SystemExit(f"held-out positive evidence did not validate the candidate: {review}")
    if (len(review.validation.positive_examples) != 2
            or review.validation.negative_examples):
        raise SystemExit(f"holdout metrics are incorrect: {review.validation}")
    shared = asdict(kb.facts()[0])
    overlap = validate_rule_candidate(
        review.candidate, training_facts=[shared], training_negative_facts=[],
        validation_facts=[shared], validation_negative_facts=[])
    if overlap.status != "overlap":
        raise SystemExit("candidate validation allowed a training/holdout fact overlap")
    if kb._inference_rules:
        raise SystemExit("reviewing a candidate silently accepted it")

    rejected_kb = CRMSKnowledgeBase()
    add_chain(rejected_kb, "Ada", "Bea", "Cal", "train:one")
    add_chain(rejected_kb, "Dee", "Eli", "Fay", "train:two")
    add_chain(rejected_kb, "Gus", "Hal", "Ivy", "holdout:one", label="negative")
    add_chain(rejected_kb, "Jo", "Kim", "Lou", "holdout:two", label="positive")
    rejected = rejected_kb.accept_inference_rule_candidate(
        1, "parent-transitivity", "holdout:")
    if rejected.accepted or rejected.review.validation.status != "contradicted":
        raise SystemExit(f"candidate with held-out counterexample was accepted: {rejected}")

    insufficient_kb = CRMSKnowledgeBase()
    add_chain(insufficient_kb, "Ada", "Bea", "Cal", "train:one")
    add_chain(insufficient_kb, "Dee", "Eli", "Fay", "train:two")
    add_chain(insufficient_kb, "Gus", "Hal", "Ivy", "holdout:one")
    insufficient = insufficient_kb.accept_inference_rule_candidate(
        1, "parent-transitivity", "holdout:")
    if insufficient.accepted or insufficient.review.validation.status != "insufficient":
        raise SystemExit(f"insufficient holdout was accepted: {insufficient}")

    same_source_kb = CRMSKnowledgeBase()
    add_chain(same_source_kb, "Ada", "Bea", "Cal", "train:one")
    add_chain(same_source_kb, "Dee", "Eli", "Fay", "train:two")
    add_chain(same_source_kb, "Gus", "Hal", "Ivy",
              "holdout:one#section-a")
    add_chain(same_source_kb, "Jo", "Kim", "Lou",
              "holdout:one#section-b")
    same_source = same_source_kb.accept_inference_rule_candidate(
        1, "parent-transitivity", "holdout:")
    if (same_source.accepted
            or same_source.review.validation.status
            != "insufficient-independent-sources"
            or same_source.review.validation.independent_sources
            != ("holdout:one",)):
        raise SystemExit("two sections of one source counted as independent validation")

    revised_kb = seed()
    revised = revised_kb.accept_inference_rule_candidate(
        1, "parent-transitivity", "holdout:")
    if not revised.accepted:
        raise SystemExit(f"valid rule was not accepted for revision test: {revised}")
    revised_kb.teach_question(
        "Who is an ancestor of Cal?", relation="ancestor",
        answer_field="subject", bound_entity="Cal", answer="Ada")
    revised_kb.teach_question(
        "Who is an ancestor of Fay?", relation="ancestor",
        answer_field="subject", bound_entity="Fay", answer="Dee")
    if revised_kb.list_inference_rules()[0]["status"] != "validated":
        raise SystemExit("accepted rule was not listed as validated")
    practiced = revised_kb.practice_relation("Nia", "ancestor", "Pia")
    if (practiced.status != "answered"
            or revised_kb.retrieve_derived_case(
                "Nia", "ancestor", "Pia", record_use=False) is None):
        raise SystemExit("validated rule result was not practiced as a derived case")
    revised_kb.add_negative_fact(
        "Nia", "ancestor", "Pia", "revision:explicit-negative")
    contradicted = revised_kb.infer_relation("Nia", "ancestor", "Pia")
    if contradicted.status != "ambiguous":
        raise SystemExit(
            f"new counterevidence did not conflict with accepted rule: {contradicted}")
    listed_rule = revised_kb.list_inference_rules()[0]
    if (listed_rule["status"] != "needs_review"
            or not listed_rule["validation"].get("counterexamples")):
        raise SystemExit("counterexample did not suspend the learned rule")
    revised_kb.add_fact("Ria", "parent", "Sia", "fresh:p1")
    revised_kb.add_fact("Sia", "parent", "Uma", "fresh:p2")
    suspended = revised_kb.infer_relation("Ria", "ancestor", "Uma")
    if (suspended.status != "unknown"
            or suspended.reason_code != "rule_needs_review"):
        raise SystemExit(
            f"suspended rule still answered a new instance: {suspended}")
    suspended_question = revised_kb.ask("Who is an ancestor of Uma?")
    if (suspended_question.status != "unknown"
            or suspended_question.reason_code != "rule_needs_review"):
        raise SystemExit(
            f"natural-language route bypassed suspended rule: {suspended_question}")
    if revised_kb.retrieve_derived_case(
            "Nia", "ancestor", "Pia", record_use=False) is not None:
        raise SystemExit("contradicted derived case remained retrievable")
    if revised_kb.practice_relation(
            "Ria", "ancestor", "Uma").status != "unknown":
        raise SystemExit("practice wrote back a rule result after contradiction")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "revised.sqlite"
        revised_kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_result = restored.infer_relation("Nia", "ancestor", "Pia")
        restored_suspended = restored.infer_relation("Ria", "ancestor", "Uma")
        if (restored_result.status != "ambiguous"
                or restored_suspended.reason_code != "rule_needs_review"
                or restored.retrieve_derived_case(
                    "Nia", "ancestor", "Pia", record_use=False) is not None):
            raise SystemExit("rule conflict or derived-case invalidation changed after reload")
        restored.close()
    if not revised_kb.remove_negative_fact(
            "Nia", "ancestor", "Pia", "revision:explicit-negative"):
        raise SystemExit("could not retract the mistaken counterexample")
    revalidated = revised_kb.accept_inference_rule_candidate(
        1, "parent-transitivity", "holdout:")
    if (not revalidated.accepted
            or revised_kb.list_inference_rules()[0]["status"] != "validated"
            or revised_kb.infer_relation("Ria", "ancestor", "Uma").status
               != "answered"
            or revised_kb.ask("Who is an ancestor of Uma?").answer != "Ria"):
        raise SystemExit("corrected rule could not be revalidated and reused")

    revised_kb.add_negative_fact(
        "Nia", "ancestor", "Pia", "revision:legacy-negative")
    with tempfile.TemporaryDirectory() as folder:
        legacy_path = Path(folder) / "legacy-accepted.json"
        revised_kb.save(legacy_path)
        legacy_payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        for stored_rule in legacy_payload["inference_rules"]:
            stored_rule.get("validation", {}).pop("status", None)
        legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
        migrated = CRMSKnowledgeBase.load(legacy_path)
        if (migrated.list_inference_rules()[0]["status"] != "needs_review"
                or migrated.infer_relation("Ria", "ancestor", "Uma").reason_code
                   != "rule_needs_review"
                or migrated.infer_relation("Nia", "ancestor", "Pia").status
                   != "ambiguous"):
            raise SystemExit(
                "legacy accepted-rule record was not reconciled with its counterexample")
        migrated.close()

    teacher_kb = CRMSKnowledgeBase()
    teacher_kb.add_inference_rule(
        "teacher-parent-transitivity", "parent", "parent", "ancestor")
    teacher_kb.add_fact("Ria", "parent", "Sia", "teacher:p1")
    teacher_kb.add_fact("Sia", "parent", "Uma", "teacher:p2")
    teacher_kb.add_fact("Nia", "parent", "Oren", "teacher:p3")
    teacher_kb.add_fact("Oren", "parent", "Pia", "teacher:p4")
    teacher_kb.add_negative_fact(
        "Nia", "ancestor", "Pia", "teacher:negative")
    if (teacher_kb.list_inference_rules()[0]["status"] != "teacher_supplied"
            or teacher_kb.infer_relation("Ria", "ancestor", "Uma").status
               != "answered"
            or teacher_kb.infer_relation("Nia", "ancestor", "Pia").status
               != "ambiguous"):
        raise SystemExit(
            "source counterexample incorrectly suspended a teacher-supplied rule")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "list-rules.json"
        session_path = root / "rule-session.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(knowledge_path), "--index", str(index_path),
               "--dialogue-state", str(state_path), "--rules", str(rules_path),
               "--rule-session", str(session_path)]
        commands = [
            'Review inference rule candidates against held-out sources with prefix "holdout:".',
            'Accept rule candidate 1 as "parent-transitivity" using held-out source prefix "holdout:".',
            "/inference-rules",
            "/infer-relation Nia|ancestor|Pia",
            "/quit",
        ]
        process = subprocess.run(
            cli, input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if ("holdout=validated" not in process.stdout
                or "Accepted validated rule parent-transitivity" not in process.stdout
                or "2 independent sources" not in process.stdout
                or "parent-transitivity [validated]" not in process.stdout
                or "Derived: Nia — ancestor → Pia." not in process.stdout):
            raise SystemExit(f"CLI review/accept/use flow failed:\n{process.stdout}")
        saved = json.loads(knowledge_path.read_text(encoding="utf-8"))
        if len(saved.get("inference_rules", [])) != 1:
            raise SystemExit("validated rule was not persisted")
        validation_record = saved["inference_rules"][0].get("validation", {})
        if (validation_record.get("validation_source_prefix") != "holdout:"
                or len(validation_record.get("positive_examples", [])) != 2
                or len(validation_record.get("training_positive_examples", [])) != 2):
            raise SystemExit("accepted rule lost its validation provenance")
        loaded = CRMSKnowledgeBase.load(knowledge_path)
        if loaded.infer_relation("Nia", "ancestor", "Pia").status != "answered":
            raise SystemExit("accepted rule did not remain usable after reload")
    print("held-out rule validation diagnostic: PASS")
    print("disjoint source split, counterexample rejection, explicit acceptance, "
          "learned-rule suspension and revalidation, teacher-rule preservation, "
          "legacy-store reconciliation, derived-case invalidation, "
          "SQLite persistence, and CLI use: PASS")


if __name__ == "__main__":
    main()
