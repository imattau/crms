"""Check numeric-slot transfer, unknown-word grounding, and repeat bounds.

CRMS must transfer a count only from a grounded numeric frame, block weaker
retrieval when a word occupies that frame without number evidence, reject
out-of-range counts, and preserve the parameterized rule after save/load.

Run from the project root with:
    python3 experiments/v1_25_parameterized_numeric_guard.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def repeated(values: list[int], count: int) -> list[int]:
    return [value for value in values for _ in range(count)]


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1, max_repeat=5)
    for count, values in ((3, [1, 2]), (4, [2, 1])):
        result = model.teach(
            f"repeat each value {count} times",
            [(values, repeated(values, count))],
        )
        if result.status != "learned":
            raise SystemExit(f"count {count} did not learn: {result}")

    for phrase in ("scale each value 3 times", "scale each value three times"):
        example_input = [1, -2]
        learned_word = model.teach(
            phrase,
            [(example_input, [3 * value for value in example_input])],
        )
        if learned_word.status != "learned":
            raise SystemExit(f"number-word grounding example failed: {learned_word}")

    grounded_word = model.predict("repeat each value three times", [3, 1])
    if grounded_word.output != repeated([3, 1], 3):
        raise SystemExit(f"grounded number-word transfer failed: {grounded_word}")

    transferred = model.predict("repeat each value 5 times", [3, 1])
    if transferred.output != repeated([3, 1], 5):
        raise SystemExit(f"grounded count transfer failed: {transferred}")

    unknown_word = model.predict("repeat each value five times", [3, 1])
    if (unknown_word.status not in ("need_examples", "need_more_examples")
            or unknown_word.output is not None
            or not unknown_word.evidence_phrases
            or not unknown_word.matched_templates):
        raise SystemExit(f"ungrounded number word was not blocked: {unknown_word}")

    out_of_range = model.predict("repeat each value 6 times", [3, 1])
    if (out_of_range.status not in ("need_examples", "need_more_examples")
            or out_of_range.output is not None
            or not out_of_range.evidence_phrases):
        raise SystemExit(f"out-of-range count was not blocked: {out_of_range}")

    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "repeat-memory.json"
        model.save(memory)
        restored = CRMSModel(
            memory, max_composition_depth=1, max_workers=1, max_repeat=5)
        persisted = restored.predict("repeat each value 5 times", [3, 1])
    if persisted.output != repeated([3, 1], 5):
        raise SystemExit(f"count transfer did not survive save/load: {persisted}")

    print("parameterized numeric guard: PASS")
    print("digit and grounded-word transfer, unknown-word abstention, bounds, and persistence: PASS")


if __name__ == "__main__":
    main()
