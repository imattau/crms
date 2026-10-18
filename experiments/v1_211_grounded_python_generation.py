"""Check inspectable Python rendering from an exact learned CRMS procedure."""

import sys
import subprocess
import hashlib
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_codegen import (
    _python_expression,
    _step_description,
    generate_python,
    natural_language_request,
)
from crms_model import CRMSModel, _apply_step
from crms_model import Step, _encode_window_expression, _parse_window_expression


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    # Verify every primitive that can be searched by the default CRMS learner,
    # including its parameterized variants, against the authoritative executor.
    parity_model = CRMSModel(max_composition_depth=1, max_workers=1)
    parity_inputs = [[], [0], [1, -2, 2, 1], [-3, 0, 7, 4, 4]]
    for step in parity_model._steps:
        expression = _python_expression(step)
        require(expression is not None,
                f"default learner operation has no standalone renderer: {step}")
        description = _step_description(step)
        require(description and not description.startswith("apply operation "),
                f"default learner operation lacks a plain-language description: {step}")
        compiled_expression = compile(expression, "<generated-expression>", "eval")
        for values in parity_inputs:
            actual = eval(compiled_expression, {}, {"xs": list(values)})
            expected = _apply_step(step, list(values))
            require(actual == expected,
                    f"standalone renderer mismatch for {step} on {values}: {actual} != {expected}")

    window_steps = [
        Step("map_window_binary", {
            "operator_id": operator_id, "window_width": width,
            "left_offset": left, "right_offset": right, "stride": stride,
        })
        for operator_id, width, left, right, stride in [
            (0, 2, 0, 1, 1), (1, 3, 2, 0, 2), (2, 3, 0, 2, 1),
            (3, 3, 1, 2, 2), (4, 2, 0, 1, 1),
        ]
    ]
    for expression, stride in [
        ("(+ x y)", 1), ("(* (- x y) z)", 2),
        ("(abs (- x y))", 1), ("(+ (abs x) y)", 2),
    ]:
        tree = _parse_window_expression(expression)
        parameters = {
            "expression_code": _encode_window_expression(tree),
            "stride": stride,
        }
        if "z" in expression:
            parameters["window_width"] = 3
        window_steps.append(Step("map_window_expression", parameters))
    for step in window_steps:
        expression = _python_expression(step)
        require(expression is not None,
                f"accepted window primitive has no standalone renderer: {step}")
        require(not _step_description(step).startswith("apply operation "),
                f"accepted window primitive lacks a description: {step}")
        compiled_expression = compile(expression, "<generated-window>", "eval")
        for values in parity_inputs:
            actual = eval(compiled_expression, {}, {"xs": list(values)})
            expected = _apply_step(step, list(values))
            require(actual == expected,
                    f"window renderer mismatch for {step} on {values}: {actual} != {expected}")

    # Window operations are supplied as explicit grammar extensions, not in
    # the base search space. Confirm learned extension procedures can also be
    # rendered all the way through the evidence-carrying artifact path.
    window_training_inputs = [
        [], [1, 2], [3, 1, 4], [2, -2, 5, 0], [8, 3, 3, 7, 1],
        [-5, 1, 2, -3, 9], [4, 4, 0, -1, 7, 2], [10, -10, 0, 5, -5],
    ]
    expression_step = Step("map_window_expression", {
        "expression_code": _encode_window_expression(
            _parse_window_expression("(abs (- x y))")),
        "stride": 1,
    })
    window_model = CRMSModel(max_composition_depth=1, max_workers=1)
    window_model._steps.append(expression_step)
    for inputs in window_training_inputs:
        outputs = _apply_step(expression_step, inputs)
        learned_window = window_model.teach(
            "window absolute difference", [(inputs, outputs)])
    require(learned_window.status == "learned",
            "window-expression grammar extension did not learn from examples")
    window_code = generate_python(window_model, "window absolute difference")
    require(window_code is not None
            and "xs[i + 0] - xs[i + 1]" in window_code.source,
            "standalone renderer did not emit the learned window expression")
    window_namespace = {}
    exec(compile(window_code.source, "<generated-window>", "exec"),
         window_namespace)
    require(window_namespace["validate_examples"](),
            "generated window-expression function failed its examples")
    for values in [[], [7, -3, 0, 9], [2, 2, 2]]:
        require(window_namespace["transform"](values)
                == window_model.predict("window absolute difference", values).output,
                f"generated window function disagreed on {values}")

    model = CRMSModel(max_composition_depth=1, max_workers=1)
    examples = [
        ([1, 2], [2, 1]), ([3, 4, 5], [5, 4, 3]), ([8], [8]),
        ([1, 3, 2], [2, 3, 1]), ([9, -1, 4], [4, -1, 9]),
    ]
    for inputs, outputs in examples:
        learned = model.teach("reverse the list", [(inputs, outputs)])
    require(learned.status == "learned", "reverse rule did not resolve")
    artifact = generate_python(model, "reverse the list")
    require(artifact is not None, "exact learned procedure did not generate code")
    require("def transform" in artifact.source and '"operation":"reverse"' in artifact.source,
            "generated source hides the learned operation")
    require("Contract: transform accepts a list of integers" in artifact.source
            and "reverse the value order" in artifact.source,
            "generated source does not explain its input contract and operation")
    require("def validate_examples" in artifact.source and "EXAMPLES =" in artifact.source,
            "generated artifact omits evidence or runtime-parity examples")
    require("import crms_model" not in artifact.source,
            "generated source still depends on the CRMS runtime")
    exact_namespace = {}
    exec(compile(artifact.source, "<generated>", "exec"), exact_namespace)
    exact_provenance = exact_namespace["CRMS_PROVENANCE"]
    recorded_id = exact_provenance.pop("artifact_id")
    recomputed_id = "crms-code-v1-" + hashlib.sha256(
        json.dumps(exact_provenance, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    require(recorded_id == artifact.provenance_id == recomputed_id,
            "machine-readable provenance identifier is inconsistent")
    require(exact_provenance["examples"]
            and all(row["phrase"] == "reverse the list"
                    for row in exact_provenance["examples"]),
            "provenance does not map examples back to their source phrase")
    require(artifact.validation_cases == len(examples) + 4,
            "generated function did not run against demonstrations and probes")
    require(generate_python(model, "sort the list") is None,
            "code was generated without an exact learned procedure")
    paraphrase = generate_python(model, "reverse list")
    require(paraphrase is not None
            and "reverse the list" in paraphrase.evidence_phrases,
            "language retrieval could not ground a paraphrase to taught examples")
    paraphrase_namespace = {}
    exec(compile(paraphrase.source, "<generated-paraphrase>", "exec"),
         paraphrase_namespace)
    paraphrase_provenance = paraphrase_namespace["CRMS_PROVENANCE"]
    require(paraphrase_provenance["resolution"] == "learned_retrieval"
            and paraphrase_provenance["retrieval_traces"]
            and all(row["matched_templates"] or row["matched_tokens"]
                    or row["matched_bigrams"] or row["evidence_phrases"]
                    for row in paraphrase_provenance["retrieval_traces"]),
            "paraphrase provenance omitted the per-probe retrieval trace")
    require(natural_language_request("Write Python code that reverse the list")
            == "reverse the list", "natural-language code request was not parsed")
    for request, expected in (
        ("Can you write Python code to reverse list?", "reverse list"),
        ("Could you please write me a Python function to reverse the list?",
         "reverse the list"),
        ("Would you create me some Python code that reverse list?", "reverse list"),
        ("Please create a Python function that reverse list.", "reverse list"),
        ("Generate code in Python to reverse list", "reverse list"),
        ("Could you write a Python script to reverse the list?",
         "reverse the list"),
        ("Can you reverse the list in Python?", "reverse the list"),
        ("Please sort the list in Python.", "sort the list"),
        ("I want to reverse the list in Python.", "reverse the list"),
        ("I need a script that reverse list", "reverse list"),
        ("I need a Python program that reverse list", "reverse list"),
        ("I need you to write Python code that reverse list", "reverse list"),
    ):
        require(natural_language_request(request) == expected,
                f"common code-request wording was not parsed: {request}")
    require(natural_language_request("reverse the list") is None,
            "ordinary instructions were incorrectly treated as code requests")
    require(natural_language_request("Can you explain Python code that reverses a list?") is None,
            "a code explanation request was misrouted as code generation")
    # Exercise parameterized standalone renderings and sequential composition.
    for phrase, rows, probes in [
        ("add three", [([1, 2], [4, 5]), ([8, -2], [11, 1]),
                        ([0, 4, -5], [3, 7, -2]), ([-3], [0])],
         [[], [-2, 0, 9]]),
        ("rotate left twice", [([1, 2, 3], [3, 1, 2]),
                               ([5, 6, 7, 8], [7, 8, 5, 6]),
                               ([0, -1], [0, -1]),
                               ([1, 2, 3, 4, 5], [3, 4, 5, 1, 2])],
         [[], [1, 2, 3, 4]]),
    ]:
        parameter_model = CRMSModel(max_composition_depth=1, max_workers=1)
        for inputs, outputs in rows:
            learned = parameter_model.teach(phrase, [(inputs, outputs)])
        require(learned.status == "learned", f"could not learn {phrase}")
        generated = generate_python(parameter_model, phrase)
        require(generated is not None, f"standalone generation rejected {phrase}")
        namespace = {}
        exec(compile(generated.source, "<generated>", "exec"), namespace)
        require(namespace["validate_examples"](),
                f"generated example validation failed for {phrase}")
        for values in probes:
            expected = parameter_model.predict(phrase, values).output
            require(namespace["transform"](values) == expected,
                    f"generated {phrase} disagreed on {values}")

    # A numeric-slot transfer uses the source examples as evidence for a
    # parameterized template; their outputs are not direct labels for the new
    # parameter. The artifact must keep evidence examples distinct from parity
    # examples for the generated target procedure.
    numeric = CRMSModel(max_composition_depth=1, max_workers=1)
    numeric_inputs = [[], [1, 2], [8, -2], [0, 4, -5], [-3], [5, 5, -1]]
    for amount in (3, 5):
        phrase = f"add {amount} to each value"
        for inputs in numeric_inputs:
            outputs = [value + amount for value in inputs]
            learned_numeric = numeric.teach(phrase, [(inputs, outputs)])
        require(learned_numeric.status == "learned",
                f"numeric source phrase did not learn: {phrase}")
    numeric_code = generate_python(numeric, "add 4 to each value")
    require(numeric_code is not None
            and numeric_code.procedure == ({"operation": "add_k",
                                            "parameters": {"k": 4}},),
            "numeric slot did not transfer to generated code")
    numeric_namespace = {}
    exec(compile(numeric_code.source, "<generated-numeric>", "exec"),
         numeric_namespace)
    require(numeric_namespace["validate_examples"](),
            "numeric-slot artifact failed generated-rule parity checks")
    require(all(row["phrase"] in {"add 3 to each value", "add 5 to each value"}
                for row in numeric_namespace["EVIDENCE_EXAMPLES"])
            and all(row["output"] == [value + 4 for value in row["input"]]
                    for row in numeric_namespace["VALIDATION_EXAMPLES"]),
            "numeric artifact conflated source evidence with target outputs")
    require(numeric_namespace["transform"]([1, -3, 5]) == [5, 1, 9],
            "generated code did not use the transferred parameter value")

    # Multiword numeral meaning is not built in: a second procedural frame
    # explicitly aligns the phrase with a digit, after which a numeric
    # parameter scaffold can use that grounded value.
    words_model = CRMSModel(max_composition_depth=1, max_workers=1,
                            max_add=30, max_rotation=25)
    for amount, words in ((21, "twenty one"), (22, "twenty two")):
        for phrase in (f"add {amount} to every value",
                       f"add {words} to every value"):
            learned_words = words_model.teach(
                phrase, [([1, -2], [1 + amount, -2 + amount])])
            require(learned_words.status == "learned",
                    f"could not ground numeric slot phrase: {phrase}")
    rotation_examples = [
        ([1, 2, 3, 4], [4, 1, 2, 3]),
        ([1, 2, 3, 4, 5], [4, 5, 1, 2, 3]),
        ([1, 2, 3, 4, 5, 6, 7], [3, 4, 5, 6, 7, 1, 2]),
    ]
    for phrase in ("rotate left 23 places", "rotate left twenty three places"):
        learned_words = words_model.teach(phrase, rotation_examples)
        require(learned_words.status == "learned",
                f"could not align the numeral phrase: {phrase}")
    require(words_model.grounded_cardinal_phrases().get(("twenty", "three"), (None,))[0]
            == 23, "number word was not mechanically grounded to digit evidence")
    word_code = generate_python(words_model, "add twenty three to every value")
    require(word_code is not None
            and word_code.procedure == ({"operation": "add_k",
                                         "parameters": {"k": 23}},),
            "grounded multiword numeral did not transfer to generated code")
    word_namespace = {}
    exec(compile(word_code.source, "<generated-number-words>", "exec"),
         word_namespace)
    require(word_namespace["validate_examples"]()
            and word_namespace["transform"]([1, -2]) == [24, 21]
            and "rotate left twenty three places"
            in word_code.evidence_phrases,
            "multiword numeral generation lost its grounded evidence or output")
    composed = CRMSModel(max_composition_depth=2, max_workers=1)
    composed_rows = [
        ([1, 2], [4, 3]), ([3, 4, 5], [7, 6, 5]), ([8], [10]),
        ([1, 3, 2], [4, 5, 3]), ([9, -1, 4], [6, 1, 11]),
        ([0, 2, -5], [-3, 4, 2]),
    ]
    for inputs, outputs in composed_rows:
        learned_composed = composed.teach(
            "reverse then add two", [(inputs, outputs)])
    require(learned_composed.status == "learned",
            "two-step composition did not become uniquely learned")
    composed_code = generate_python(composed, "reverse then add two")
    require(composed_code is not None and len(composed_code.procedure) == 2,
            "standalone code generator did not preserve composed procedure steps")
    composed_namespace = {}
    exec(compile(composed_code.source, "<generated-composed>", "exec"),
         composed_namespace)
    require(composed_namespace["validate_examples"](),
            "composed generated function failed its learned examples")
    for values in [[], [5, -3, 2], [0, 0, 9, -1]]:
        require(composed_namespace["transform"](values)
                == composed.predict("reverse then add two", values).output,
                f"generated composition disagreed on {values}")
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="crms-codegen-") as directory:
        root = Path(directory)
        generated_file = root / "generated_reverse.py"
        generated_file.write_text(paraphrase.source, encoding="utf-8")
        run_generated = subprocess.run([
            sys.executable, "-c",
            "import runpy,sys; m=runpy.run_path(sys.argv[1]); "
            "assert m['validate_examples'](); "
            "assert m['transform']([7,-2,4]) == [4,-2,7]",
            str(generated_file)], text=True, capture_output=True,
            cwd=root, timeout=15)
        require(run_generated.returncode == 0,
                f"saved generated Python failed independent process check: {run_generated.stderr}")
        memory = root / "rules.json"
        model.save(memory)
        paths = {name: root / f"{name}.json" for name in
                 ("knowledge", "math", "translations", "index", "dialogue")}
        command = [sys.executable, str(project / "crms_chat.py"),
                   "--rules", str(memory), "--rule-depth", "1"]
        for flag, path in paths.items():
            command.extend([f"--{flag}", str(path)])
        run = subprocess.run(command, input=(
            "Write Python code that reverse list\n"
            "Explain that code\n"
            "Show the examples for that code\n/quit\n"), text=True,
            capture_output=True, cwd=root, timeout=30)
        require(run.returncode == 0 and "def transform" in run.stdout
                and "wrapper parity checked" in run.stdout
                and "reverse the list" in run.stdout
                and "implements this learned list operation: reverse the value order" in run.stdout
                and "[1, 2] -> [2, 1]" in run.stdout
                and paraphrase.provenance_id in run.stdout,
                f"terminal did not route and inspect the natural-language code:\n{run.stdout}\n{run.stderr}")
        numeric_memory = root / "numeric_rules.json"
        numeric.save(numeric_memory)
        numeric_command = [sys.executable, str(project / "crms_chat.py"),
                           "--rules", str(numeric_memory), "--rule-depth", "1"]
        for flag, path in paths.items():
            numeric_command.extend([f"--{flag}", str(path)])
        numeric_run = subprocess.run(numeric_command, input=(
            "Can you write Python code to add 4 to each value?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=30)
        require(numeric_run.returncode == 0
                and "add 4 to every value" in numeric_run.stdout
                and "add 3 to each value" in numeric_run.stdout
                and "add 5 to each value" in numeric_run.stdout,
                f"terminal failed natural-language numeric code transfer:\n"
                f"{numeric_run.stdout}\n{numeric_run.stderr}")
    print("grounded Python generation diagnostic: PASS")


if __name__ == "__main__":
    main()
