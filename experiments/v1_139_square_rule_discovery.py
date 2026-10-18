"""Learn elementwise squaring through bounded procedure synthesis."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    first = model.teach("square the values", [([0, 1], [0, 1])])
    if first.status != "need_more_examples" or model.list_rules():
        raise SystemExit("identity-like evidence did not preserve ambiguity")
    learned = model.teach(
        "square the values", [([-2, 3, -4], [4, 9, 16])])
    expected = [{"operation": "square_values", "parameters": {}}]
    if learned.status != "learned" or learned.procedure != expected:
        raise SystemExit(f"square rule was not uniquely learned: {learned}")

    for values, output in (([-7, 0, 2], [49, 0, 4]),
                           ([5, -3, 1, -1], [25, 9, 1, 1]),
                           ([], [])):
        prediction = model.predict("square the values", values)
        if prediction.status != "ok" or prediction.output != output:
            raise SystemExit(f"held-out square prediction failed: {prediction}")

    reverse = Step("reverse", {})
    square = Step("square_values", {})
    sort = Step("sort_ascending", {})
    multiple_filter = Step("keep_multiples_k", {"k": 4})
    if _semantic_key((square, reverse)) != _semantic_key((reverse, square)):
        raise SystemExit("exact square/reversal commutation was not recognized")
    if _semantic_key((square, sort)) == _semantic_key((sort, square)):
        raise SystemExit("square and sorting were merged despite order dependence")
    if (_semantic_key((square, multiple_filter))
            == _semantic_key((multiple_filter, square))):
        raise SystemExit("square and composite-modulus filtering were merged")

    operations = (square, reverse, sort, multiple_filter,
                  Step("keep_evens", {}), Step("first", {}),
                  Step("scale_k", {"k": -2}))
    programs = ([ (operation,) for operation in operations]
                + list(product(operations, repeat=2)))
    probe_lists = [list(values) for length in range(4)
                   for values in product((-2, -1, 0, 1, 2), repeat=length)]
    seen: dict[tuple, tuple[tuple, tuple[Step, ...]]] = {}
    for program in programs:
        key = _semantic_key(program)
        behavior = tuple(tuple(_apply_procedure(program, values))
                         for values in probe_lists)
        prior = seen.get(key)
        if prior is not None and prior[0] != behavior:
            raise SystemExit(
                f"semantic-key collision: {prior[1]} vs {program}")
        seen[key] = behavior, program

    composed = CRMSModel(max_composition_depth=2, max_workers=1)
    composition = composed.teach(
        "square every value then sum",
        [([1, 2], [5]), ([-2, 3], [13]), ([0], [0])])
    expected_composition = [
        {"operation": "square_values", "parameters": {}},
        {"operation": "sum_values", "parameters": {}},
    ]
    if (composition.status != "learned"
            or composition.procedure != expected_composition):
        raise SystemExit(f"square/sum composition failed: {composition}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        restored.load()
        result = restored.predict("square the values", [-6, 2])
        if result.status != "ok" or result.output != [36, 4]:
            raise SystemExit(f"persisted square rule failed: {result}")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        rules_path = root / "rules.json"
        terminal = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--rules", str(rules_path),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "index.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rule-depth", "1"],
            input=("/teach-rule square the values|0,1|0,1\n"
                   "/teach-rule square the values|-2,3,-4|4,9,16\n"
                   "/apply-rule square the values|-5,6\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if ("Rule learning status: need_more_examples." not in terminal.stdout
                or "Rule learning status: learned." not in terminal.stdout
                or "CRMS> [25, 36]" not in terminal.stdout
                or not rules_path.exists()):
            raise SystemExit(
                f"terminal square teaching or application failed:\n{terminal.stdout}")

    print("square rule discovery diagnostic: PASS")
    print("ambiguous evidence retention, unique synthesis, held-out transfer, composition, persistence, terminal teaching, conservative nonlinear canonicalization: PASS")
    print(f"canonicalizer audit: {len(programs)} programs × {len(probe_lists)} short lists, no collisions")


if __name__ == "__main__":
    main()
