"""Compose a longer numeral only after a complete grounded addition grid."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def teach_amount(model: CRMSModel, literal: str, value: int) -> None:
    examples = [([1, 4], [1 + value, 4 + value]),
                ([-2, 3], [-2 + value, 3 + value])]
    result = model.teach(f"add {literal} to each value", examples)
    if result.status != "learned":
        raise SystemExit(f"could not learn amount {literal!r}: {result}")


def ground(model: CRMSModel, digits: str, words: str, value: int) -> None:
    teach_amount(model, digits, value)
    teach_amount(model, words, value)


def train(*, complete_grid: bool = True) -> CRMSModel:
    model = CRMSModel(max_composition_depth=1, max_workers=1, max_add=500)
    for digits, words, value in (
            ("2", "two", 2), ("3", "three", 3), ("4", "four", 4),
            ("20", "twenty", 20), ("21", "twenty one", 21),
            ("22", "twenty two", 22), ("23", "twenty three", 23),
            ("200", "two hundred", 200),
            ("300", "three hundred", 300)):
        ground(model, digits, words, value)

    grid = [
        ("221", "two hundred twenty one", 221),
        ("222", "two hundred twenty two", 222),
        ("321", "three hundred twenty one", 321),
        ("322", "three hundred twenty two", 322),
    ]
    if not complete_grid:
        grid.pop()
    for digits, words, value in grid:
        ground(model, digits, words, value)
    # Independently demonstrate optional conjunction placement at one stable
    # boundary for two distinct compound values.
    ground(model, "221", "two hundred and twenty one", 221)
    ground(model, "321", "three hundred and twenty one", 321)
    return model


def main() -> None:
    model = train()
    learned = model._grounded_number_words()
    if learned.get(("four", "hundred", "twenty", "three"), (None,))[0] != 423:
        raise SystemExit("complete 2x2 sum grid did not license 423")
    prediction = model.predict(
        "add four hundred twenty three to each value", [7, -3])
    if prediction.status != "ok" or prediction.output != [430, 420]:
        raise SystemExit(f"held-out compound numeral failed: {prediction}")
    hyphenated = model.predict(
        "add four-hundred-twenty-three to each value", [7, -3])
    if hyphenated.status != "ok" or hyphenated.output != [430, 420]:
        raise SystemExit(f"hyphenated compound numeral failed: {hyphenated}")
    grounded_and = model.predict(
        "add four hundred and twenty three to each value", [7, -3])
    if grounded_and.status != "ok" or grounded_and.output != [430, 420]:
        raise SystemExit(f"grounded optional connective failed: {grounded_and}")
    ungrounded_and = model.predict(
        "add four hundred twenty and three to each value", [7, -3])
    if ungrounded_and.output is not None:
        raise SystemExit("ungrounded connective position was silently ignored")
    required = {
        "add 4 to each value", "add four to each value",
        "add 200 to each value", "add two hundred to each value",
        "add 300 to each value", "add three hundred to each value",
        "add 221 to each value", "add two hundred twenty one to each value",
        "add 222 to each value", "add two hundred twenty two to each value",
        "add 321 to each value", "add three hundred twenty one to each value",
        "add 322 to each value", "add three hundred twenty two to each value",
    }
    if not required.issubset(set(prediction.evidence_phrases or ())):
        raise SystemExit("compound numeral omitted its grounding lineage")

    unsupported = model.predict(
        "add five hundred twenty three to each value", [7, -3])
    if unsupported.output is not None or unsupported.status not in {
            "need_examples", "need_more_examples"}:
        raise SystemExit(f"unknown number prefix was guessed: {unsupported}")

    sparse = train(complete_grid=False)
    if ("four", "hundred", "twenty", "three") in (
            sparse._grounded_number_words()):
        raise SystemExit("incomplete 2x2 grid licensed compound transfer")
    sparse_prediction = sparse.predict(
        "add four hundred twenty three to each value", [7, -3])
    if sparse_prediction.output is not None:
        raise SystemExit("sparse evidence produced an unsupported answer")

    one_and_example = train()
    # Remove one direct conjunction example; the other grounded pair cannot
    # license a productive insertion by itself.
    one_and_example.forget("add three hundred and twenty one to each value")
    if ("four", "hundred", "and", "twenty", "three") in (
            one_and_example._grounded_number_words()):
        raise SystemExit("one conjunction pair licensed optional insertion")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1,
                             max_add=500)
        after_load = restored.predict(
            "add four hundred twenty three to each value", [7, -3])
        if (after_load.status != "ok" or after_load.output != [430, 420]
                or after_load.evidence_phrases != prediction.evidence_phrases):
            raise SystemExit(f"compound numeral changed after reload: {after_load}")

    print("grounded compound-numeral diagnostic: PASS")
    print("complete additive grid, held-out transfer, lineage, persistence, "
          "grounded optional connective, hyphenation, sparse-grid and "
          "unknown-language abstention: PASS")


if __name__ == "__main__":
    main()
