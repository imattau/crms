"""Stress source-separated rule discovery with a larger symbolic knowledge base.

Builds many disjoint chains and unrelated facts, proposes a rule from one
source partition, validates it on another, then checks rule use and proof
verification on endpoint pairs whose conclusions were never taught.

Run from the project root with:
    python3 experiments/v1_297_large_scale_rule_learning.py
"""
from __future__ import annotations

from dataclasses import asdict
import time
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_source_fact(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                    source_id: str, sentence: str, subject: str,
                    relation: str, obj: str, *, teach: bool = False) -> None:
    index.add_document(source_id, "Generated relational record", sentence,
                       source_id + ".txt")
    hit = next((row for row in index.search(sentence, limit=10)
                if row.document_id == source_id), None)
    require(hit is not None, f"indexed source was not retrievable: {source_id}")
    if teach:
        kb.add_fact_from_hit(subject, relation, obj, index, hit)
        predicate = "mentored" if relation == "parent" else "guided"
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation=relation, obj=obj,
            predicate_phrase=predicate, research_index=index, hit=hit)
        return

    candidates = kb.propose_facts_from_hit(
        sentence, research_index=index, hit=hit)
    candidate = next((item for item in candidates
                      if (item.subject, item.relation, item.object)
                      == (subject, relation, obj)), None)
    require(candidate is not None,
            f"learned language frames did not extract {sentence!r}: {candidates}")
    before = len(kb.facts())
    kb.accept_fact_candidate(candidate, index)
    require(len(kb.facts()) == before + 1,
            "reviewed source extraction did not add exactly one fact")


def add_chain(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
              number: int, partition: str, *, labeled: bool = True,
              teach: bool = False) -> None:
    subject = f"Person{number:04d}A"
    middle = f"Person{number:04d}B"
    target = f"Person{number:04d}C"
    source = f"{partition}:{number:04d}"
    rows = [
        ("first", f"{subject} mentored {middle}.", subject, "parent", middle),
        ("second", f"{middle} mentored {target}.", middle, "parent", target),
    ]
    if labeled:
        rows.append(("label", f"{subject} guided {target}.", subject,
                     "ancestor", target))
    for suffix, sentence, left, relation, right in rows:
        add_source_fact(kb, index, source + ":" + suffix, sentence,
                        left, relation, right, teach=teach)
    group = f"Group{number:04d}"
    region = f"Region{number:04d}"
    linked_source = f"linked:{partition}:{number:04d}"
    kb.add_fact(subject, "member-of", group, linked_source + "#membership")
    kb.add_fact(group, "located-in", region, linked_source + "#location")
    if labeled:
        kb.add_fact(subject, "has-region", region, linked_source + "#label")


def add_linked_counterexample(kb: CRMSKnowledgeBase) -> None:
    subject, group, region = "Person9999A", "Group9999", "Region9999"
    source = "validation:linked-counterexample"
    kb.add_fact(subject, "member-of", group, source + "#membership")
    kb.add_fact(group, "located-in", region, source + "#location")
    kb.add_negative_fact(subject, "has-region", region, source + "#negative")


