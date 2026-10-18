"""Learn optional conjunction placement in a deeper numeral composition."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crms_model import CRMSModel
from v1_148_hierarchical_numeral_composition import teach_amount, train


def ground_and(model: CRMSModel, *, include_second: bool = True) -> None:
    examples = [("2221", "two thousand two hundred twenty one", 2_221,
                 "two thousand two hundred and twenty one"),
                ("3221", "three thousand two hundred twenty one", 3_221,
                 "three thousand two hundred and twenty one")]
    if not include_second:
        examples.pop()
    for digits, base, value, with_and in examples:
        teach_amount(model, digits, value)
        teach_amount(model, with_and, value)


def main() -> None:
    model = train()
    ground_and(model)
    phrase = "four thousand two hundred and twenty three"
    prediction = model.predict(f"add {phrase} to each value", [7, -3])
    if prediction.status != "ok" or prediction.output != [4_230, 4_220]:
        raise SystemExit(f"hierarchical conjunction transfer failed: {prediction}")
    if not {
            "add two thousand two hundred and twenty one to each value",
            "add three thousand two hundred and twenty one to each value",
            "add two thousand two hundred twenty one to each value",
            "add three thousand two hundred twenty one to each value",
    }.issubset(set(prediction.evidence_phrases or ())):
        raise SystemExit("connective transfer omitted its grounded pair lineage")

    wrong_boundary = model.predict(
        "add four thousand and two hundred twenty three to each value", [7, -3])
    if wrong_boundary.output is not None:
        raise SystemExit(f"ungrounded conjunction boundary was accepted: {wrong_boundary}")

    one_example = train()
    ground_and(one_example, include_second=False)
    unsupported = one_example.predict(f"add {phrase} to each value", [7, -3])
    if unsupported.output is not None:
        raise SystemExit("one conjunction pair licensed productive insertion")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1,
                             max_add=5_000)
        after_load = restored.predict(f"add {phrase} to each value", [7, -3])
        if (after_load.status != "ok" or after_load.output != [4_230, 4_220]
                or after_load.evidence_phrases != prediction.evidence_phrases):
            raise SystemExit(f"connective transfer changed after reload: {after_load}")

    print("hierarchical numeral connective diagnostic: PASS")
    print("two-example boundary induction, held-out transfer, lineage, persistence, "
          "wrong-boundary and one-example abstention: PASS")


if __name__ == "__main__":
    main()
