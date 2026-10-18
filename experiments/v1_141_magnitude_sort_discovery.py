"""Teach and validate stable sorting by absolute magnitude from examples."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


PROJECT = Path(__file__).resolve().parents[1]
INSTRUCTION = "order values by size"
TARGET = (Step("sort_by_magnitude", {}),)
EXAMPLES = [
    ([4, -1, 3, -6, 2], [-1, 2, 3, 4, -6]),
    ([-10, 3, -2, 1, 7], [1, -2, 3, 7, -10]),
    ([6, -8, 2, -3, 5], [2, -3, 5, 6, -8]),
    ([3, -3, 2, -2, 1], [1, 2, -2, 3, -3]),
]


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "rules.json"
        model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        learned = model.teach(INSTRUCTION, EXAMPLES)
        if learned.status != "learned" or learned.procedure != [
                {"operation": "sort_by_magnitude", "parameters": {}}]:
            raise SystemExit(f"magnitude-sort rule was not uniquely learned: {learned}")

        held_out = [-5, 2, -1, 4]
        prediction = model.predict(INSTRUCTION, held_out)
        if prediction.status != "ok" or prediction.output != [-1, 2, 4, -5]:
            raise SystemExit(f"held-out magnitude sort failed: {prediction}")
        tied = [-3, 2, 3]
        tie_result = model.predict(INSTRUCTION, tied)
        if tie_result.output != [2, -3, 3]:
            raise SystemExit(f"stable equal-magnitude order changed: {tie_result}")
        if _semantic_key(TARGET) != _semantic_key((
                Step("sort_by_magnitude", {}), Step("sort_by_magnitude", {}))):
            raise SystemExit("idempotent magnitude sorts were not canonicalized")
        if _semantic_key(TARGET) == _semantic_key((Step("sort_ascending", {}),)):
            raise SystemExit("magnitude sort was merged with numeric ascending sort")

        value_lists = [[]]
        for length in range(1, 5):
            value_lists.extend(list(values)
                               for values in product(range(-2, 3), repeat=length))
        equivalent_pairs = (
            ((Step("sort_by_magnitude", {}), Step("sort_ascending", {})),
             (Step("sort_ascending", {}),)),
            ((Step("sort_by_magnitude", {}), Step("sort_descending", {})),
             (Step("sort_descending", {}),)),
            ((Step("sort_by_magnitude", {}), Step("scale_k", {"k": -2})),
             (Step("scale_k", {"k": -2}), Step("sort_by_magnitude", {}))),
            ((Step("sort_by_magnitude", {}), Step("repeat_each_k", {"k": 2})),
             (Step("repeat_each_k", {"k": 2}), Step("sort_by_magnitude", {}))),
            ((Step("sort_by_magnitude", {}), Step("stable_unique", {})),
             (Step("stable_unique", {}), Step("sort_by_magnitude", {}))),
        )
        for left, right in equivalent_pairs:
            if _semantic_key(left) != _semantic_key(right):
                raise SystemExit(f"proved magnitude-sort laws did not canonicalize: {left}, {right}")
            if any(_apply_procedure(left, values) != _apply_procedure(right, values)
                   for values in value_lists):
                raise SystemExit(f"magnitude-sort law failed exhaustive lists: {left}, {right}")

        restored = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        after_load = restored.predict(INSTRUCTION, held_out)
        if after_load.status != "ok" or after_load.output != [-1, 2, 4, -5]:
            raise SystemExit(f"magnitude-sort rule did not persist: {after_load}")

    # The lexical association is learned from the demonstrations; no instruction
    # vocabulary is assigned to the operation by the primitive itself.
    unknown = CRMSModel(max_composition_depth=1, max_workers=1)
    if unknown.predict(INSTRUCTION, held_out).status != "need_examples":
        raise SystemExit("unseen instruction guessed magnitude sorting")

    composed_instruction = "order values by size then reverse"
    composed_examples = [(values, list(reversed(output)))
                         for values, output in EXAMPLES]
    composed = CRMSModel(max_composition_depth=2, max_workers=1)
    composed_result = composed.teach(composed_instruction, composed_examples)
    composed_prediction = composed.predict(composed_instruction, held_out)
    if (composed_result.status != "learned"
            or composed_prediction.status != "ok"
            or composed_prediction.output != [-5, 4, 2, -1]):
        raise SystemExit(
            f"magnitude sort did not compose with reversal: {composed_result}, "
            f"{composed_prediction}")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        command = [sys.executable, str(PROJECT / "crms_chat.py"),
                   "--rules", str(root / "rules.json"),
                   "--knowledge", str(root / "knowledge.json"),
                   "--index", str(root / "index.json"),
                   "--dialogue-state", str(root / "dialogue.json"),
                   "--rule-session", str(root / "session.json"),
                   "--rule-depth", "1"]
        rows = [f"/teach-rule {INSTRUCTION}|{','.join(map(str, xs))}|"
                f"{','.join(map(str, ys))}" for xs, ys in EXAMPLES]
        rows.extend((f"/apply-rule {INSTRUCTION}|-5,2,-1,4", "/quit"))
        process = subprocess.run(
            command, input="\n".join(rows) + "\n", text=True,
            capture_output=True, check=True, timeout=30)
        if "CRMS> [-1, 2, 4, -5]" not in process.stdout:
            raise SystemExit(f"terminal did not learn magnitude sorting:\n{process.stdout}")

    print("magnitude-sort discovery diagnostic: PASS")
    print("unique rule, held-out and tie stability, syntax-safe canonicalization, persistence, CLI, unseen-phrase abstention: PASS")


if __name__ == "__main__":
    main()
