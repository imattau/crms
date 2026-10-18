"""Learn signed number phrases and a grounded negative prefix pattern."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def teach_add(model: CRMSModel, literal: str, value: int) -> None:
    examples = [([1, 4], [1 + value, 4 + value]),
                ([-2, 3], [-2 + value, 3 + value])]
    result = model.teach(f"add {literal} to every value", examples)
    if result.status != "learned":
        raise SystemExit(f"could not learn amount {literal!r}: {result}")


def train(*, include_second_sign_example: bool = True) -> CRMSModel:
    model = CRMSModel(max_composition_depth=1, max_workers=1, max_add=100)
    for literal, value in (("3", 3), ("three", 3), ("4", 4), ("four", 4),
                           ("23", 23), ("twenty three", 23),
                           ("-3", -3), ("minus three", -3)):
        teach_add(model, literal, value)
    if include_second_sign_example:
        for literal in ("-4", "minus four"):
            teach_add(model, literal, -4)
    return model


def main() -> None:
    model = train()
    learned = model._grounded_number_words()
    if learned.get(("minus", "three"), (None,))[0] != -3:
        raise SystemExit("signed digit/word alignment lost its negative value")
    if learned.get(("minus", "twenty", "three"), (None,))[0] != -23:
        raise SystemExit("two-example negative prefix did not generalize")
    prediction = model.predict(
        "add minus twenty three to every value", [7, -3])
    if prediction.status != "ok" or prediction.output != [-16, -26]:
        raise SystemExit(f"held-out negative number transfer failed: {prediction}")
    if not {"add -3 to every value", "add -4 to every value",
            "add 23 to every value", "add twenty three to every value"}.issubset(
                set(prediction.evidence_phrases or ())):
        raise SystemExit("negative numeral omitted grounding lineage")

    ungrounded = model.predict(
        "add negative twenty three to every value", [7, -3])
    if ungrounded.output is not None:
        raise SystemExit("ungrounded sign prefix was treated as minus")

    insufficient = train(include_second_sign_example=False)
    if ("minus", "twenty", "three") in insufficient._grounded_number_words():
        raise SystemExit("one negative example licensed sign-prefix transfer")
    if insufficient.predict(
            "add minus twenty three to every value", [7, -3]).output is not None:
        raise SystemExit("unsupported negative prefix produced an answer")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1,
                             max_add=100)
        after_load = restored.predict(
            "add minus twenty three to every value", [7, -3])
        if (after_load.status != "ok" or after_load.output != [-16, -26]
                or after_load.evidence_phrases != prediction.evidence_phrases):
            raise SystemExit(f"negative phrase changed after reload: {after_load}")

    print("grounded negative number-word diagnostic: PASS")
    print("signed digit alignment, two-example prefix pattern, held-out transfer, "
          "lineage, persistence, and insufficient/unknown-prefix abstention: PASS")


if __name__ == "__main__":
    main()
