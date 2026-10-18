"""Discover and validate relation rules without crossing qualifier scopes."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def add_chain(kb: CRMSKnowledgeBase, subject: str, middle: str,
              target: str, source: str, year: str, *, label: str = "positive") -> None:
    scope = {"year": year}
    kb.add_fact(subject, "parent", middle, f"{source}#p1", qualifiers=scope)
    kb.add_fact(middle, "parent", target, f"{source}#p2", qualifiers=scope)
    if label == "positive":
        kb.add_fact(subject, "ancestor", target, f"{source}#label", qualifiers=scope)
    elif label == "negative":
        kb.add_negative_fact(subject, "ancestor", target, f"{source}#label",
                             qualifiers=scope)


def candidate_for(kb: CRMSKnowledgeBase):
    return next((candidate for candidate in
                 kb.discover_inference_rules().candidates
                 if (candidate.first_relation, candidate.second_relation,
                     candidate.conclusion_relation)
                 == ("parent", "parent", "ancestor")), None)


def main() -> None:
    kb = CRMSKnowledgeBase()
    add_chain(kb, "Ada", "Bea", "Cal", "train:one", "2024")
    add_chain(kb, "Dee", "Eli", "Fay", "train:two", "2025")
    add_chain(kb, "Gus", "Hal", "Ivy", "holdout:one", "2026")
    add_chain(kb, "Jo", "Kim", "Lou", "holdout:two", "2027")
    add_chain(kb, "Nia", "Oren", "Pia", "runtime", "2028", label="none")
    # These endpoints are labeled in 2030, but one premise belongs to 2031.
    kb.add_fact("Rick", "parent", "Sam", "cross#first", qualifiers={"year": "2030"})
    kb.add_fact("Sam", "parent", "Tom", "cross#second", qualifiers={"year": "2031"})
    kb.add_fact("Rick", "ancestor", "Tom", "cross#label", qualifiers={"year": "2030"})

    candidate = candidate_for(kb)
    if candidate is None or candidate.status != "uncontradicted":
        raise SystemExit(f"exact-scope candidate was not discovered: {candidate}")
    if (len(candidate.positive_examples) != 4
            or candidate.independent_sources != ("holdout:one", "holdout:two",
                                                   "train:one", "train:two")):
        raise SystemExit("candidate support included a cross-context or duplicate example")
    if any(example["first"].get("qualifiers") != example["second"].get("qualifiers")
           or example["first"].get("qualifiers") != example["conclusion"].get("qualifiers")
           for example in candidate.positive_examples):
        raise SystemExit("candidate evidence lost its exact qualifier scope")
    discovery_text = kb.render_rule_discovery(kb.discover_inference_rules())
    if "support (context: year=2024)" not in discovery_text:
        raise SystemExit("rule discovery display hid candidate context")

    reviewed = kb.review_inference_rules("holdout:")
    if (not reviewed.complete or len(reviewed.reviews) != 1
            or reviewed.reviews[0].validation is None
            or reviewed.reviews[0].validation.status != "validated"):
        raise SystemExit(f"contextual held-out rule did not validate: {reviewed}")
    if "holdout-positive (context: year=2026)" not in kb.render_rule_reviews(reviewed):
        raise SystemExit("held-out rule review display hid candidate context")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        cli = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json")],
            input="/suggest-inference-rules 2|holdout:\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20)
        if "holdout-positive (context: year=2026)" not in cli.stdout:
            raise SystemExit(f"CLI rule review hid contextual evidence:\n{cli.stdout}")
    accepted = kb.accept_inference_rule_candidate(
        1, "parent-transitivity", "holdout:")
    if not accepted.accepted:
        raise SystemExit(f"source-separated contextual rule was rejected: {accepted}")
    runtime = kb.infer_relation(
        "Nia", "ancestor", "Pia", qualifiers={"year": "2028"})
    if runtime.status != "answered":
        raise SystemExit("accepted contextual rule failed on an unseen endpoint pair")

    contradicted = CRMSKnowledgeBase()
    add_chain(contradicted, "Ada", "Bea", "Cal", "one", "2024")
    add_chain(contradicted, "Dee", "Eli", "Fay", "two", "2025")
    contradicted.add_negative_fact(
        "Ada", "ancestor", "Cal", "other-scope#negative",
        qualifiers={"year": "2026"})
    separate_scope = candidate_for(contradicted)
    if separate_scope is None or separate_scope.status != "uncontradicted":
        raise SystemExit("different-scope negative label contradicted the rule")
    contradicted.add_negative_fact(
        "Ada", "ancestor", "Cal", "same-scope:negative",
        qualifiers={"year": "2024"})
    same_scope = candidate_for(contradicted)
    if same_scope is None or same_scope.status != "contradicted":
        raise SystemExit("same-scope negative label did not contradict the rule")

    print("contextual rule discovery diagnostic: PASS")
    print("exact-scope support, source-separated validation, unseen-context use, scoped counterexamples: PASS")


if __name__ == "__main__":
    main()