def main() -> None:
    kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    for number in range(40):
        # The first two chains teach the two sentence-to-relation frames from
        # cited examples. Later claims must pass through learned extraction.
        add_chain(kb, index, number, "training", teach=number < 2)
    for number in range(40, 52):
        add_chain(kb, index, number, "validation")
    for number in range(52, 64):
        add_chain(kb, index, number, "unlabeled", labeled=False)
    add_linked_counterexample(kb)

    # Add disconnected background facts to ensure discovery runs against a
    # nontrivial store without introducing accidental chain examples.
    for number in range(800):
        kb.add_fact(f"artifact {number:04d}", "described-by",
                    f"record {number:04d}", f"background:{number:04d}")

    started = time.perf_counter()
    discovery = kb.discover_inference_rules(
        min_support=2, max_expansions=250_000)
    elapsed = time.perf_counter() - started
    require(discovery.complete,
            f"candidate discovery exhausted its bound: {discovery.expansions}")
    target = next((candidate for candidate in discovery.candidates
                   if (candidate.first_relation, candidate.second_relation,
                       candidate.conclusion_relation)
                   == ("parent", "parent", "ancestor")), None)
    require(target is not None and target.status == "uncontradicted",
            f"planted rule was not proposed cleanly: {target}")
    linked_candidate = next((candidate for candidate in discovery.candidates
                             if (candidate.first_relation,
                                 candidate.second_relation,
                                 candidate.conclusion_relation)
                             == ("member-of", "located-in", "has-region")), None)
    require(linked_candidate is not None
            and linked_candidate.status == "contradicted"
            and len(linked_candidate.negative_examples) == 1,
            f"linked decoy or its counterexample was not surfaced: {linked_candidate}")
    require(len(target.positive_examples) == 52,
            f"unexpected training support: {len(target.positive_examples)}")

    review = kb.review_inference_rules(
        "validation:", min_support=2, min_validation_support=8,
        max_expansions=250_000)
    require(review.complete, "source-held-out review exhausted its bound")
    target_review = next((item for item in review.reviews
                          if (item.candidate.first_relation,
                              item.candidate.second_relation,
                              item.candidate.conclusion_relation)
                          == ("parent", "parent", "ancestor")), None)
    require(target_review is not None
            and len(target_review.candidate.positive_examples) == 40
            and target_review.validation is not None
            and target_review.validation.status == "validated"
            and len(target_review.validation.positive_examples) == 12,
            f"held-out rule failed its independent-source gate: {target_review}")
    linked_review = next((item for item in review.reviews
                          if (item.candidate.first_relation,
                              item.candidate.second_relation,
                              item.candidate.conclusion_relation)
                          == ("member-of", "located-in", "has-region")), None)
    require(linked_review is not None
            and linked_review.validation is not None
            and linked_review.validation.status == "contradicted"
            and len(linked_review.validation.negative_examples) == 1,
            f"held-out linked counterexample did not block the decoy rule: {linked_review}")

    candidate_number = review.reviews.index(target_review) + 1
    acceptance = kb.accept_inference_rule_candidate(
        candidate_number, "parent-transitivity", "validation:",
        min_support=2, min_validation_support=8, max_expansions=250_000)
    require(acceptance.accepted and acceptance.rule is not None,
            f"reviewed rule was not accepted: {acceptance}")

    results = []
    for number in range(52, 64):
        subject = f"Person{number:04d}A"
        target_entity = f"Person{number:04d}C"
        result = kb.infer_relation(subject, "ancestor", target_entity)
        require(result.status == "answered" and result.complete and result.proofs,
                f"accepted rule did not generalize to unlabeled pair {number}: {result}")
        results.append(result)
        rejected_decoy = kb.infer_relation(
            subject, "has-region", f"Region{number:04d}")
        require(rejected_decoy.status == "unknown",
                f"counterexample-rejected rule was unexpectedly installed: {rejected_decoy}")

    facts = [asdict(fact) for fact in kb.facts()]
    rules = [asdict(rule) for rule in kb._inference_rules.values()]
    proof_count = 0
    for result in results:
        for proof in result.proofs:
            checked = verify_inference_proof(
                proof, facts, rules, expected_conclusion=result.conclusion)
            require(checked.valid, f"independent proof check failed: {checked}")
            proof_count += 1

    print("large-scale language-to-rule learning diagnostic: PASS")
    print(f"facts={len(kb.facts())}; indexed_sources={len(index.documents())}; "
          f"candidates={len(discovery.candidates)}; "
          f"discovery_expansions={discovery.expansions}; "
          f"discovery_seconds={elapsed:.3f}")
    print("two cited examples per relation licensed the language frames; "
          "all later chain claims entered through reviewed extraction")
    print("review split: training=40 labeled pairs; "
          "heldout=12 independent labeled pairs; "
          "unlabeled transfer=12 pairs")
    print("linked candidate=member-of + located-in -> has-region; "
          "one held-out negative blocked installation; runtime abstained")
    print(f"unlabeled_answers=12; independently_verified_proofs={proof_count}; "
          "explicit_review_gate=PASS")


if __name__ == "__main__":
    main()
