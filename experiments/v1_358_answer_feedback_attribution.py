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
    AnswerFeedbackStore, collect_codegen_feedback_refs,
    collect_feedback_refs,
    collect_math_feedback_refs, collect_translation_feedback_refs,
    collect_summary_feedback_refs, collect_timeline_feedback_refs,
    collect_writing_feedback_refs,
    feedback_answer_id, render_feedback_refs,
)
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_codegen import generate_python
from crms_research import CRMSResearchIndex
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

    math = CRMSMath()
    math.teach("What is 2 plus 3?", "5")
    math.teach("What is 5 plus 3?", "8")
    math_result = math.ask("What is 7 plus 3?")
    math_refs = collect_math_feedback_refs(math_result)
    require(len(math_refs) == 1 and math_refs[0]["kind"] == "math_derivation",
            f"math feedback did not identify the exact derivation: {math_refs}")
    require(math_refs == collect_math_feedback_refs(math_result),
            "math derivation fingerprint was not deterministic")
    require(collect_math_feedback_refs(SimpleNamespace(
                status="unknown", value=None, expression=None)) == [],
            "unknown math output was offered as answer feedback")

    code_model = CRMSModel(max_composition_depth=1, max_workers=1)
    require(code_model.teach(
                "reverse the list",
                [([1, 2, 3], [3, 2, 1]), ([4, -1, 7], [7, -1, 4])]
            ).status == "learned", "code feedback fixture did not learn")
    code_artifact = generate_python(code_model, "reverse the list")
    code_refs = collect_codegen_feedback_refs(code_artifact)
    require(len(code_refs) == 1
            and code_refs[0]["kind"] == "code_artifact"
            and code_refs[0]["id"] == code_artifact.provenance_id
            and code_refs[0]["evidence_examples"] >= 2
            and code_refs[0]["validation_cases"] >= 2,
            f"code feedback did not retain artifact provenance: {code_refs}")
    require("instruction evidence:" in render_feedback_refs(code_refs),
            "code feedback hid its instruction evidence")
    require(collect_codegen_feedback_refs(None) == [],
            "missing code artifact was offered as feedback evidence")

    research_index = CRMSResearchIndex()
    research_index.add_document(
        "helion", "Helion probe notes",
        "The Helion probe measured plasma temperature. "
        "The probe was assembled by the university team.",
        "https://research.test/helion")
    summary_result = research_index.summarize("Helion probe plasma temperature")
    summary_refs = collect_summary_feedback_refs(summary_result)
    require(any(item["kind"] == "source"
                and item["id"].startswith("helion#")
                for item in summary_refs),
            f"summary feedback omitted exact source citation: {summary_refs}")
    expansion_refs = collect_feedback_refs(research={
        "source_sentences": [],
        "query_expansions": [{"kind": "question-frame", "evidence": "frame-1",
                              "text": "probe heat", "sources": ["src-1"],
                              "rules": ["rule-1"]}],
    })
    require({("source", "src-1"), ("rule", "rule-1")} <= {
                (item["kind"], item["id"]) for item in expansion_refs},
            f"summary feedback omitted query-expansion lineage: {expansion_refs}")

    timeline_kb = CRMSKnowledgeBase()
    for subject, obj, source in (("Ada", "Acme", "event:2012"),
                                 ("Grace", "Lab", "event:2013")):
        timeline_kb.add_fact(subject, "founded", obj, source)
        timeline_kb.teach_fact_pattern(
            f"{subject} founded {obj}.", subject=subject, relation="founded",
            obj=obj, source=source, predicate_phrase="founded")
        timeline_kb.teach_about_frame(f"Tell me about {subject}", entity=subject)
    timeline_kb.add_fact("Ada", "founded", "Acme", "event:2012",
                         qualifiers={"year": "2012"})
    timeline_result = timeline_kb.write_timeline("Ada")
    timeline_refs = collect_timeline_feedback_refs(timeline_result)
    require(any(item["kind"] == "fact"
                and item.get("subject") == "Ada"
                and item.get("object") == "Acme"
                and "event:2012" in item.get("sources", ())
                for item in timeline_refs)
            and ("source", "event:2012") in {
                (item["kind"], item["id"]) for item in timeline_refs},
            f"timeline feedback omitted fact or wording-source lineage: {timeline_refs}")
    about_refs = collect_writing_feedback_refs(timeline_kb.write_about("Ada"))
    require(any(item["kind"] == "fact" and item.get("subject") == "Ada"
                and "event:2012" in item.get("sources", ())
                for item in about_refs),
            f"entity writing feedback omitted source-backed claims: {about_refs}")
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
        commands = ("/infer-relation Nia|grandparent|Pia\n/wrong\n/feedback\n"
                    "/inference-rules\n/infer-relation Nia|grandparent|Pia\n/quit\n")
        run = subprocess.run(args, input=commands, text=True, capture_output=True,
                             timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        for phrase in ("Suspended validated learned rule(s) for review",
                       "learned-grandparent [needs_review]",
                       "user marked an answer using it wrong", "Feedback ",
                       "Current rule review signal (held-out learned)",
                       "User-feedback review signal (held-out learned)",
                       "does not alter proof or answer selection"):
            require(phrase in run.stdout,
                    f"interactive feedback omitted {phrase!r}: {run.stdout}")
        require("contradictory source-backed evidence" not in run.stdout,
                "user feedback was described as a verified source counterexample")
        persisted = CRMSKnowledgeBase.load(knowledge_path).list_inference_rules()[0]
        require(persisted["status"] == "needs_review",
                "interactive feedback did not persist rule review status")
        ledger_state = AnswerFeedbackStore(
            root / "feedback.sqlite3").ledger_item(
                "rule", "learned-grandparent")
        require(ledger_state is not None and not ledger_state["protected"]
                and ledger_state["misses"] == 1
                and abs(ledger_state["weight"] - 0.13) < 1e-12,
                f"interactive feedback did not update the learned-rule ledger: "
                f"{ledger_state}")

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

    with tempfile.TemporaryDirectory(prefix="crms-math-feedback-chat-") as directory:
        root = Path(directory)
        math.save(root / "math.json")
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
            args, input="What is 7 plus 3?\n/right\n/feedback\n/quit\n",
            text=True, capture_output=True, timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        events = AnswerFeedbackStore(root / "feedback.sqlite3").recent(1)
        require(len(events) == 1
                and any(item["kind"] == "math_derivation"
                        for item in events[0]["evidence"]),
                f"math feedback lost its derivation attribution: {events}")

    with tempfile.TemporaryDirectory(prefix="crms-code-feedback-chat-") as directory:
        root = Path(directory)
        code_model.save(root / "rules.json")
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
            input=("Can you write Python code to reverse the list?\n"
                   "/wrong\n/feedback\n/quit\n"),
            text=True, capture_output=True, timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        events = AnswerFeedbackStore(root / "feedback.sqlite3").recent(1)
        require(len(events) == 1
                and any(item["kind"] == "code_artifact"
                        for item in events[0]["evidence"]),
                f"code correction lost its generated-artifact attribution: {events}")

    with tempfile.TemporaryDirectory(prefix="crms-summary-feedback-chat-") as directory:
        root = Path(directory)
        research_index.save(root / "index.json")
        args = [sys.executable, str(ROOT / "crms_chat.py"),
                "--knowledge", str(root / "knowledge.json"),
                "--feedback-db", str(root / "feedback.sqlite3"),
                "--dialogue-state", str(root / "dialogue.json"),
                "--rules", str(root / "rules.json"),
                "--rule-session", str(root / "rule-session.json"),
                "--math", str(root / "math.json"),
                "--math-session", str(root / "math-session.json"),
                "--translations", str(root / "translations.json"),
                "--translation-session", str(root / "translation-session.json"),
                "--index", str(root / "index.json")]
        run = subprocess.run(
            args,
            input="/summarize Helion probe plasma temperature\n"
                  "/wrong\n/feedback\n/quit\n",
            text=True, capture_output=True, timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        events = AnswerFeedbackStore(root / "feedback.sqlite3").recent(1)
        require(len(events) == 1
                and any(item["kind"] == "source"
                        and item["id"].startswith("helion#")
                        for item in events[0]["evidence"]),
                f"summary correction lost its source citation: {events}")

    with tempfile.TemporaryDirectory(prefix="crms-paper-feedback-chat-") as directory:
        root = Path(directory)
        paper_index = CRMSResearchIndex()
        paper_index.add_document(
            "helion-study", "Helion Probe Study",
            "Authors: Mira Chen, Dev Patel\n"
            "Abstract: We demonstrate a probe that measures plasma temperature.",
            "https://research.test/helion-study")
        paper_index.save(root / "index.json")
        args = [sys.executable, str(ROOT / "crms_chat.py"),
                "--knowledge", str(root / "knowledge.json"),
                "--feedback-db", str(root / "feedback.sqlite3"),
                "--dialogue-state", str(root / "dialogue.json"),
                "--rules", str(root / "rules.json"),
                "--rule-session", str(root / "rule-session.json"),
                "--math", str(root / "math.json"),
                "--math-session", str(root / "math-session.json"),
                "--translations", str(root / "translations.json"),
                "--translation-session", str(root / "translation-session.json"),
                "--index", str(root / "index.json")]
        run = subprocess.run(
            args,
            input=("Who are the authors of the Helion Probe Study paper?\n"
                   "/right\nWhat is the main result of the Helion Probe Study?\n"
                   "/wrong\n/feedback\n/quit\n"),
            text=True, capture_output=True, timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        events = AnswerFeedbackStore(root / "feedback.sqlite3").events()
        require(len(events) == 2
                and all(any(item["kind"] == "source"
                            and item["id"].startswith("helion-study#")
                            for item in event["evidence"])
                        for event in events),
                f"paper metadata/result feedback lost exact citations: {events}\n"
                f"chat output: {run.stdout}")

    with tempfile.TemporaryDirectory(prefix="crms-timeline-feedback-chat-") as directory:
        root = Path(directory)
        timeline_kb.save(root / "knowledge.json")
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
            input=("Write a timeline for Ada ordered by year.\n/wrong\n"
                   "/write-about Ada\n/right\nTell me about Ada\n/wrong\n"
                   "/feedback\n/quit\n"),
            text=True, capture_output=True, timeout=30)
        require(run.returncode == 0, run.stderr or run.stdout)
        events = AnswerFeedbackStore(root / "feedback.sqlite3").events()
        require(len(events) == 3
                and all(any(item["kind"] == "fact"
                            and item.get("subject") == "Ada"
                            and item.get("object") == "Acme"
                            for item in event["evidence"])
                        and any(item["kind"] == "source"
                                and item["id"] == "event:2012"
                                for item in event["evidence"])
                        for event in events),
                f"grounded writing feedback lost claim/source attribution: {events}\n"
                f"chat output: {run.stdout}")

    print("answer feedback attribution: direct facts, rule, and source refs PASS")
    print("translation feedback ties to deterministic aligned-frame evidence: PASS")
    print("interactive translation feedback persists its frame attribution: PASS")
    print("math feedback ties to deterministic expression and licensed evidence: PASS")
    print("interactive math feedback persists its derivation attribution: PASS")
    print("code feedback ties to artifact provenance and parity evidence: PASS")
    print("interactive code feedback persists artifact attribution: PASS")
    print("summary feedback retains exact citations and expansion lineage: PASS")
    print("interactive summary feedback persists cited sources: PASS")
    print("paper author and main-result feedback retain exact citations: PASS")
    print("timeline feedback retains fact and wording-source lineage: PASS")
    print("interactive timeline and entity-writing feedback retain claims: PASS")
    print("SQLite persistence, deterministic IDs, duplicate suppression: PASS")
    print("conflicting feedback retained for review without changing knowledge: PASS")
    print("wrong proof feedback suspends only validated learned rules: PASS")
    print("rule feedback reason persists; teacher and duplicate signals are protected: PASS")
    print("interactive /wrong suspension and evidence-honest abstention: PASS")
    print("direct-fact feedback is inert until explicit source retraction: PASS")
    print("selected source retracted; feedback audit retained: PASS")


if __name__ == "__main__":
    main()
