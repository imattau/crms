"""Find exact, review-only source evidence for a concrete missing premise.

Objective: connect bounded reasoning gaps to indexed evidence without
loosening language or relation matching.
Setup: a two-premise grandparent rule has one accepted parent premise; the
indexed corpus contains the exact missing premise plus reversed and unrelated
sentences.
Metrics: exact candidates returned, citation validity, and proof completion
after explicit acceptance.
Failure modes: proposing a reversed or wrong-relation sentence, proposing
without a licensed frame, accepting an unverified fact, or failing to complete
the derivation after acceptance.
Definition of success: only the exact frame-parsed sentence is proposed;
without that frame no candidate is offered; accepting the proposal completes a
proof-checked inference.

Run from the project root with:
    python3 experiments/v1_296_missing_premise_source_followup.py
"""

from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import (
    _follow_missing_premise_sources,
    _missing_premise_source_candidates,
)
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_knowledge(*, teach_frame: bool) -> CRMSKnowledgeBase:
    knowledge = CRMSKnowledgeBase()
    knowledge.add_fact("Ada", "parent of", "Bea", "teacher:ada-bea")
    knowledge.add_fact("Grace", "parent of", "Hopper", "teacher:grace-hopper")
    if teach_frame:
        knowledge.teach_fact_pattern(
            "Ada is parent of Bea.", subject="Ada", relation="parent of",
            obj="Bea", source="teacher:ada-bea",
            predicate_phrase="is parent of")
        knowledge.teach_fact_pattern(
            "Grace is parent of Hopper.", subject="Grace",
            relation="parent of", obj="Hopper", source="teacher:grace-hopper",
            predicate_phrase="is parent of")
    knowledge.add_inference_rule(
        "grandparent", "parent of", "parent of", "grandparent of")
    if teach_frame:
        knowledge.add_fact("Ruth", "grandparent of", "Nina", "teacher:ruth-nina")
        knowledge.add_fact("Tess", "grandparent of", "Omar", "teacher:tess-omar")
        knowledge.teach_question(
            "Who is grandparent of Nina?", relation="grandparent of",
            answer_field="subject", bound_entity="Nina", answer="Ruth")
        knowledge.teach_question(
            "Who is grandparent of Omar?", relation="grandparent of",
            answer_field="subject", bound_entity="Omar", answer="Tess")
    return knowledge


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document(
        "gap-source", "Family notes",
        "Bea is parent of Cal. Cal is parent of Bea. Bea raised Cal.",
        "https://research.test/family")
    knowledge = make_knowledge(teach_frame=True)
    initial = knowledge.infer_relation("Ada", "grandparent of", "Cal")
    require(initial.failure_kind == "missing_premise"
            and initial.missing_premises,
            f"fixture did not expose a concrete missing premise: {initial}")

    candidates = _missing_premise_source_candidates(
        knowledge, index, list(initial.missing_premises))
    require(len(candidates) == 1,
            f"reversed or wrong-relation evidence was proposed: {candidates}")
    candidate = candidates[0]
    require((candidate.subject, candidate.relation, candidate.object,
             candidate.sentence) == (
                 "Bea", "parent of", "Cal", "Bea is parent of Cal."),
            f"source candidate did not match the missing premise exactly: {candidate}")
    require(candidate.sentence in index.resolve_citation(candidate.source),
            "candidate citation does not resolve to its exact source sentence")

    turn = CRMSDialogue(knowledge).turn(
        "Who is grandparent of Cal?", research_index=index)
    require(turn.response is not None
            and turn.response.reason_code == "missing_premise"
            and turn.research is not None,
            f"natural-language question did not expose its missing premise: {turn}")
    reply = _follow_missing_premise_sources(
        knowledge, index, turn.response, turn.research, turn.text)
    require(turn.research.status == "needs_review"
            and len(turn.research.candidates or []) == 1
            and turn.research.candidates[0].sentence == candidate.sentence
            and candidate.sentence in reply
            and "Family notes" in reply,
            f"missing-premise candidate was not attached for review: {reply}")

    no_frame = make_knowledge(teach_frame=False)
    require(not _missing_premise_source_candidates(
        no_frame, index, list(initial.missing_premises)),
        "source retrieval proposed a fact without an accepted frame")
    distractors = CRMSResearchIndex()
    distractors.add_document(
        "distractors", "Distractor notes",
        "Cal is parent of Bea. Bea raised Cal.",
        "https://research.test/distractors")
    require(not _missing_premise_source_candidates(
        knowledge, distractors, list(initial.missing_premises)),
        "source retrieval proposed a missing premise absent from the corpus")

    knowledge.accept_fact_candidate(turn.research.candidates[0], index)
    completed = knowledge.infer_relation("Ada", "grandparent of", "Cal")
    require(completed.status == "answered" and completed.proofs,
            f"accepted missing premise did not complete inference: {completed}")
    facts = [asdict(fact) for fact in knowledge.facts()]
    rules = [asdict(rule) for rule in knowledge._inference_rules.values()]
    for proof in completed.proofs:
        check = verify_inference_proof(
            proof, facts, rules, expected_conclusion=completed.conclusion)
        require(check.valid, f"completed derivation failed proof checking: {check}")

    print("missing-premise source follow-through diagnostic: PASS")
    print("exact licensed parse, reversed/wrong-relation rejection, no-frame abstention, "
          "review acceptance, and verified derivation: PASS")


if __name__ == "__main__":
    main()
