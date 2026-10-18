"""Discover zero scaling and use a grounded number word in a new frame."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


ZERO_EXAMPLES = [([1, 2], [0, 0]), ([-3, 4], [0, 0]),
                 ([0, 5, 6], [0, 0, 0]), ([], [])]
TRIPLE_EXAMPLES = [([1, 2], [3, 6]), ([-3, 4], [-9, 12]),
                   ([0, 5, 6], [0, 15, 18]), ([], [])]


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1,
                      max_scale=5)
    learned_zero = model.teach("scale each value by 0", ZERO_EXAMPLES)
    if (learned_zero.status != "learned"
            or learned_zero.procedure != [
                {"operation": "scale_k", "parameters": {"k": 0}}]):
        raise SystemExit(f"zero scaling was not uniquely discovered: {learned_zero}")
    learned_word = model.teach("scale each value by zero", ZERO_EXAMPLES)
    if learned_word.status != "learned":
        raise SystemExit(f"zero word form was not grounded: {learned_word}")
    model.teach("scale each value by 3", TRIPLE_EXAMPLES)
    model.teach("scale each value by three", TRIPLE_EXAMPLES)

    zero_word = model._grounded_number_words().get(("zero",))
    if zero_word is None or zero_word[0] != 0:
        raise SystemExit(f"zero was not learned as a numeric word: {zero_word}")

    model.teach("multiply each value by 0", ZERO_EXAMPLES)
    model.teach("multiply each value by 3", TRIPLE_EXAMPLES)
    transferred = model.predict("multiply each value by zero", [8, -2, 0])
    if (transferred.status != "ok" or transferred.output != [0, 0, 0]
            or transferred.procedure != [
                {"operation": "scale_k", "parameters": {"k": 0}}]):
        raise SystemExit(f"grounded zero slot failed in a new frame: {transferred}")

    unknown = model.predict("multiply each value by nil", [8, -2, 0])
    if unknown.output is not None:
        raise SystemExit("unknown number word was treated as zero")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1,
                             max_scale=5)
        after_load = restored.predict("multiply each value by zero", [8, -2, 0])
        if (after_load.status != "ok" or after_load.output != [0, 0, 0]
                or after_load.procedure != transferred.procedure):
            raise SystemExit(f"zero scale did not survive reload: {after_load}")

    print("zero-scale learning diagnostic: PASS")
    print("unique zero-scale discovery, grounded zero word, cross-frame parameter "
          "transfer, unknown-word abstention, persistence: PASS")


if __name__ == "__main__":
    main()
