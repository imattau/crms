"""Learn a sequencing connective, recombine procedures, and generate code."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import generate_python
from crms_model import CRMSModel


INPUTS = ([3, 1, 2], [4, -1, 7], [0, 5, -2, 8], [-5, 9], [12], [])
DUPLICATE_PROBE = [0, 0]
BASE_PHRASES = (
    ("sort the list", "sort"),
    ("reverse the list", "reverse"),
    ("sort the values", "sort"),
    ("reverse the values", "reverse"),
)
COMPOUND_PHRASES = (
    "sort the list then reverse the values",
    "reverse the list then sort the values",
)
HELD_OUT = "sort the list then reverse the list"
TEST_INPUT = [4, 1, 4, 2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def transformed(values: list[int], first: str, second: str) -> list[int]:
    intermediate = sorted(values) if first == "sort" else list(reversed(values))
    return sorted(intermediate) if second == "sort" else list(reversed(intermediate))


def main() -> None:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    for phrase, operation in BASE_PHRASES:
        examples = [
            (list(values), sorted(values) if operation == "sort"
             else list(reversed(values)))
            for values in (*INPUTS, DUPLICATE_PROBE)
        ]
        learned = model.teach(phrase, examples)
        require(learned.status == "learned" and learned.candidate_count == 1,
                f"base operation was not uniquely learned: {phrase}: {learned}")

    compound_specs = (
        (COMPOUND_PHRASES[0], "sort", "reverse"),
        (COMPOUND_PHRASES[1], "reverse", "sort"),
    )
    for phrase, first, second in compound_specs:
        examples = [(list(values), transformed(list(values), first, second))
                    for values in INPUTS]
        initial = model.teach(phrase, examples)
        require(initial.status == "need_more_examples"
                and initial.contrastive_input == DUPLICATE_PROBE
                and initial.candidate_outputs is not None
                and len({tuple(output)
                         for output in initial.candidate_outputs}) == 2,
                f"compound ambiguity did not request a useful contrast: "
                f"{phrase}: {initial}")
        taught_contrast = model.teach(
            phrase, [(DUPLICATE_PROBE,
                      transformed(DUPLICATE_PROBE, first, second))])
        require(taught_contrast.status == "learned"
                and taught_contrast.candidate_count == 1,
                f"contrastive example did not resolve {phrase}: "
                f"{taught_contrast}")

    # One compound does not license the connective in a new crossing.
    one_compound = CRMSModel(max_composition_depth=2, max_workers=1)
    for phrase, operation in BASE_PHRASES:
        examples = [(list(values), sorted(values) if operation == "sort"
                     else list(reversed(values)))
                    for values in (*INPUTS, DUPLICATE_PROBE)]
        require(one_compound.teach(phrase, examples).status == "learned",
                f"single-compound control failed to learn {phrase}")
    first_phrase, first_op, second_op = compound_specs[0]
    examples = [(list(values), transformed(list(values), first_op, second_op))
                for values in INPUTS]
    require(one_compound.teach(first_phrase, examples).status
            == "need_more_examples",
            "single compound unexpectedly had unique behavior")
    require(one_compound.teach(
        first_phrase, [(DUPLICATE_PROBE,
                        transformed(DUPLICATE_PROBE, first_op, second_op))
    ]).status == "learned", "single-compound contrast was not accepted")
    before_learning = one_compound.predict(HELD_OUT, TEST_INPUT)
    require(before_learning.status != "ok"
            and generate_python(one_compound, HELD_OUT) is None,
            f"one compound licensed an unsupported connective crossing: "
            f"{before_learning}")

    # Two independent component-pair contexts license the sequential
    # connective. The requested phrase is not itself a teaching phrase.
    prediction = model.predict(HELD_OUT, TEST_INPUT)
    require(prediction.status == "ok"
            and prediction.output == [4, 4, 2, 1]
            and prediction.matched_templates == ["learned_sequence:then"],
            f"held-out sequence did not use the learned connective: {prediction}")
    expected_evidence = {
        "sort the list", "reverse the list",
        COMPOUND_PHRASES[0], COMPOUND_PHRASES[1],
    }
    require(expected_evidence <= set(prediction.evidence_phrases),
            f"sequence proof lost its component or rule evidence: "
            f"{prediction.evidence_phrases}")

    artifact = generate_python(model, HELD_OUT)
    require(artifact is not None
            and set(artifact.evidence_phrases) == expected_evidence,
            f"held-out sequence did not create a fully traceable artifact: "
            f"{artifact}")
    namespace: dict[str, object] = {}
    exec(compile(artifact.source, "<crms-learned-sequence>", "exec"), namespace)
    transform = namespace["transform"]
    require(transform(TEST_INPUT) == [4, 4, 2, 1]
            and transform([3, -1, 3, 2]) == [3, 3, 2, -1]
            and namespace["validate_examples"](),
            "generated sequence code disagreed with the learned procedure")
    repeated = generate_python(model, HELD_OUT)
    require(repeated is not None
            and repeated.provenance_id == artifact.provenance_id,
            "same learned crossing did not produce a deterministic artifact")

    with tempfile.TemporaryDirectory(prefix="crms-sequence-code-chat-") as folder:
        root = Path(folder)
        rule_path = root / "rules.json"
        model.save(rule_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(rule_path),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        chat = subprocess.run(
            command,
            input=("Write Python code to sort the list then reverse the list\n"
                   "Explain that code\nShow the examples for that code\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(chat.returncode == 0
                and "Generated Python for 'sort the list then reverse the list'"
                    in chat.stdout
                and all(phrase in chat.stdout for phrase in expected_evidence)
                and "sort_ascending" in chat.stdout
                and "reverse the value order" in chat.stdout
                and "Evidence for generated artifact" in chat.stdout,
                f"natural-language code request/follow-ups failed: "
                f"{chat.stdout}\n{chat.stderr}")

    for unsupported in (
            "sort the list or reverse the list",
            "rotate the list then reverse the list",
            "sort please the list then reverse the list"):
        require(model.predict(unsupported, TEST_INPUT).status != "ok"
                and generate_python(model, unsupported) is None,
                f"unsupported sequence was answered or rendered: {unsupported}")

    print("Learned sequence connective and procedure composition: PASS")
    print("contrastive input resolved both compound rules: [0, 0]")
    print("one-compound control abstained; two independent contexts licensed then: PASS")
    print("held-out sort→reverse: correct output, four evidence phrases, verified code: PASS")
    print("terminal code request, explanation, and evidence follow-up: PASS")
    print("unsupported connective, operation, and modifier: abstained; no code: PASS")


if __name__ == "__main__":
    main()
