"""Audit natural-language questions answered from independently checked rules.

Expected relations come from an independent two-edge join over explicit facts;
each CRMS proof must also pass the separate recursive proof verifier.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def independent_two_edge_join(
        facts: list[dict[str, object]]) -> dict[
            str, list[tuple[str, dict[str, object], dict[str, object]]]]:
    """Compute parent-parent conclusions without invoking CRMS inference."""
    edges = [fact for fact in facts
             if str(fact["relation"]).casefold() == "parent"
             and not fact.get("qualifiers")]
    conclusions: dict[str, list[tuple[str, dict[str, object], dict[str, object]]]] = {}
    for first in edges:
        for second in edges:
            if str(first["object"]).casefold() != str(second["subject"]).casefold():
                continue
            conclusions.setdefault(str(second["object"]), []).append(
                (str(first["subject"]), first, second))
    return conclusions


def collect_leaf_sources(proof: dict[str, object]) -> set[str]:
    if proof.get("kind") == "fact":
        fact = proof.get("fact", {})
        return set(fact.get("sources", ())) if isinstance(fact, dict) else set()
    sources: set[str] = set()
    for premise in proof.get("premises", []):
        if isinstance(premise, dict):
            sources.update(collect_leaf_sources(premise))
    return sources


def main() -> None:
    kb = CRMSKnowledgeBase()
    chains = [
        ("Ada", "Bea", "Cal", "train-a"),
        ("Dee", "Eli", "Fay", "train-b"),
        ("Nia", "Oren", "Pia", "heldout-c"),
        ("Nox", "Oren", "Pia", "heldout-d"),
        ("Tess", "Uma", "Rex", "heldout-e"),
    ]
    for subject, middle, obj, source in chains:
        kb.add_fact(subject, "parent", middle, f"{source}:first")
        kb.add_fact(middle, "parent", obj, f"{source}:second")
    rule = kb.add_inference_rule(
        "parent-transitivity", "parent", "parent", "ancestor")

    for question, entity, answer in (
            ("Who is an ancestor of Cal?", "Cal", "Ada"),
            ("Who is an ancestor of Fay?", "Fay", "Dee")):
        kb.teach_question(question, relation="ancestor", answer_field="subject",
                          bound_entity=entity, answer=answer)

    if len(kb._question_examples) != 1:
        raise SystemExit("expected one licensed inferred-question frame")
    (relation_json, answer_field, prefix, suffix), examples = next(
        iter(kb._question_examples.items()))
    relation = tuple(json.loads(relation_json))
    if relation != ("ancestor",) or answer_field != "subject":
        raise SystemExit("unexpected learned question frame")
    if not kb._question_frame_is_licensed(
            (relation_json, answer_field, prefix, suffix), examples):
        raise SystemExit("inferred examples did not license the question frame")

    fact_rows = [asdict(fact) for fact in kb.facts()]
    rule_rows = [asdict(rule)]
    expected = independent_two_edge_join(fact_rows)
    before_facts = [asdict(fact) for fact in kb.facts()]
    before_frames = {key: dict(rows) for key, rows in kb._question_examples.items()}

    checked = 0
    for bound, derivations in sorted(expected.items(), key=lambda item: item[0].casefold()):
        question = " ".join(prefix + tuple(bound.casefold().split()) + suffix)
        result = kb.ask(question)
        answers = sorted({subject for subject, _first, _second in derivations},
                         key=str.casefold)
        expected_status = "answered" if len(answers) == 1 else "ambiguous"
        actual_answers = ([result.answer] if result.status == "answered" else
                          sorted(result.candidates or [], key=str.casefold))
        if result.status != expected_status or actual_answers != answers:
            raise SystemExit(f"inferred answer mismatch for {question!r}: "
                             f"expected {expected_status} {answers}, got {result}")
        proofs = result.inference_proofs or []
        if not proofs:
            raise SystemExit(f"inferred answer lacks proofs: {question!r}")
        proven_conclusions: set[tuple[str, str, str]] = set()
        proof_sources: set[str] = set()
        for proof in proofs:
            conclusion = proof.get("conclusion", {})
            if not isinstance(conclusion, dict):
                raise SystemExit(f"malformed inference conclusion: {proof}")
            check = verify_inference_proof(
                proof, fact_rows, rule_rows, expected_conclusion=conclusion)
            if not check.valid:
                raise SystemExit(f"independent proof check failed: {check}")
            proven_conclusions.add((str(conclusion.get("subject")),
                                    str(conclusion.get("relation")),
                                    str(conclusion.get("object"))))
            proof_sources.update(collect_leaf_sources(proof))

        expected_conclusions = {(subject, "ancestor", bound)
                                for subject, _first, _second in derivations}
        if proven_conclusions != expected_conclusions:
            raise SystemExit(f"proof conclusion mismatch: {proven_conclusions} != "
                             f"{expected_conclusions}")
        expected_sources = {source for _subject, first, second in derivations
                            for fact in (first, second)
                            for source in fact.get("sources", ())}
        if proof_sources != expected_sources:
            raise SystemExit(f"proof provenance mismatch: {proof_sources} != "
                             f"{expected_sources}")
        checked += 1

    missing = kb.ask("Who is an ancestor of Unrecorded?")
    if missing.status != "unknown" or not missing.matched_templates:
        raise SystemExit(f"learned frame did not abstain without a proof: {missing}")
    if [asdict(fact) for fact in kb.facts()] != before_facts:
        raise SystemExit("question evaluation mutated the fact store")
    if {key: dict(rows) for key, rows in kb._question_examples.items()} != before_frames:
        raise SystemExit("question evaluation mutated learned frames")

    print(f"inferred question curriculum: {checked} independently joined endpoints; PASS")
    print("answer sets, ambiguity, recursive proof checks, source lineage, "
          "open-world abstention, and read-only evaluation: PASS")


if __name__ == "__main__":
    main()
