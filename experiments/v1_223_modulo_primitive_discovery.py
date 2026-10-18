"""Exercise out-of-grammar remainder discovery through learning and codegen."""
from __future__ import annotations

import random
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_codegen import generate_python
from crms_model import CRMSModel


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def remainder(values: list[int]) -> list[int]:
    return [left % right for left, right in zip(values, values[1:])]


def main() -> None:
    phrases = (
        "keep the remainder of each adjacent pair",
        "map modulo across neighboring values",
        "for every pair return the first value's remainder by the next",
    )
    rng = random.Random(223)
    model = CRMSModel(max_composition_depth=1, max_workers=1,
                      max_search_expansions=20_000)
    examples_by_phrase = {}
    for phrase in phrases:
        examples = []
        while len(examples) < 12:
            values = [rng.randint(-40, 40)
                      for _ in range(rng.randint(6, 10))]
            if any(value == 0 for value in values[1:]):
                continue
            examples.append((values, remainder(values)))
        learned = model.teach(phrase, examples)
        require(learned.status == "no_fit" and learned.search_complete,
                f"target unexpectedly fit the active grammar: {phrase}: {learned.status}")
        examples_by_phrase[phrase] = examples

    proposals = [proposal for proposal in model.propose_primitive_candidates()
                 if proposal["descriptor"].get("operation") == "map_window_binary"
                 and proposal["descriptor"].get("operator") == "modulo"
                 and proposal["descriptor"].get("left_offset") == 0
                 and proposal["descriptor"].get("right_offset") == 1
                 and proposal["descriptor"].get("stride") == 1]
    require(len(proposals) == 1 and proposals[0]["held_out_valid"]
            and proposals[0]["mdl_gate_passed"]
            and set(proposals[0]["supporting_instructions"]) == set(phrases),
            f"independently specified modulo failed discovery gates: {proposals}")
    result = model.learn_primitive_proposal(proposals[0]["artifact_id"])
    require(result["status"] == "learned"
            and set(result["learned_phrases"]) == set(phrases),
            f"validated modulo proposal did not learn its supported phrases: {result}")
    for phrase, examples in examples_by_phrase.items():
        for inputs, outputs in examples:
            prediction = model.predict(phrase, inputs)
            require(prediction.status == "ok" and prediction.output == outputs,
                    f"learned modulo rule failed replay for {phrase}")
    require(model.predict(phrases[0], [-7, 3]).output == [2]
            and model.predict(phrases[0], [7, -3]).output == [-2],
            "negative operands do not follow the declared Python remainder semantics")
    try:
        model.predict(phrases[0], [7, 0])
    except ZeroDivisionError:
        pass
    else:
        raise SystemExit("a zero divisor did not retain exact modulo domain behavior")

    generated = generate_python(model, phrases[0])
    require(generated is not None and generated.validation_cases > 0,
            "standalone modulo code was not generated")
    with tempfile.TemporaryDirectory(prefix="crms-modulo-code-") as directory:
        path = Path(directory) / "generated.py"
        path.write_text(generated.source, encoding="utf-8")
        namespace = {"__name__": "generated_modulo"}
        exec(compile(generated.source, str(path), "exec"), namespace)
        require(namespace["validate_examples"]()
                and namespace["transform"]([-7, 3, 7, -3]) == [2, 3, -2],
                "standalone code does not match exact CRMS modulo behavior")
        try:
            namespace["transform"]([7, 0])
        except ZeroDivisionError:
            pass
        else:
            raise SystemExit("standalone modulo code hid its zero-divisor behavior")

    with tempfile.TemporaryDirectory(prefix="crms-modulo-memory-") as directory:
        restored_path = Path(directory) / "rules.json"
        model.save(restored_path)
        restored = CRMSModel(restored_path, max_composition_depth=1,
                             max_workers=1, max_search_expansions=20_000)
        require(restored.predict(phrases[0], [-7, 3]).output == [2]
                and restored.accepted_primitive_candidates(),
                "learned modulo primitive did not survive persistence")
    print("held-out modulo discovery, negative-operand semantics, transactional learning, standalone code parity, zero-divisor behavior, persistence: PASS")


if __name__ == "__main__":
    main()
