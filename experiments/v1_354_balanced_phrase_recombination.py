"""Measure phrase recombination under balanced, crossed demonstrations.

This complements the larger phrase grid in v1_242. That benchmark's first
four examples use unique verbs and nouns, so this diagnostic tests the
inductive effect of a balanced three-example crossing and its order stability.
"""
from __future__ import annotations

from itertools import permutations
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import generate_python
from crms_model import CRMSModel


EXAMPLES = (
    ([1, 2, 3], [3, 2, 1]),
    ([4, -1, 7], [7, -1, 4]),
)
HELD_OUT_INPUTS = ([], [17, -3, 0, 4], [2, 2, -1])
TRAINING_CROSSES = (
    (("reverse the list", "reverse the values", "invert the values"),
     "invert the list"),
    (("reverse the list", "invert the list", "invert the values"),
     "reverse the values"),
)
NEGATIVES = (
    "flip the list",              # unseen operator
    "reverse the collection",     # unseen object class
    "list reverse values",        # known words in unsupported order
    "reverse please the values",  # unsupported modifier placement
)
REVERSE_EXAMPLES = (
    ([1, 2, 3], [3, 2, 1]),
    ([4, -1, 7], [7, -1, 4]),
)
SORT_EXAMPLES = (
    ([1, 4, -2], [-2, 1, 4]),
    ([6, 0, 3], [0, 3, 6]),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def evaluate_cross(phrases: tuple[str, str, str], held_out: str) -> dict:
    permutation_rows = []
    for order in permutations(phrases):
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        for phrase in order:
            result = model.teach(phrase, EXAMPLES)
            require(result.status == "learned",
                    f"failed to teach {phrase!r}: {result}")
        outputs = []
        for values in HELD_OUT_INPUTS:
            result = model.predict(held_out, values)
            expected = list(reversed(values))
            outputs.append({
                "status": result.status,
                "correct": result.status == "ok" and result.output == expected,
                "wrong": result.status == "ok" and result.output != expected,
                "evidence_phrases": sorted(result.evidence_phrases),
                "matched_templates": result.matched_templates,
            })
        negatives = {phrase: model.predict(phrase, [8, -2, 5]).status
                     for phrase in NEGATIVES}
        artifact = generate_python(model, held_out)
        require(artifact is not None
                and artifact.domain == "list"
                and artifact.instruction == held_out
                and set(artifact.evidence_phrases) == set(order),
                f"held-out recombination did not generate a traceable artifact: "
                f"{held_out}: {artifact}")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<crms-balanced-recombination>", "exec"),
             namespace)
        require(namespace["transform"]([17, -3, 0, 4]) == [4, 0, -3, 17]
                and namespace["validate_examples"](),
                f"generated code failed parity for {held_out}: {artifact}")
        require(generate_python(model, "flip the list") is None,
                "code was generated for an unsupported operation word")
        permutation_rows.append({
            "training_order": list(order),
            "held_out": held_out,
            "cases": outputs,
            "negative_statuses": negatives,
            "generated_code": {
                "resolution": namespace["CRMS_PROVENANCE"]["resolution"],
                "evidence_phrases": artifact.evidence_phrases,
                "validation_cases": artifact.validation_cases,
                "provenance_id": artifact.provenance_id,
            },
        })
    return {"held_out": held_out, "permutations": permutation_rows}


def evaluate_conflicting_cross() -> None:
    """Do not select one operation when a crossed phrase fits both."""
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    examples = (
        ("invert the values", REVERSE_EXAMPLES),
        ("invert the entries", REVERSE_EXAMPLES),
        ("reverse the list", REVERSE_EXAMPLES),
        ("flip the list", REVERSE_EXAMPLES),
        ("invert the items", SORT_EXAMPLES),
        ("invert the objects", SORT_EXAMPLES),
        ("sort the list", SORT_EXAMPLES),
        ("order the list", SORT_EXAMPLES),
    )
    for phrase, demonstrations in examples:
        result = model.teach(phrase, demonstrations)
        require(result.status == "learned",
                f"failed to teach collision control {phrase!r}: {result}")

    # Each side is independently grounded, but the unseen crossed phrase
    # combines an operator and object role that support different behaviors.
    collision = model.predict("invert the list", [9, -3, 4, 1])
    require(collision.status == "need_examples"
            and collision.output is None
            and collision.language_gaps is not None
            and collision.language_gaps.get("conflicting_tokens")
            and collision.language_gaps.get("conflicting_bigrams"),
            f"conflicting crossed behavior was not exposed for review: "
            f"{collision}")
    require(generate_python(model, "invert the list") is None,
            "code generator resolved an ambiguous crossed phrase")


def main() -> None:
    results = [evaluate_cross(phrases, held_out)
               for phrases, held_out in TRAINING_CROSSES]
    total = correct = wrong = abstained = 0
    evidence_checks = 0
    for crossing in results:
        for row in crossing["permutations"]:
            for case in row["cases"]:
                total += 1
                correct += case["correct"]
                wrong += case["wrong"]
                abstained += case["status"] != "ok"
                evidence_checks += (
                    set(case["evidence_phrases"])
                    == set(row["training_order"]))
            require(all(status != "ok"
                        for status in row["negative_statuses"].values()),
                    f"unlicensed negative was answered: {row}")

    require(correct == total and wrong == 0 and abstained == 0,
            f"balanced crossing did not transfer exactly: "
            f"correct={correct}/{total}, wrong={wrong}, abstained={abstained}")
    require(evidence_checks == total,
            f"transfer evidence did not name all three teaching phrases: "
            f"{evidence_checks}/{total}")
    for crossing in results:
        artifact_ids = {
            row["generated_code"]["provenance_id"]
            for row in crossing["permutations"]
        }
        require(len(artifact_ids) == 1,
                f"teaching order changed the generated artifact: {artifact_ids}")
    evaluate_conflicting_cross()

    print("Balanced phrase recombination: 2 crossed 2x2 patterns")
    print("three demonstrations per pattern; all 6 teaching orders tested")
    print(f"held-out exact outputs: {correct}/{total}; wrong={wrong}; "
          f"abstained={abstained}")
    print(f"all teaching phrases preserved as evidence: "
          f"{evidence_checks}/{total}")
    print("standalone code for held-out phrases: 12/12, all source-traced and "
          "parity-checked; stable artifact IDs across teaching orders")
    print(f"unseen operators/entities/order/modifiers abstained: "
          f"{len(results) * 6 * len(NEGATIVES)}/"
          f"{len(results) * 6 * len(NEGATIVES)}")
    print("crossed reverse/sort conflict abstains; no code emitted for conflict: PASS")


if __name__ == "__main__":
    main()
