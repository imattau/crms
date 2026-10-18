"""Transfer a reviewed irregular verb form into source-grounded object QA."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_chat import _natural_object_wh_form_candidate


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    knowledge = CRMSKnowledgeBase()
    examples = (
        ("Ada Lovelace wrote the first computer program.",
         "Ada Lovelace", "the first computer program"),
        ("Mary Somerville wrote the astronomy book.",
         "Mary Somerville", "the astronomy book"),
    )
    for number, (sentence, subject, object_) in enumerate(examples):
        document_id = f"reviewed-write-{number}"
        index.add_document(document_id, "Reviewed verb-form example",
                           sentence, f"{document_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document_id)
        knowledge.add_fact_from_hit(subject, "write", object_, index, hit)
        knowledge.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="write", obj=object_,
            predicate_phrase="wrote", research_index=index, hit=hit)

    heldout = "Grace Hopper wrote the compiler notes."
    index.add_document("heldout-write", "Held-out writing record",
                       heldout, "heldout-write.txt")
    result = knowledge.research("What did Grace Hopper write?", index)
    require(result.realized_answer is not None
            and result.realized_answer["text"] == heldout
            and result.realized_answer["document_id"] == "heldout-write",
            f"reviewed irregular form did not transfer to source realization: {result}")
    require(any(item.get("kind") == "licensed_predicate"
                and item.get("evidence") == "write"
                and item.get("text") == "wrote"
                for item in result.query_expansions or []),
            "held-out answer omitted the explicit write/wrote learning license")
    heldout_candidate = next((candidate for candidate in result.candidates or []
                              if candidate.subject == "Grace Hopper"
                              and candidate.relation == "write"
                              and candidate.object == "the compiler notes"), None)
    require(heldout_candidate is not None,
            f"held-out source fact was not proposed for review: {result.candidates}")

    # Without reviewed language examples, an unrelated relation must not use
    # the same agent page as evidence for an answer.
    unlicensed = CRMSKnowledgeBase().research(
        "What did Grace Hopper invent?", index)
    require(unlicensed.realized_answer is None,
            f"an unlicensed predicate produced an answer: {unlicensed}")

    with tempfile.TemporaryDirectory(prefix="crms-irregular-inverse-") as temp:
        root = Path(temp)
        knowledge_path, index_path = root / "knowledge.json", root / "research.json"
        knowledge.save(knowledge_path)
        index.save(index_path)
        chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--candidate-session", str(root / "candidates.json"),
             "--rules", str(root / "rules.json"),
             "--rule-session", str(root / "rule-session.json"),
             "--math", str(root / "math.json"),
             "--math-session", str(root / "math-session.json"),
             "--translations", str(root / "translations.json"),
             "--translation-session", str(root / "translation-session.json")],
            input="What did Grace Hopper write?\n/quit\n", text=True,
            capture_output=True, check=False, timeout=30)
        require(chat.returncode == 0
                and heldout in chat.stdout
                and "quoted evidence, not an accepted fact" in chat.stdout,
                "chat did not lead with the cited held-out sentence:\n"
                + chat.stdout + chat.stderr)

    knowledge.accept_fact_candidate(heldout_candidate, index)
    learned_inverse = knowledge.ask("What did Grace Hopper write?")
    require(learned_inverse.status == "answered"
            and learned_inverse.answer == "the compiler notes",
            f"reviewing the fact did not teach its object-question frame: {learned_inverse}")

    # On a corpus with no prior predicate lesson, the exact-title page can
    # generate a review-only vowel-change hypothesis from the question and its
    # source sentence. Acceptance teaches the page-scoped surname span without
    # exporting it as a global entity alias.
    discovery_index = CRMSResearchIndex()
    discovery_index.add_document(
        "ada-page", "Ada Lovelace",
        "Lovelace wrote the first computer program in 1844.", "ada-page.txt")
    discovery_knowledge = CRMSKnowledgeBase()
    discovered = _natural_object_wh_form_candidate(
        discovery_index, "What did Ada Lovelace write?")
    require(discovered is not None
            and discovered.subject == "Ada Lovelace"
            and discovered.relation == "write"
            and discovered.object == "the first computer program"
            and len(discovery_knowledge.facts()) == 0,
            f"corpus did not produce a review-only inflection hypothesis: {discovered}")
    require(_natural_object_wh_form_candidate(
                discovery_index, "What did Ada Lovelace invent?") is None,
            "a consonant-mismatched relation produced a form hypothesis")
    proper_object_index = CRMSResearchIndex()
    proper_object_index.add_document(
        "ada-proper-object", "Ada Lovelace",
        "Lovelace wrote Notes on the Analytical Engine.",
        "ada-proper-object.txt")
    proper_object = _natural_object_wh_form_candidate(
        proper_object_index, "What did Ada Lovelace write?")
    require(proper_object is not None
            and proper_object.object == "Notes on the Analytical Engine",
            f"proper-name object was not retained as one source span: {proper_object}")
    discovery_knowledge.accept_fact_candidate(discovered, discovery_index)
    discovered_answer = discovery_knowledge.ask(
        "What did Ada Lovelace write?")
    require(discovered_answer.status == "answered"
            and discovered_answer.answer == "the first computer program"
            and ("lovelace",) not in discovery_knowledge._entity_aliases,
            "accepted page-scoped verb hypothesis did not teach QA safely")

    with tempfile.TemporaryDirectory(prefix="crms-irregular-discovery-") as temp:
        root = Path(temp)
        discovery_knowledge = CRMSKnowledgeBase()
        discovery_index.save(root / "research.json")
        discovery_knowledge.save(root / "knowledge.json")
        chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "research.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--candidate-session", str(root / "candidates.json"),
             "--rules", str(root / "rules.json"),
             "--rule-session", str(root / "rule-session.json"),
             "--math", str(root / "math.json"),
             "--math-session", str(root / "math-session.json"),
             "--translations", str(root / "translations.json"),
             "--translation-session", str(root / "translation-session.json")],
            input=("What did Ada Lovelace write?\naccept candidate 1\n"
                   "What did Ada Lovelace write?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(chat.returncode == 0
                and "possible wording match on Ada Lovelace" in chat.stdout
                and "Lovelace wrote the first computer program in 1844. "
                    "[Source: Ada Lovelace; accepted fact]" in chat.stdout
                and "Review candidate 1: Ada Lovelace — write → "
                    "the first computer program" in chat.stdout,
                "interactive corpus hypothesis/review/answer loop failed:\n"
                + chat.stdout + chat.stderr)
        persisted = CRMSKnowledgeBase.load(root / "knowledge.json")
        require(("lovelace",) not in persisted._entity_aliases,
                "accepted surname coreference escaped its exact-title source")

    print("reviewed irregular inverse-retrieval diagnostic: PASS")
    print("reviewed write/wrote transfer; unlicensed relation abstention; "
          "corpus hypothesis/review loop; scoped page-title coreference; "
          "object-question learning; CLI answer realization: PASS")


if __name__ == "__main__":
    main()
