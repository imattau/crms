"""Drive natural-language follow-ups against the portable academic corpus.

Run from the project root with:
    python3 experiments/v1_266_large_corpus_chat_followups.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSResearchIndex, CRMSSQLiteResearchIndex
from crms_knowledge import CRMSKnowledgeBase
from crms_chat import _file_sha256, _render_latest_research
from crms_package import install_model_database


_FAILURES: list[str] = []


def require(condition: bool, message: str) -> None:
    """Record a failed probe and keep driving independent chat scenarios."""
    if not condition:
        _FAILURES.append(message)


def _chat(model: Path, root: Path, turns: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--model-db", str(model),
        "--dialogue-state", str(root / "dialogue.json"),
        "--candidate-session", str(root / "candidates.json"),
        "--rule-session", str(root / "rules.json"),
        "--math-session", str(root / "math.json"),
        "--translation-session", str(root / "translations.json"),
    ]
    result = subprocess.run(
        command, input=turns + "/quit\n", text=True, capture_output=True,
        check=False, timeout=120)
    if result.returncode:
        raise AssertionError(
            f"CRMS chat exited {result.returncode}: {result.stderr}\n"
            f"stdout: {result.stdout}")
    return result.stdout


def main() -> None:
    source_model = PROJECT / "data" / "crms_project_model_academic_expanded.sqlite"
    require(source_model.is_file(),
            "expanded portable academic model is missing")

    sentence = "Python was created by Guido van Rossum."
    source = {
        "text": sentence, "context_kind": "assertion",
        "title": "Python history", "citation": "fixture#verified",
        "document_id": "fixture",
    }
    nominal_expansions = [{
        "kind": "agent_noun_spelling_candidate", "text": "created",
        "evidence": "agent noun in question: creator",
    }]
    realized = CRMSKnowledgeBase._realize_question_from_passive_source(
        "Who is the creator of Python?", [source], nominal_expansions)
    require(realized is not None and realized["text"] ==
            "Guido van Rossum created Python.",
            f"bounded passive realization failed: {realized}")
    inverse = CRMSKnowledgeBase._realize_question_from_passive_source(
        "What did Guido van Rossum create?", [source], [])
    require(inverse is not None and inverse["text"] ==
            "Guido van Rossum created Python.",
            f"inverse object question failed: {inverse}")
    active_source = dict(
        source, text="Ada Lovelace designed the Analytical Engine.",
        title="Analytical Engine", citation="fixture#active")
    active_subject = CRMSKnowledgeBase._realize_question_from_passive_source(
        "Who designed the Analytical Engine?", [active_source], [])
    require(active_subject is not None and active_subject["text"] ==
            "Ada Lovelace designed the Analytical Engine.",
            f"active-clause subject realization failed: {active_subject}")
    active_object = CRMSKnowledgeBase._realize_question_from_passive_source(
        "What did Ada Lovelace design?", [active_source], [])
    require(active_object is not None and active_object["text"] ==
            "Ada Lovelace designed the Analytical Engine.",
            f"active-clause object realization failed: {active_object}")
    active_index = CRMSResearchIndex()
    active_index.add_document(
        "active-analytical-engine", "Analytical Engine history",
        active_source["text"], "fixture://active-analytical-engine")
    active_kb = CRMSKnowledgeBase()
    active_result = active_kb.research(
        "Who designed the Analytical Engine?", active_index)
    require(active_result.realized_answer is not None
            and active_result.realized_answer["text"] ==
            "Ada Lovelace designed the Analytical Engine."
            and "active-analytical-engine#sha256="
            in (active_result.realized_answer.get("citation") or ""),
            f"active source realization did not reach research/chat output: {active_result}")
    unlicensed = CRMSKnowledgeBase._realize_question_from_passive_source(
        "What did Guido van Rossum invent?", [source], [])
    require(unlicensed is None,
            f"an unobserved relation synonym was treated as equivalent: {unlicensed}")
    for context, unsafe_question, text in (
            ("example", "Who created Python?", sentence),
            ("assertion", "Who created Python?",
             "Python was not created by Guido van Rossum."),
            ("assertion", "Who created Python?",
             "Python was created by Guido van Rossum, not by Linus Torvalds."),
            ("assertion", "Who designed the Analytical Engine?",
             "Ada Lovelace did not design the Analytical Engine."),
            ("assertion", "Who designed the Analytical Engine?",
             "Ada Lovelace designed the Analytical Engine, not the Compiler."),
            ("assertion", "Who designed the Analytical Engine?",
             "Some programmer designed the Analytical Engine."),
            ("example", "Who designed the Analytical Engine?",
             "Ada Lovelace designed the Analytical Engine."),
            ("ambiguous", "Who designed the Analytical Engine?",
             "Ada Lovelace designed the Analytical Engine.")):
        unsafe = dict(source, context_kind=context, text=text)
        require(CRMSKnowledgeBase._realize_question_from_passive_source(
            unsafe_question, [unsafe], []) is None,
            f"unsafe example or negative context was realized: {unsafe}")

    with tempfile.TemporaryDirectory(prefix="crms-large-chat-followups-") as temp:
        root = Path(temp)
        source_sidecar = root / "source-model.memories"
        install_model_database(source_model, source_sidecar)
        model = root / source_model.name
        shutil.copy2(source_model, model)
        model_sidecar = model.with_name(model.name + ".memories")
        shutil.copytree(source_sidecar, model_sidecar)
        (model_sidecar / ".model.sha256").write_text(
            _file_sha256(model) + "\n", encoding="ascii")
        research = CRMSSQLiteResearchIndex(
            model.with_name(model.name + ".memories") / "research.sqlite")
        try:
            document_count = research.document_count()
            require(document_count >= 1_500,
                    f"large-corpus gate failed: only {document_count} documents")
            _latest_text, _latest_evidence, latest_documents = (
                _render_latest_research(research, "graph theory"))
            require(len(latest_documents) >= 2,
                    "large corpus lacks two dated graph-theory papers for the follow-up probe")
            expected_second_title = latest_documents[1]["title"]
        finally:
            research.close()

        active_root = root / "active-source-chat"
        active_root.mkdir()
        active_model = active_root / source_model.name
        shutil.copy2(source_model, active_model)
        active_sidecar = active_model.with_name(active_model.name + ".memories")
        shutil.copytree(source_sidecar, active_sidecar)
        (active_sidecar / ".model.sha256").write_text(
            _file_sha256(active_model) + "\n", encoding="ascii")
        active_research = CRMSSQLiteResearchIndex(
            active_sidecar / "research.sqlite")
        try:
            active_research.add_document(
                "active-analytical-engine", "Analytical Engine history",
                "Ada Lovelace designed the Analytical Engine.",
                "fixture://active-analytical-engine")
        finally:
            active_research.close()
        active_chat = _chat(
            active_model, active_root / "chat",
            "Who designed the Analytical Engine?\n")
        require("Ada Lovelace designed the Analytical Engine."
                in active_chat
                and "[Source: Analytical Engine history; quoted evidence, "
                    "not an accepted fact]" in active_chat,
                f"active source fact was not clearly cited and labeled: {active_chat}")

        no_context = _chat(
            model, root / "no-context",
            "Who created Python?\nWhy?\n"
            "What is causal forgetting in CRMS?\n"
            "Who is the creator of Python?\n"
            "What did Guido van Rossum create?\n"
            "Which language did Guido van Rossum create?\n"
            "Who created Java?\nWho made Python?\n"
            "What does the second paper say?\n"
            "Is Sydney the capital of Australia?\n")
        require(no_context.count("Guido van Rossum created Python.") >= 3
                and "Illustrative example, not a factual assertion: can extend to" not in no_context,
                f"direct and morphology-derived questions were not realized from the factual source: {no_context}")
        answer_turn, why_turn = no_context.split("you> CRMS> ", 2)[1:3]
        require("Guido van Rossum created Python." in answer_turn
                and "The cited source states:" in why_turn
                and "CRMS prototype" in answer_turn
                and "CRMS prototype" in why_turn,
                f"why follow-up did not retain the preceding answer and source: {no_context}")
        require("causal" in no_context.casefold()
                and "forgetting" in no_context.casefold()
                and "no grounded cardinal value in 'causal forgetting'"
                not in no_context.casefold()
                and "the store can trace which derived knowledge depends"
                in no_context.casefold(),
                f"a definition question was hijacked by unit conversion: {no_context}")
        require(no_context.count(
                    "I couldn't find one source sentence that states who answers that question.") >= 2
                and no_context.count("Guido van Rossum created Python.") >= 3,
                f"unobserved relation wording or missing entity was answered without support: {no_context}")
        require("I don't have a recent paper list to resolve that reference"
                in no_context,
                f"unbound ordinal was turned into a lexical paper match: {no_context}")
        require("copular_yes.status" not in no_context
                and "Sydney is the capital of Australia" not in no_context,
                f"yes/no question surfaced a code fixture or example: {no_context}")

        reasoning_summary = _chat(
            model, root / "reasoning-summary",
            "Summarize the CRMS reasoning design.\n")
        require("CRMS reasoning will be strong on:" in reasoning_summary
                and "CRMS reasoning will be weak on:" in reasoning_summary
                and "[Reasoning as a Capability for CRMS" in reasoning_summary
                and "arXiv metadata API" not in reasoning_summary
                and "Benchmarking and Enhancing Design-Aware" not in reasoning_summary,
                f"topic summary mixed unrelated sources or omitted its core source: {reasoning_summary}")

        routes = _chat(
            model, root / "learning-routes",
            "What are the three learning routes in CRMS?\n")
        require("Teach" in routes and "Induce" in routes and "Derive" in routes
                and ("Current status:" in routes or "Requires teacher?:" in routes)
                and "[Source:" in routes,
                f"list question did not realize the matching source table: {routes}")
        require("Illustrative example" not in routes,
                f"list question selected an unrelated illustrative passage: {routes}")

        retrieval_answer = _chat(
            model, root / "crms-retrieval",
            "What does CRMS say about retrieval?\n")
        require("the expensive operation (retrieval) is also the parallel-friendly one"
                in retrieval_answer
                and "An LLM cannot say" not in retrieval_answer,
                f"retrieval question ranked an unrelated CRMS sentence first: {retrieval_answer}")

        contextual_followup = _chat(
            model, root / "dialogue-topic-carryover",
            "What does CRMS say about retrieval?\n"
            "How does it handle conflicts?\n"
            "What is the latest research in graph theory?\n"
            "How does it handle conflicts?\n")
        require(contextual_followup.count(
                    "Please name the entity this pronoun refers to.") == 1
                and '"ambiguous" when evidence conflicts' in contextual_followup
                and "Held-out validation" not in contextual_followup,
                f"research-topic follow-up used a broad or unresolved referent: {contextual_followup}")

        derivation_loop = _chat(
            model, root / "derivation-loop",
            "How does the derivation loop work?\n")
        require("feedback loop" in derivation_loop.casefold()
                and "retrieve premises" in derivation_loop.casefold()
                and "verify the proof" in derivation_loop.casefold()
                and "[Source:" in derivation_loop
                and "quoted evidence, not an accepted fact" in derivation_loop,
                f"how-question did not recover the matching explanation paragraph: {derivation_loop}")

        verification_risk = _chat(
            model, root / "verification-risk",
            "What risks require verification before storing derived cases?\n")
        require("Verification before write-back" in verification_risk
                and "must pass the consistency check against the fact store"
                in verification_risk,
                f"verification-risk question missed its direct source passage: {verification_risk}")

        wrong_relation = _chat(
            model, root / "wrong-relation",
            "What did Guido van Rossum invent?\n")
        require("Source text:" not in wrong_relation
                and "Python was created" not in wrong_relation,
                f"entity overlap presented a different action as evidence: {wrong_relation}")

        quoted_question = _chat(
            model, root / "quoted-question",
            "Where does Alan Turing work?\n")
        require(("I don't know this from the sources and facts I have"
                 in quoted_question
                 or "I couldn't find a work location statement" in quoted_question)
                and "Source: CRMS prototype" not in quoted_question,
                f"an illustrative question example was treated as factual evidence: {quoted_question}")

        acronym_anchor = _chat(
            model, root / "acronym-anchor",
            "How does CRMS learn language?\n")
        require("DBLSTM" not in acronym_anchor
                and "CRMS can also learn a sequential connective from examples"
                in acronym_anchor
                and "Source: CRMS prototype" in acronym_anchor,
                f"CRMS-specific question did not use its grounded prototype passage: {acronym_anchor}")
        definition = _chat(model, root / "definition", "What is CRMS?\n")
        require("CRMS is a deterministic, evidence-grounded prototype" in definition
                and "reasoning layer is the most carefully built" not in definition,
                f"definition question selected a mere mention: {definition}")

        ordinal = _chat(
            model, root / "ordinal",
            "What is the latest research in graph theory?\n"
            "What does the second paper say?\n")
        require(expected_second_title in ordinal
                and "Extractive summary for: " + expected_second_title in ordinal,
                f"ordinal follow-up did not select the second listed paper: {ordinal}")
        require("Understanding the second quantization of fermions" not in ordinal,
                f"ordinal follow-up drifted to an unrelated lexical match: {ordinal}")

        comparison = _chat(
            model, root / "comparison",
            "What is the latest research in graph theory?\n"
            "What do these papers agree on?\n")
        require("I can't establish agreement from the abstracts" in comparison
                and expected_second_title in comparison,
                f"comparison follow-up did not preserve paper-list context: {comparison}")
        require("Predicting Software Effort from Use Case Points" not in comparison,
                f"comparison follow-up retrieved an unrelated passage: {comparison}")

    if _FAILURES:
        print(f"large-corpus natural-language chat follow-ups: "
              f"{len(_FAILURES)} finding(s)")
        for number, failure in enumerate(_FAILURES, start=1):
            print(f"\nFINDING {number}: {failure}")
        raise SystemExit(1)

    print("large-corpus natural-language chat follow-ups: PASS")
    print(f"portable model documents={document_count}; factual-source retrieval, "
          "controlled forward/inverse passive realization, agent-noun morphology, "
          "table-list realization, how-answer paragraph recovery, verification-risk "
          "retrieval, research-topic pronoun carryover and reset, unsafe-context "
          "rejection, yes/no code/example guard, "
          "unbound ordinal clarification, contextual second-paper summary, "
          "and comparison abstention: PASS")


if __name__ == "__main__":
    main()
