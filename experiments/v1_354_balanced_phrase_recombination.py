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
        permutation_rows.append({
            "training_order": list(order),
            "held_out": held_out,
            "cases": outputs,
            "negative_statuses": negatives,
        })
    return {"held_out": held_out, "permutations": permutation_rows}


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

    print("Balanced phrase recombination: 2 crossed 2x2 patterns")
    print("three demonstrations per pattern; all 6 teaching orders tested")
    print(f"held-out exact outputs: {correct}/{total}; wrong={wrong}; "
          f"abstained={abstained}")
    print(f"all teaching phrases preserved as evidence: "
          f"{evidence_checks}/{total}")
    print(f"unseen operators/entities/order/modifiers abstained: "
          f"{len(results) * 6 * len(NEGATIVES)}/"
          f"{len(results) * 6 * len(NEGATIVES)}")


if __name__ == "__main__":
    main()
