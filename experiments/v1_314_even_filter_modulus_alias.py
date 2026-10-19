"""Check even filtering and divisibility by two share a normal form."""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import Step, _apply_procedure, _semantic_key


def main() -> None:
    even = Step("keep_evens", {})
    multiples_two = Step("keep_multiples_k", {"k": 2})
    multiples_negative_two = Step("keep_multiples_k", {"k": -2})
    square = Step("square_values", {})
    multiples_four = Step("keep_multiples_k", {"k": 4})
    filter_forms = [
        (even,),
        (multiples_two,),
        (multiples_negative_two,),
    ]
    squared_even_forms = [
        (even, square),
        (multiples_two, square),
        (square, even),
        (square, multiples_four),
    ]
    for forms in (filter_forms, squared_even_forms):
        keys = {_semantic_key(procedure) for procedure in forms}
        if len(keys) != 1:
            raise SystemExit(f"equivalent even-filter forms kept separate keys: {keys}")

    values_to_check = [
        list(values)
        for length in range(7)
        for values in itertools.product(range(-2, 3), repeat=length)
    ]
    rng = random.Random(314)
    values_to_check.extend(
        [rng.randint(-1_000, 1_000) for _ in range(rng.randint(0, 40))]
        for _ in range(1_000)
    )
    for values in values_to_check:
        for forms in (filter_forms, squared_even_forms):
            outputs = [_apply_procedure(procedure, values) for procedure in forms]
            if any(output != outputs[0] for output in outputs[1:]):
                raise SystemExit(
                    f"even-filter alias outputs differ for {values}: {outputs}")

    # Odd filtering is not divisibility by a fixed integer; keep it separate.
    odd = Step("keep_odds", {})
    if _semantic_key((odd,)) == _semantic_key((multiples_two,)):
        raise SystemExit("odd filtering was incorrectly merged with even filtering")

    print("even-filter/modulus alias diagnostic: PASS")
    print(f"equivalent_groups=2; forms={len(filter_forms) + len(squared_even_forms)}; "
          f"runtime_inputs_per_form={len(values_to_check)}")


if __name__ == "__main__":
    main()
