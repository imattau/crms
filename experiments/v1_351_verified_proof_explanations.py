"""Verify, render, and round-trip explanatory text for inference proofs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_explain import render_verified_explanation
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    structured_fallbacks = 0
    incomplete_results = 0
    proved = 0
    for case in range(31):
        depth = case % 5 + 1
        hops = depth + 1
        kb = CRMSKnowledgeBase()
        for index in range(hops):
            kb.add_fact(f"Case {case} Node {index}", "great-grandparent",
                        f"Case {case} Node {index + 1}",
                        f"edge:{case}:{index}")
        kb.add_relation_type("great-grandparent", "transitive", "schema:great")
        result = kb.infer_relation(
            f"Case {case} Node 0", "great grandparent",
            f"Case {case} Node {hops}")
        require(result.status == "answered" and result.proofs,
                f"depth {depth} did not prove: {result.status}")
        if not result.complete:
            incomplete_results += 1
        explanation = render_verified_explanation(
            kb, result.proofs[0], complete=result.complete)
        require(explanation is not None,
                f"depth {depth} proof was not rendered after verification")
        require(explanation.startswith(
            f"Case {case} Node 0 — great-grandparent → "),
                f"depth {depth} answer did not use structured fallback")
        structured_fallbacks += 1
        # Answer + edge facts + relation-schema license + inference step.
        expected_paragraphs = 1 + hops + 1 + 1 + (not result.complete)
        require(len(explanation.split("\n\n")) == expected_paragraphs,
                f"depth {depth} had wrong paragraph count")
        require(explanation == render_verified_explanation(
            kb, result.proofs[0], complete=result.complete),
            f"depth {depth} rendering was not deterministic")

        tampered = dict(result.proofs[0])
        tampered["conclusion"] = dict(tampered["conclusion"], object="Forged")
        require(render_verified_explanation(kb, tampered) is None,
                f"depth {depth} tampered proof was rendered")
        proved += 1

    no_proof = CRMSKnowledgeBase()
    no_proof.add_fact("A", "great-grandparent", "B", "edge:a-b")
    no_proof.add_relation_type("great-grandparent", "transitive", "schema")
    missing = no_proof.infer_relation("A", "great-grandparent", "C")
    require(missing.status == "unknown" and not missing.proofs,
            "unprovable conclusion unexpectedly had a proof")

    # The explicit relation spelling in structured explanations must parse
    # back through the same proposal API used for ordinary source sentences.
    proposals = no_proof.propose_facts(
        "A — great-grandparent → C", source="explanation:test")
    require(len(proposals) == 1
            and proposals[0].relation == "great-grandparent",
            "structured explanation did not round-trip through propose_facts")

    worded = CRMSKnowledgeBase()
    for subject, middle, target, label in (
            ("Ada", "Bea", "Cal", "one"),
            ("Dee", "Eli", "Fay", "two"),
            ("Nia", "Oren", "Pia", "three")):
        worded.add_fact(subject, "parent", middle, f"{label}:parent-1")
        worded.add_fact(middle, "parent", target, f"{label}:parent-2")
    for subject, target, label in (("Ada", "Cal", "one"),
                                   ("Dee", "Fay", "two")):
        worded.add_fact(subject, "grandparent", target, f"{label}:grandparent")
        worded.teach_fact_pattern(
            f"{subject} is a grandparent of {target}.",
            subject=subject, relation="grandparent", obj=target,
            source=f"{label}:grandparent", predicate_phrase="is a grandparent of")
    worded.add_inference_rule(
        "parent-to-grandparent", "parent", "parent", "grandparent")
    inferred = worded.infer_relation("Nia", "grandparent", "Pia")
    require(inferred.status == "answered" and inferred.proofs,
            "worded relation setup did not prove the held-out claim")
    realized = render_verified_explanation(
        worded, inferred.proofs[0], complete=inferred.complete)
    require(realized is not None
            and realized.startswith("Nia is a grandparent of Pia."),
            f"licensed wording was not selected and round-tripped: {realized}")

    typed = CRMSKnowledgeBase()
    typed.add_fact("Nia", "parent", "Oren", "typed:first")
    typed.add_fact("Oren", "parent", "Pia", "typed:second")
    typed.add_fact("Oren", "is-a", "person", "typed:kind")
    typed.add_inference_rule(
        "typed-grandparent", "parent", "parent", "grandparent",
        middle_kind="person")
    typed_result = typed.infer_relation("Nia", "grandparent", "Pia")
    require(typed_result.status == "answered" and typed_result.proofs,
            "typed rule did not establish its conclusion")
    typed_text = render_verified_explanation(
        typed, typed_result.proofs[0], complete=typed_result.complete)
    require(typed_text is not None
            and "Oren — is-a → person" in typed_text
            and "typed:kind" in typed_text,
            f"typed premise was omitted from explanation: {typed_text}")

    partial = CRMSKnowledgeBase()
    partial.add_fact("Open A", "connected", "Open B", "open:one")
    partial.add_fact("Open B", "connected", "Open C", "open:two")
    partial.add_fact("Open A", "alias", "Elsewhere", "open:alias")
    partial.add_inference_rule("feed-connected", "alias", "connected",
                               "connected")
    partial.add_relation_type("connected", "transitive", "schema:connected")
    partial_result = partial.infer_relation("Open A", "connected", "Open C")
    require(partial_result.status == "answered" and not partial_result.complete,
            "feeding rule did not mark omitted alternatives as incomplete")
    partial_explanation = render_verified_explanation(
        partial, partial_result.proofs[0], complete=partial_result.complete)
    require(partial_explanation is not None
            and "Other proofs may exist" in partial_explanation,
            "incomplete proof explanation omitted the alternatives note")
    incomplete_results += 1

    print(f"proof explanation: {proved}/31 conclusions verified and round-tripped")
    print("proof depths 1-5; tampered proofs refused; deterministic output: PASS")
    print("parse-back and hyphenated relation normalization: PASS")
    print(f"structured fallbacks: {structured_fallbacks}")
    print(f"results carrying incomplete flag: {incomplete_results}")
    print("licensed sentence realization for inferred conclusion: PASS")


if __name__ == "__main__":
    main()
