"""Transfer a phrase number into a varying parameter with fixed rule steps."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def constant_examples(value: int):
    return [([1, 2], [value, value]), ([-3, 4], [value, value]),
            ([0, 5, 6], [value, value, value])]


def teach_add(model: CRMSModel, phrase: str, value: int) -> None:
    examples = [([1, 4], [1 + value, 4 + value]),
                ([-2, 3], [-2 + value, 3 + value]),
                ([0, 8, -5], [value, 8 + value, -5 + value]),
                ([4, 4, -1], [4 + value, 4 + value, -1 + value]),
                ([], []), ([-10], [-10 + value])]
    result = model.teach(phrase, examples)
    if result.status != "learned":
        raise SystemExit(f"could not ground numeric word {phrase!r}: {result}")


def main() -> None:
    model = CRMSModel(max_composition_depth=2, max_workers=1,
                      max_add=10, max_scale=3)
    for value in (3, 7):
        result = model.teach(
            f"set every value to {value}", constant_examples(value))
        expected = [{"operation": "scale_k", "parameters": {"k": 0}},
                    {"operation": "add_k", "parameters": {"k": value}}]
        if result.status != "learned" or result.procedure != expected:
            raise SystemExit(f"constant rule composition failed for {value}: {result}")

    teach_add(model, "add 5 to each value", 5)
    teach_add(model, "add five to each value", 5)

    prediction = model.predict("set every value to five", [12, -9, 0])
    expected = [{"operation": "scale_k", "parameters": {"k": 0}},
                {"operation": "add_k", "parameters": {"k": 5}}]
    if (prediction.status != "ok" or prediction.output != [5, 5, 5]
            or prediction.procedure != expected
            or set(prediction.evidence_phrases or ()) != {
                "set every value to 3", "set every value to 7",
                "add 5 to each value", "add five to each value"}):
        raise SystemExit(f"fixed-parameter numeric transfer failed: {prediction}")

    unknown = model.predict("set every value to eleven", [12, -9, 0])
    if unknown.output is not None:
        raise SystemExit("unknown numeric word filled the fixed-parameter rule")
    out_of_range = model.predict("set every value to 12", [12, -9, 0])
    if out_of_range.output is not None:
        raise SystemExit("out-of-range numeric slot was applied")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=2, max_workers=1,
                             max_add=10, max_scale=3)
        after_load = restored.predict("set every value to five", [12, -9, 0])
        if (after_load.status != "ok" or after_load.output != [5, 5, 5]
                or after_load.procedure != prediction.procedure):
            raise SystemExit(f"fixed-parameter transfer changed after reload: {after_load}")

    print("fixed-parameter numeric-slot diagnostic: PASS")
    print("composed constant rule, varying-slot transfer, retained zero-scale "
          "parameter, word grounding, bounds, abstention, persistence: PASS")


if __name__ == "__main__":
    main()
