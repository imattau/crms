"""Check grounded numeral composition across thousands and hundreds."""

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
    model = CRMSModel(max_composition_depth=1, max_workers=1, max_add=5_000)
    for digits, words, value in (
            ("2", "two", 2), ("3", "three", 3), ("4", "four", 4),
            ("20", "twenty", 20), ("21", "twenty one", 21),
            ("22", "twenty two", 22), ("23", "twenty three", 23),
            ("200", "two hundred", 200),
            ("300", "three hundred", 300),
            ("2000", "two thousand", 2_000),
            ("3000", "three thousand", 3_000)):
        ground(model, digits, words, value)

    # First teach a complete 2x2 grid for hundreds + tens/units. It licenses
    # the unobserved suffixes two hundred twenty three, etc.
    for digits, words, value in (
            ("221", "two hundred twenty one", 221),
            ("222", "two hundred twenty two", 222),
            ("321", "three hundred twenty one", 321),
            ("322", "three hundred twenty two", 322)):
        ground(model, digits, words, value)

    # A second, independent grid uses thousand prefixes and the already
    # grounded hundred compounds. The four-by-four part is deliberately
    # incomplete when requested, so the held-out phrase should abstain.
    grid = [("2221", "two thousand two hundred twenty one", 2_221),
            ("2222", "two thousand two hundred twenty two", 2_222),
            ("3221", "three thousand two hundred twenty one", 3_221),
            ("3222", "three thousand two hundred twenty two", 3_222)]
    if not complete_grid:
        grid.pop()
    for digits, words, value in grid:
        ground(model, digits, words, value)
    return model


def main() -> None:
    model = train()
    phrase = ("four thousand two hundred twenty three")
    learned = model._grounded_number_words()
    if learned.get(tuple(phrase.split()), (None,))[0] != 4_223:
        raise SystemExit("hierarchical grounded composition did not license 4,223")
    prediction = model.predict(f"add {phrase} to each value", [7, -3])
    if prediction.status != "ok" or prediction.output != [4_230, 4_220]:
        raise SystemExit(f"held-out hierarchical numeral failed: {prediction}")
    required = {
        "add 2 to each value", "add two to each value",
        "add 3 to each value", "add three to each value",
        "add 200 to each value", "add two hundred to each value",
        "add 300 to each value", "add three hundred to each value",
        "add 2000 to each value", "add two thousand to each value",
        "add 3000 to each value", "add three thousand to each value",
        "add 221 to each value", "add 222 to each value",
        "add 321 to each value", "add 322 to each value",
        "add 2221 to each value", "add 2222 to each value",
        "add 3221 to each value", "add 3222 to each value",
    }
    if not required.issubset(set(prediction.evidence_phrases or ())):
        raise SystemExit("hierarchical composition omitted supporting lineage")

    incomplete = train(complete_grid=False)
    unsupported = incomplete.predict(f"add {phrase} to each value", [7, -3])
    if unsupported.output is not None:
        raise SystemExit("incomplete thousand grid licensed unsupported phrase")

    unknown = model.predict(
        "add five thousand two hundred twenty three to each value", [7, -3])
    if unknown.output is not None:
        raise SystemExit(f"ungrounded prefix was guessed: {unknown}")
    reversed_parts = model.predict(
        "add twenty one two hundred to each value", [7, -3])
    if reversed_parts.output is not None:
        raise SystemExit(f"unsupported reversed parts were composed: {reversed_parts}")
    repeated_parts = model.predict(
        "add two hundred two hundred to each value", [7, -3])
    if repeated_parts.output is not None:
        raise SystemExit(f"unsupported repeated parts were composed: {repeated_parts}")
    explicitly_taught = train()
    teach_amount(explicitly_taught, "400", 400)
    teach_amount(explicitly_taught, "two hundred two hundred", 400)
    direct = explicitly_taught.predict(
        "add two hundred two hundred to each value", [7, -3])
    if direct.status != "ok" or direct.output != [407, 397]:
        raise SystemExit(f"directly taught phrase was blocked: {direct}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1,
                             max_add=5_000)
        after_load = restored.predict(f"add {phrase} to each value", [7, -3])
        if (after_load.status != "ok" or after_load.output != [4_230, 4_220]
                or after_load.evidence_phrases != prediction.evidence_phrases):
            raise SystemExit(f"hierarchical numeral changed after reload: {after_load}")

    print("hierarchical numeral composition diagnostic: PASS")
    print("thousands/hundreds grids, multi-level held-out transfer, lineage, "
          "persistence, sparse-grid and unknown-prefix abstention: PASS")


if __name__ == "__main__":
    main()
