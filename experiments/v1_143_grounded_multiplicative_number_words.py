"""Learn a bounded multiplicative number-word pattern from examples."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def teach_add(model: CRMSModel, literal: str, value: int) -> None:
    examples = [([1, 4], [1 + value, 4 + value]),
                ([-2, 3], [-2 + value, 3 + value])]
    result = model.teach(f"add {literal} to each value", examples)
    if result.status != "learned":
        raise SystemExit(f"could not learn amount {literal!r}: {result}")


def ground(model: CRMSModel, digit: str, words: str, value: int) -> None:
    teach_add(model, digit, value)
    teach_add(model, words, value)


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1, max_add=500)
    ground(model, "2", "two", 2)
    ground(model, "3", "three", 3)
    ground(model, "4", "four", 4)
    ground(model, "200", "two hundred", 200)
    ground(model, "300", "three hundred", 300)

    learned = model._grounded_number_words()
    if learned.get(("four", "hundred"), (None,))[0] != 400:
        raise SystemExit(f"multiplicative phrase was not induced: {learned}")
    prediction = model.predict("add four hundred to each value", [7, -3])
    if prediction.status != "ok" or prediction.output != [407, 397]:
        raise SystemExit(f"held-out multiplicative slot failed: {prediction}")
    required_sources = {
        "add 4 to each value", "add four to each value",
        "add 200 to each value", "add two hundred to each value",
        "add 300 to each value", "add three hundred to each value",
    }
    if not required_sources.issubset(set(prediction.evidence_phrases or ())):
        raise SystemExit("prediction omitted number-composition lineage")

    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "rules.json"
        model.save(memory)
        restored = CRMSModel(memory, max_composition_depth=1, max_workers=1,
                             max_add=500)
        after_load = restored.predict(
            "add four hundred to each value", [7, -3])
        if (after_load.status != "ok" or after_load.output != [407, 397]
                or after_load.evidence_phrases != prediction.evidence_phrases):
            raise SystemExit(
                f"number-word transfer changed after reload: {after_load}")

    unknown = model.predict("add five hundred to each value", [7, -3])
    if unknown.output is not None or unknown.status not in {
            "need_examples", "need_more_examples"}:
        raise SystemExit(f"ungrounded multiplier prefix was guessed: {unknown}")

    insufficient = CRMSModel(max_composition_depth=1, max_workers=1,
                             max_add=500)
    ground(insufficient, "2", "two", 2)
    ground(insufficient, "3", "three", 3)
    ground(insufficient, "4", "four", 4)
    ground(insufficient, "200", "two hundred", 200)
    if ("four", "hundred") in insufficient._grounded_number_words():
        raise SystemExit("one compound licensed a multiplicative pattern")

    print("grounded multiplicative number-word diagnostic: PASS")
    print("two distinct compound examples, held-out product, source lineage, "
          "persistence, unknown-prefix and one-example abstention: PASS")


if __name__ == "__main__":
    main()
