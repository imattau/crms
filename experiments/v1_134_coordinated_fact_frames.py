"""Compose learned sentence frames across independently grounded clauses.

Run from the project root with:
    python3 experiments/v1_134_coordinated_fact_frames.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    knowledge = CRMSKnowledgeBase()
    training = (
        ("Ada Lovelace", "designed", "the Analytical Engine",
         "Ada Lovelace designed the Analytical Engine.", "design-a"),
        ("Grace Hopper", "designed", "the Compiler",
         "Grace Hopper designed the Compiler.", "design-b"),
        ("Katherine Johnson", "built", "the Trajectory Table",
         "Katherine Johnson built the Trajectory Table.", "build-a"),
        ("James Watt", "built", "the Difference Engine",
         "James Watt built the Difference Engine.", "build-b"),
    )
    for subject, relation, obj, sentence, document_id in training:
        index.add_document(document_id, document_id, sentence,
                           f"https://research.test/{document_id}")
        hit = next(hit for hit in index.search(sentence, limit=10)
                   if hit.document_id == document_id)
        knowledge.add_fact_from_hit(subject, relation, obj, index, hit)
        knowledge.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation=relation, obj=obj,
            research_index=index, hit=hit, predicate_phrase=relation)

    sentence = (
        "Ada Lovelace designed the Analytical Engine and Grace Hopper built "
        "the Trajectory Table.")
    index.add_document("compound", "Compound source", sentence,
                       "https://research.test/compound")
    hit = next(hit for hit in index.search(sentence, limit=10)
               if hit.document_id == "compound")
    proposals = knowledge.propose_facts_from_hit(
        sentence, research_index=index, hit=hit)
    actual = {(candidate.subject, candidate.relation, candidate.object)
              for candidate in proposals}
    expected = {
        ("Ada Lovelace", "designed", "the Analytical Engine"),
        ("Grace Hopper", "built", "the Trajectory Table"),
    }
    if actual != expected:
        raise SystemExit(f"coordinated clause extraction failed: {actual}")
    citation = index.citation(hit)
    if any(candidate.source != citation or candidate.sentence != sentence
           for candidate in proposals):
        raise SystemExit("coordinated proposals lost the cited sentence")

    elliptical_sentence = (
        "Ada Lovelace designed the Analytical Engine and built the Compiler.")
    elliptical = knowledge.propose_facts(
        elliptical_sentence, source="source:elliptical")
    elliptical_claims = {
        (candidate.subject, candidate.relation, candidate.object)
        for candidate in elliptical
    }
    if elliptical_claims != {
            ("Ada Lovelace", "designed", "the Analytical Engine"),
            ("Ada Lovelace", "built", "the Compiler")}:
        raise SystemExit(f"shared-subject recovery failed: {elliptical_claims}")
    if any(candidate.sentence != elliptical_sentence for candidate in elliptical):
        raise SystemExit("shared-subject proposals lost the original sentence")

    shared_predicate_sentence = (
        "Ada Lovelace designed the Analytical Engine and the Compiler.")
    shared_predicate = knowledge.propose_facts(
        shared_predicate_sentence, source="source:shared-predicate")
    shared_predicate_claims = {
        (candidate.subject, candidate.relation, candidate.object)
        for candidate in shared_predicate
    }
    if shared_predicate_claims != {
            ("Ada Lovelace", "designed", "the Analytical Engine"),
            ("Ada Lovelace", "designed", "the Compiler")}:
        raise SystemExit(
            f"shared-predicate recovery failed: {shared_predicate_claims}")
    index.add_document("shared-predicate", "Shared predicate source",
                       shared_predicate_sentence,
                       "https://research.test/shared-predicate")
    shared_research = knowledge.research(shared_predicate_sentence, index)
    shared_research_claims = {
        (candidate.subject, candidate.relation, candidate.object)
        for candidate in shared_research.candidates or []
    }
    if (shared_research.status != "needs_review"
            or ("Ada Lovelace", "designed", "the Compiler")
            not in shared_research_claims):
        raise SystemExit(
            f"research lost the shared-predicate proposal: {shared_research}")

    if len(knowledge.facts()) != len(training):
        raise SystemExit("review-only coordinated proposals were auto-committed")

    research = knowledge.research(sentence, index)
    researched = {(candidate.subject, candidate.relation, candidate.object)
                  for candidate in research.candidates or []}
    # Research review is question-focused: the directly matching second
    # clause is proposed, while a neighboring source claim about a different
    # object is not appended as unrelated review debris.
    new_claims = {
        ("Grace Hopper", "built", "the Trajectory Table"),
    }
    if research.status != "needs_review" or not new_claims <= researched:
        raise SystemExit(
            f"research did not expose coordinated proposals for review: {research}")
    if len(knowledge.facts()) != len(training):
        raise SystemExit("research promoted a coordinated proposal automatically")
    accepted_candidate = next(
        candidate for candidate in research.candidates or []
        if (candidate.subject, candidate.relation, candidate.object)
        == ("Grace Hopper", "built", "the Trajectory Table"))
    accepted = knowledge.accept_fact_candidate(accepted_candidate, index)
    if (accepted.sources != (citation,)
            or len(knowledge.facts()) != len(training) + 1):
        raise SystemExit("accepted coordinated claim lost exact citation provenance")

    three_clause_sentence = (
        "Ada Lovelace designed the Analytical Engine and Grace Hopper built "
        "the Trajectory Table and James Watt built the Difference Engine.")
    three = knowledge.propose_facts(
        three_clause_sentence, source="source:three-clauses")
    if len(three) != 3 or {candidate.relation for candidate in three} != {
            "designed", "built"}:
        raise SystemExit(f"three-clause composition failed: {three}")
    if any(candidate.sentence != three_clause_sentence for candidate in three):
        raise SystemExit("nested coordination did not preserve original evidence")

    at_limit = " and ".join(
        "Ada Lovelace designed the Analytical Engine" for _ in range(9))
    at_limit_candidates = knowledge.propose_facts(
        at_limit, source="source:at-limit")
    if len(at_limit_candidates) != 1:
        raise SystemExit("maximum supported coordination did not complete")

    over_limit = " and ".join(
        "Ada Lovelace designed the Analytical Engine" for _ in range(10))
    if knowledge.propose_facts(over_limit, source="source:large"):
        raise SystemExit("over-limit coordination did not abstain")

    print("coordinated fact-frame diagnostic: PASS")
    print("two/three clauses, shared-subject/predicate recovery, research review, selective acceptance: PASS")


if __name__ == "__main__":
    main()
