"""Objective: persist explicit feedback against the exact answer evidence.

Setup: record direct-fact and rule-proof references in a temporary SQLite log.
Metrics: attribution, duplicate suppression, conflict preservation, reload.
Failure modes: feedback loses lineage, silently changes knowledge, or disappears.
Definition of success: exact references survive reload and no knowledge is mutated.
"""
from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_feedback import (
    AnswerFeedbackStore, collect_feedback_refs,
    collect_translation_feedback_refs, feedback_answer_id, render_feedback_refs,
)
from crms_knowledge import CRMSKnowledgeBase
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    response = SimpleNamespace(
        evidence=[{"subject": "Ada", "relation": "designed",
                   "object": "Engine", "sources": ["book:12"]},
                  {"subject": "Ada", "relation": "designed",
                   "object": "Engine", "sources": ["archive:3"]}],
        proofs=[{"rule": {"rule_id": "direct-proof-rule"},
                 "premises": [{"fact": {"sources": ["direct:1"]}}]}],
        inference_proofs=[{
            "rule": {"rule_id": "parent-rule"},
            "fact": {"sources": ["family:1"]},
            "premises": [{"fact": {"sources": ["family:2"]}}],
        }])
    research = SimpleNamespace(
        source_sentences=[{"document_id": "wiki:ada", "sentence_id": "s7"}],
        passages=[])
    refs = collect_feedback_refs(response, research)
    require(all({"kind": kind, "id": value} in refs for kind, value in (
        ("rule", "direct-proof-rule"), ("rule", "parent-rule"),
        ("source", "book:12"), ("source", "archive:3"),
        ("source", "direct:1"),
        ("source", "family:1"), ("source", "family:2"),
        ("source", "s7"), ("source", "wiki:ada"))),
        f"did not collect exact rule/source lineage: {refs}")

    translation = CRMSTranslation()
    translation.teach(
        "English", "Spanish", "neutral",
        "The cat greets {name}.", "El gato saluda a {name}.",
        [("The cat greets Lina.", "El gato saluda a Lina."),
         ("The cat greets Omar.", "El gato saluda a Omar.")])
    translated = translation.translate(
        "Translate from English to Spanish: The cat greets Lina.")
    translation_refs = collect_translation_feedback_refs(translated)
    require(len(translation_refs) == 1
            and translation_refs[0]["kind"] == "translation_frame"
            and len(translation_refs[0]["sources"]) == 2,
            f"translation feedback did not identify its aligned examples: {translation_refs}")
    require(collect_translation_feedback_refs(SimpleNamespace(
                status="ambiguous", output=None, evidence=())) == [],
            "ambiguous translation was offered as answer feedback")
    require(translation_refs == collect_translation_feedback_refs(translated),
            "translation evidence fingerprint was not deterministic")
    require("aligned example ids:" in render_feedback_refs(translation_refs),
            "translation feedback did not display its aligned-example references")
    fact_ref = next((item for item in refs if item["kind"] == "fact"), None)
    require(fact_ref is not None
            and fact_ref["subject"] == "Ada"
            and fact_ref["relation"] == "designed"
            and fact_ref["object"] == "Engine"
            and fact_ref["sources"] == ["archive:3", "book:12"],
            f"did not retain the proposition and sources: {fact_ref}")
    require("Ada — designed → Engine" in render_feedback_refs(refs)
            and "book:12" in render_feedback_refs(refs),
            "feedback references were not readable for fact correction")
    require(feedback_answer_id("Q", "A", refs) == feedback_answer_id(
        "Q", "A", [{"kind": item["kind"], "id": item["id"]}
                    for item in refs]),
        "adding readable fact metadata changed event identity")

    with tempfile.TemporaryDirectory(prefix="crms-feedback-") as directory:
        store = AnswerFeedbackStore(Path(directory) / "feedback.sqlite3")
        answer_id, inserted = store.record(
            "wrong", "Who designed Engine?", "Ada designed Engine.", refs)
        require(inserted, "first wrong signal was not stored")
        duplicate_id, inserted = store.record(
            "wrong", "Who designed Engine?", "Ada designed Engine.",
            list(reversed(refs)))
        require(answer_id == duplicate_id and not inserted,
                "same feedback was duplicated or order changed identity")
        _same_id, inserted = store.record(
            "right", "Who designed Engine?", "Ada designed Engine.", refs)
        require(inserted, "contradictory signal was not retained for review")
        reloaded = AnswerFeedbackStore(Path(directory) / "feedback.sqlite3")
        events = reloaded.events()
        require([row["verdict"] for row in events] == ["wrong", "right"],
                "feedback did not persist in event order")
        require(all(row["evidence"] == refs for row in events),
                "persisted feedback lost evidence attribution")
        require(all(row["question"] == "Who designed Engine?"
                    and row["answer"] == "Ada designed Engine."
                    for row in events),
                "feedback was attached to a different answer")
        require(reloaded.has_verdict(answer_id, "wrong")
                and reloaded.has_verdict(answer_id, "right"),
                "indexed opposite-verdict lookup missed a stored event")
        require([row["verdict"] for row in reloaded.recent(1)] == ["right"],
                "bounded recent-event query returned the wrong event")

    kb = CRMSKnowledgeBase()
    kb.add_fact("Nia", "parent", "Oren", "family:no")
    kb.add_fact("Oren", "parent", "Pia", "family:op")
    kb.add_inference_rule("learned-grandparent", "parent", "parent",
                          "grandparent")
    kb.add_inference_rule("teacher-rule", "parent", "parent",
                          "great-grandparent")
    key = ("learned", "grandparent")
    kb._inference_rule_validation[key] = {"status": "validated"}
    before = kb.infer_relation("Nia", "grandparent", "Pia")
    require(before.status == "answered" and before.proofs,
            "validated learned rule did not support the answer before feedback")
    changed = kb.flag_inference_rule_from_feedback(
        "learned-grandparent", {
            "answer_id": "feedback-1", "question": "Is Nia a grandparent of Pia?",
            "answer": "Yes."})
    require(changed, "wrong feedback did not flag a validated learned rule")
    after = kb.infer_relation("Nia", "grandparent", "Pia")
    require(after.status == "unknown",
            "rule awaiting review still contributed to inference")
    require(after.request is not None
            and "user marked an answer" in after.request
            and "feedback-1" in after.request,
            "abstention misrepresented the feedback as proven evidence")
    item = kb.list_inference_rules()[0]
    require(item["status"] == "needs_review"
            and item["validation"]["suspension_reason"] == "user_feedback"
            and item["validation"]["feedback_reports"][0]["answer_id"]
                == "feedback-1",
            "feedback suspension was not visible with its reason")
    require(not kb.flag_inference_rule_from_feedback(
        "learned-grandparent", {
            "answer_id": "feedback-1", "question": "Is Nia a grandparent of Pia?",
            "answer": "Yes."}),
        "duplicate feedback was applied twice to the rule")
    require(not kb.flag_inference_rule_from_feedback(
        "teacher-rule", {
            "answer_id": "feedback-2", "question": "q", "answer": "a"}),
        "unknown/teacher rule was altered")
    with tempfile.TemporaryDirectory(prefix="crms-rule-feedback-") as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_rule = restored.list_inference_rules()[0]
        require(restored_rule["status"] == "needs_review"
                and restored_rule["validation"]["feedback_reports"][0]["answer_id"]
                    == "feedback-1",
                "feedback-based rule suspension did not persist")

    with tempfile.TemporaryDirectory(prefix="crms-feedback-chat-") as directory:
        root = Path(directory)
        chat_kb = CRMSKnowledgeBase()
        chat_kb.add_fact("Nia", "parent", "Oren", "family:no")
        chat_kb.add_fact("Oren", "parent", "Pia", "family:op")
        chat_kb.add_inference_rule("learned-grandparent", "parent", "parent",
                                   "grandparent")
        chat_kb._inference_rule_validation[key] = {
            "status": "validated", "validation_source_prefix": "holdout:"}
        knowledge_path = root / "knowledge.json"
        chat_kb.save(knowledge_path)
        args = [sys.executable, str(ROOT / "crms_chat.py"),
                "--knowledge", str(knowledge_path),
                "--feedback-db", str(root / "feedback.sqlite3"),
                "--dialogue-state", str(root / "dialogue.json"),
                "--rules", str(root / "rules.json"),
                "--rule-session", str(root / "rule-session.json"),
                "--math", str(root / "math.json"),
                "--math-session", str(root / "math-session.json"),
                "--translations", str(root / "translations.json"),
                "--translation-session", str(root / "translation-session.json")]
        commands = ("/infer-relation Nia|grandparent|Pia\n/wrong\n"
                    "/inference-rules\n/infer-relation Nia|grandparent|Pia\n/quit\n")
        run = subprocess.run(args, input=commands, text=True, capture_output=True,
                             timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        for phrase in ("Suspended validated learned rule(s) for review",
                       "learned-grandparent [needs_review]",
                       "user marked an answer using it wrong", "Feedback "):
            require(phrase in run.stdout,
                    f"interactive feedback omitted {phrase!r}: {run.stdout}")
        require("contradictory source-backed evidence" not in run.stdout,
                "user feedback was described as a verified source counterexample")
        persisted = CRMSKnowledgeBase.load(knowledge_path).list_inference_rules()[0]
        require(persisted["status"] == "needs_review",
                "interactive feedback did not persist rule review status")

    with tempfile.TemporaryDirectory(prefix="crms-fact-feedback-chat-") as directory:
        root = Path(directory)
        chat_kb = CRMSKnowledgeBase()
        chat_kb.add_fact("Ada Lovelace", "designed", "Engine", "book:12")
        chat_kb.teach_question("Who designed Engine?", relation="designed",
                               answer_field="subject", bound_entity="Engine",
                               answer="Ada Lovelace")
        knowledge_path = root / "knowledge.json"
        chat_kb.save(knowledge_path)
        args = [sys.executable, str(ROOT / "crms_chat.py"),
                "--knowledge", str(knowledge_path),
                "--feedback-db", str(root / "feedback.sqlite3"),
                "--dialogue-state", str(root / "dialogue.json"),
                "--rules", str(root / "rules.json"),
                "--rule-session", str(root / "rule-session.json"),
                "--math", str(root / "math.json"),
                "--math-session", str(root / "math-session.json"),
                "--translations", str(root / "translations.json"),
                "--translation-session", str(root / "translation-session.json")]
        run = subprocess.run(
            args, input="Who designed Engine?\n/wrong\n/feedback\n/quit\n",
            text=True, capture_output=True, timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        for phrase in ("Ada Lovelace", "Ada Lovelace — designed → Engine",
                       "sources: book:12", "/retract-feedback 1|FACT_NUMBER|SOURCE_NUMBER"):
            require(phrase in run.stdout,
                    f"direct-fact feedback omitted {phrase!r}: {run.stdout}")
        persisted = CRMSKnowledgeBase.load(knowledge_path)
        require(len(persisted.facts()) == 1 and not persisted.negative_facts(),
                "wrong feedback silently altered stored facts")
        retract_args = args
        retract_run = subprocess.run(
            retract_args,
            input="/retract-feedback 1|1|1\n/quit\n",
            text=True, capture_output=True, timeout=30)
        require(retract_run.returncode == 0,
                retract_run.stderr or retract_run.stdout)
        require("Retracted POS support from book:12" in retract_run.stdout
                and "Recheck: no accepted fact now answers" in retract_run.stdout,
                f"explicit correction did not retract selected support: "
                f"{retract_run.stdout}")
        corrected_store = CRMSKnowledgeBase.load(knowledge_path)
        require(not corrected_store.facts(),
                "explicit feedback retraction left the selected support stored")
        require(AnswerFeedbackStore(root / "feedback.sqlite3").event(1) is not None,
                "explicit retraction deleted its feedback audit event")

    with tempfile.TemporaryDirectory(prefix="crms-translation-feedback-chat-") as directory:
        root = Path(directory)
        translation.save(root / "translations.json")
        args = [sys.executable, str(ROOT / "crms_chat.py"),
                "--knowledge", str(root / "knowledge.json"),
                "--feedback-db", str(root / "feedback.sqlite3"),
                "--dialogue-state", str(root / "dialogue.json"),
                "--rules", str(root / "rules.json"),
                "--rule-session", str(root / "rule-session.json"),
                "--math", str(root / "math.json"),
                "--math-session", str(root / "math-session.json"),
                "--translations", str(root / "translations.json"),
                "--translation-session", str(root / "translation-session.json")]
        run = subprocess.run(
            args,
            input=("Translate from English to Spanish: The cat greets Lina.\n"
                   "/wrong\n/feedback\n/quit\n"),
            text=True, capture_output=True, timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        events = AnswerFeedbackStore(root / "feedback.sqlite3").recent(1)
        require(len(events) == 1
                and any(item["kind"] == "translation_frame"
                        for item in events[0]["evidence"]),
                f"translation correction lost its model-frame attribution: {events}")

    print("answer feedback attribution: direct facts, rule, and source refs PASS")
    print("translation feedback ties to deterministic aligned-frame evidence: PASS")
    print("interactive translation feedback persists its frame attribution: PASS")
    print("SQLite persistence, deterministic IDs, duplicate suppression: PASS")
    print("conflicting feedback retained for review without changing knowledge: PASS")
    print("wrong proof feedback suspends only validated learned rules: PASS")
    print("rule feedback reason persists; teacher and duplicate signals are protected: PASS")
    print("interactive /wrong suspension and evidence-honest abstention: PASS")
    print("direct-fact feedback is inert until explicit source retraction: PASS")
    print("selected source retracted; feedback audit retained: PASS")


if __name__ == "__main__":
    main()
