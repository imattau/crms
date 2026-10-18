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
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_chain(kb: CRMSKnowledgeBase, number: int, partition: str,
              *, labeled: bool = True) -> None:
    subject = f"person {number:04d}a"
    middle = f"person {number:04d}b"
    target = f"person {number:04d}c"
    source = f"{partition}:{number:04d}"
    kb.add_fact(subject, "parent", middle, source + "#first")
    kb.add_fact(middle, "parent", target, source + "#second")
    if labeled:
        kb.add_fact(subject, "ancestor", target, source + "#label")


def main() -> None:
    kb = CRMSKnowledgeBase()
    for number in range(40):
        add_chain(kb, number, "training")
    for number in range(40, 52):
        add_chain(kb, number, "validation")
    for number in range(52, 64):
        add_chain(kb, number, "unlabeled", labeled=False)

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

    candidate_number = review.reviews.index(target_review) + 1
    acceptance = kb.accept_inference_rule_candidate(
        candidate_number, "parent-transitivity", "validation:",
        min_support=2, min_validation_support=8, max_expansions=250_000)
    require(acceptance.accepted and acceptance.rule is not None,
            f"reviewed rule was not accepted: {acceptance}")

    results = []
    for number in range(52, 64):
        subject = f"person {number:04d}a"
        target_entity = f"person {number:04d}c"
        result = kb.infer_relation(subject, "ancestor", target_entity)
        require(result.status == "answered" and result.complete and result.proofs,
                f"accepted rule did not generalize to unlabeled pair {number}: {result}")
        results.append(result)

    facts = [asdict(fact) for fact in kb.facts()]
    rules = [asdict(rule) for rule in kb._inference_rules.values()]
    proof_count = 0
    for result in results:
        for proof in result.proofs:
            checked = verify_inference_proof(
                proof, facts, rules, expected_conclusion=result.conclusion)
            require(checked.valid, f"independent proof check failed: {checked}")
            proof_count += 1

    print("large-scale self-learning rule diagnostic: PASS")
    print(f"facts={len(kb.facts())}; candidates={len(discovery.candidates)}; "
          f"discovery_expansions={discovery.expansions}; "
          f"discovery_seconds={elapsed:.3f}")
    print("review split: training=40 labeled pairs; "
          "heldout=12 independent labeled pairs; "
          "unlabeled transfer=12 pairs")
    print(f"unlabeled_answers=12; independently_verified_proofs={proof_count}; "
          "explicit_review_gate=PASS")


if __name__ == "__main__":
    main()
