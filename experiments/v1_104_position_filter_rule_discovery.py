"""Learn positional list filters without confusing them with value parity."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def main() -> None:
    examples = {
        "keep values at even positions": [
            ([11, 4, 7, 6, 9, 8], [4, 6, 8]),
            ([2, 7, 9, 4, 11], [7, 4]),
            ([-4, 3, 0, -7, 2], [3, -7]),
        ],
        "keep values at odd positions": [
            ([11, 4, 7, 6, 9, 8], [11, 7, 9]),
            ([2, 7, 9, 4, 11], [2, 9, 11]),
            ([-4, 3, 0, -7, 2], [-4, 0, 2]),
        ],
    }
    targets = {
        "keep values at even positions": Step("keep_even_positions", {}),
        "keep values at odd positions": Step("keep_odd_positions", {}),
    }
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "rules.json"
        model = CRMSModel(path, max_composition_depth=1, max_workers=1)
        for phrase, demonstrations in examples.items():
            result = model.teach(phrase, demonstrations)
            if (result.status != "learned"
                    or _semantic_key(tuple(
                        Step(step["operation"], step["parameters"])
                        for step in result.procedure or []))
                    != _semantic_key((targets[phrase],))):
                raise SystemExit(f"failed to learn {phrase!r}: {result}")
        held_out = [[], [13], [5, 5, 5, 5, 5], [-8, 3, 0, 7]]
        for phrase, procedure in targets.items():
            for values in held_out:
                prediction = model.predict(phrase, values)
                expected = _apply_procedure((procedure,), values)
                if prediction.status != "ok" or prediction.output != expected:
                    raise SystemExit(
                        f"positional rule failed held-out {phrase!r} {values}: {prediction}")
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        if restored.predict("keep values at even positions", [1, 2, 3, 4]).output != [2, 4]:
            raise SystemExit("positional rule did not persist")

    even, odd = targets["keep values at even positions"], targets[
        "keep values at odd positions"]
    affine_before = (Step("add_k", {"k": 3}), even)
    affine_after = (even, Step("add_k", {"k": 3}))
    if _semantic_key(affine_before) != _semantic_key(affine_after):
        raise SystemExit("affine value mapping did not commute with position selection")
    if _semantic_key((odd, even)) == _semantic_key((even, odd)):
        raise SystemExit("different positional residue classes were conflated")

    composed = CRMSModel(max_composition_depth=2, max_workers=1).teach(
        "add three then keep even positions",
        [([1, 2, 3, 4, 5, 6], [5, 7, 9]),
         ([2, 7, 9, 4, 11], [10, 7]),
         ([-4, 3, 0, -7, 2], [6, -4]),
         ([11, 4, 7, 6, 9, 8], [7, 9, 11])])
    if composed.status != "learned":
        raise SystemExit(f"positional primitive did not compose: {composed}")
    procedure = tuple(Step(step["operation"], step["parameters"])
                      for step in composed.procedure or [])
    for values in ([8, 2, -3, 7, 0], [], [9, -2, 1]):
        expected = _apply_procedure(
            (Step("add_k", {"k": 3}), even), values)
        if _apply_procedure(procedure, values) != expected:
            raise SystemExit(f"composed rule failed held-out input {values}: {procedure}")

    print("position-filter rule discovery diagnostic: PASS")
    print("one-based parity semantics, value-parity distinction, edge cases, persistence, exact affine law, composition, held-out behavior: PASS")


if __name__ == "__main__":
    main()
