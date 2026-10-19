"""Grounded Python rendering for procedures learned by CRMSModel.

This is a code artifact renderer, not an open-ended programming language model.
It emits only exact committed CRMS list procedures and keeps the operation
descriptors visible in the generated source.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import re
from typing import Any

from crms_model import (
    CRMSModel,
    Step,
    _apply_procedure,
    _decode_window_expression,
)
from crms_math import (
    CRMSMath, MathBinary, MathLiteral, MathVariable, _ExpressionParser,
    _format,
)


def _python_expression(step: Step) -> str | None:
    """Return a standalone Python expression for a primitive step."""
    op, p = step.operation, step.parameters
    expressions = {
        "identity": "xs",
        "reverse": "list(reversed(xs))",
        "sort_ascending": "sorted(xs)",
        "sort_descending": "sorted(xs, reverse=True)",
        "sort_by_magnitude": "sorted(xs, key=abs)",
        "stable_unique": "list(dict.fromkeys(xs))",
        "sum_values": "[sum(xs)]",
        "cumulative_sum": "[sum(xs[:i]) for i in range(1, len(xs) + 1)]",
        "adjacent_difference": "[right - left for left, right in zip(xs, xs[1:])]",
        "double": "[2 * x for x in xs]",
        "square_values": "[x * x for x in xs]",
        "absolute_values": "[abs(x) for x in xs]",
        "duplicate_each": "[x for x in xs for _ in range(2)]",
        "keep_evens": "[x for x in xs if x % 2 == 0]",
        "keep_odds": "[x for x in xs if x % 2 != 0]",
        "keep_even_positions": "xs[1::2]",
        "keep_odd_positions": "xs[::2]",
        "keep_greater_than_first": "[x for x in xs if xs and x > xs[0]]",
        "keep_less_than_first": "[x for x in xs if xs and x < xs[0]]",
        "add_position": "[x + i for i, x in enumerate(xs, start=1)]",
        "add_first": "[x + xs[0] for x in xs] if xs else []",
        "subtract_first": "[x - xs[0] for x in xs] if xs else []",
        "first": "xs[:1]",
        "last": "xs[-1:]",
        "drop_first": "xs[1:]",
        "drop_last": "xs[:-1]",
    }
    if op in expressions:
        return expressions[op]
    if op == "repeat_each_k":
        return f"[x for x in xs for _ in range({p['k']})]"
    if op == "scale_k":
        return f"[{p['k']} * x for x in xs]"
    if op == "keep_every_kth_position":
        return f"xs[{p['k'] - 1}::{p['k']}]"
    if op == "keep_multiples_k":
        return f"[x for x in xs if x % {p['k']} == 0]"
    if op == "add_k":
        k = p['k']
        return f"[x {'+' if k >= 0 else '-'} {abs(k)} for x in xs]"
    if op == "rotate_left_k":
        k = p['k']
        return (f"(xs[{k} % len(xs):] + xs[:{k} % len(xs)]) "
                "if xs else []")
    if op == "map_window_binary":
        operators = ("+", "-", "*", "max", "min", "%")
        operator = operators[p["operator_id"]]
        left = f"xs[i + {p['left_offset']}]"
        right = f"xs[i + {p['right_offset']}]"
        value = (f"{operator}({left}, {right})"
                 if operator in {"max", "min"}
                 else f"({left} {operator} {right})")
        width, stride = p["window_width"], p["stride"]
        return f"[{value} for i in range(0, len(xs) - {width} + 1, {stride})]"
    if op == "map_window_expression":
        width = p.get("window_width", 2)
        stride = p["stride"]

        def render(node: Any) -> str:
            if node in {"x", "y", "z"}:
                return f"xs[i + { {'x': 0, 'y': 1, 'z': 2}[node] }]"
            if node[0] == "abs":
                return f"abs({render(node[1])})"
            operator, left, right = node
            return f"({render(left)} {operator} {render(right)})"

        expression = render(_decode_window_expression(p["expression_code"]))
        return (f"[{expression} for i in range(0, "
                f"len(xs) - {width} + 1, {stride})]")
    return None


def _step_description(step: Step) -> str:
    """Describe a primitive's explicit runtime behavior for code readers."""
    op, p = step.operation, step.parameters
    fixed = {
        "identity": "leave values unchanged",
        "reverse": "reverse the value order",
        "sort_ascending": "sort values from smallest to largest",
        "sort_descending": "sort values from largest to smallest",
        "sort_by_magnitude": "stable-sort by absolute value, smallest first",
        "stable_unique": "keep each value's first occurrence",
        "sum_values": "replace the list with its sum (empty list gives zero)",
        "cumulative_sum": "replace each value with the running total",
        "adjacent_difference": "emit each next value minus its predecessor",
        "double": "multiply each value by two",
        "square_values": "square each value",
        "absolute_values": "replace each value with its absolute value",
        "duplicate_each": "repeat each value twice, preserving order",
        "keep_evens": "keep values divisible by two",
        "keep_odds": "keep values not divisible by two",
        "keep_even_positions": "keep one-based positions 2, 4, 6, ...",
        "keep_odd_positions": "keep one-based positions 1, 3, 5, ...",
        "keep_greater_than_first": "keep values greater than the first value",
        "keep_less_than_first": "keep values less than the first value",
        "add_position": "add each value's one-based position to it",
        "add_first": "add the first value to every value",
        "subtract_first": "subtract the first value from every value",
        "first": "keep only the first value, if present",
        "last": "keep only the last value, if present",
        "drop_first": "remove the first value",
        "drop_last": "remove the last value",
    }
    if op in fixed:
        return fixed[op]
    if op == "repeat_each_k":
        return f"repeat each value {p['k']} times, preserving order"
    if op == "scale_k":
        return f"multiply each value by {p['k']}"
    if op == "keep_every_kth_position":
        return f"keep one-based positions {p['k']}, {2 * p['k']}, {3 * p['k']}, ..."
    if op == "keep_multiples_k":
        return f"keep values divisible by {p['k']}"
    if op == "add_k":
        return f"add {p['k']} to every value"
    if op == "rotate_left_k":
        direction = "left" if p["k"] >= 0 else "right"
        return f"rotate {direction} by {abs(p['k'])} positions"
    if op == "map_window_binary":
        operator = ("add", "subtract", "multiply", "maximum", "minimum",
                    "modulo")[
            p["operator_id"]]
        return (f"map {operator} over positions {p['left_offset'] + 1} and "
                f"{p['right_offset'] + 1} in width-{p['window_width']} "
                f"windows, stepping by {p['stride']}")
    if op == "map_window_expression":
        def describe(node: Any) -> str:
            if node in {"x", "y", "z"}:
                return {"x": "first", "y": "second", "z": "third"}[node]
            if node[0] == "abs":
                return f"absolute value of {describe(node[1])}"
            operator, left, right = node
            return f"({describe(left)} {operator} {describe(right)})"

        expression = describe(_decode_window_expression(p["expression_code"]))
        return (f"evaluate {expression} over width-"
                f"{p.get('window_width', 2)} windows, stepping by {p['stride']}")
    return f"apply operation {op} with parameters {p}"


@dataclass(frozen=True)
class GeneratedCode:
    instruction: str
    source: str
    evidence_examples: int
    validation_cases: int
    procedure: tuple[dict[str, Any], ...]
    evidence_phrases: tuple[str, ...]
    provenance_id: str
    domain: str = "list"
    evidence_details: tuple[dict[str, Any], ...] = ()


def describe_generated_code(result: GeneratedCode) -> str:
    """Explain a generated artifact from its typed procedure and evidence."""
    if result.domain == "list":
        operations = [
            _step_description(Step(
                item["operation"], dict(item.get("parameters", {}))))
            for item in result.procedure
        ]
        summary = "; then ".join(operations)
        sources = ", ".join(f"'{phrase}'" for phrase in result.evidence_phrases)
        return (f"The generated function implements this learned list operation: "
                f"{summary}. Its instruction evidence is {sources}; "
                f"{result.evidence_examples} examples and "
                f"{result.validation_cases} parity inputs are recorded. "
                f"Artifact id: {result.provenance_id}.")
    if result.domain == "math":
        def describe(node: dict[str, Any]) -> str:
            if node["kind"] == "literal":
                return str(node["value"])
            if node["kind"] == "variable":
                return node["name"]
            left, right = describe(node["left"]), describe(node["right"])
            return (f"({left} using learned phrase '{node['learned_phrase']}' "
                    f"as exact {node['operation']} {right})")

        tree = result.procedure[0]
        sources = ", ".join(f"'{phrase}'" for phrase in result.evidence_phrases)
        return (f"The generated function evaluates {describe(tree)}. The operator "
                f"phrases were learned from {sources}; the artifact records "
                f"{result.evidence_examples} aligned operator examples and "
                f"{result.validation_cases} exact-output probes. This validates "
                f"the emitted expression against those probes. Artifact id: "
                f"{result.provenance_id}.")
    if result.domain == "math_map":
        return ("The generated function applies the learned exact math "
                "expression independently to each integer in the input list. "
                f"Its operator wording is supported by "
                f"{result.evidence_examples} aligned examples; the combined "
                f"artifact passed {result.validation_cases} list probes. "
                f"Artifact id: {result.provenance_id}.")
    if result.domain == "list_math_map":
        return ("The generated function first applies its learned list "
                "procedure, then maps the exact learned math expression over "
                f"the resulting values. Both stages and "
                f"{result.validation_cases} composed probes are recorded. "
                f"Artifact id: {result.provenance_id}.")
    if result.domain == "unit":
        descriptor = result.procedure[0]
        return (f"The function converts {descriptor['source_unit']} to "
                f"{descriptor['target_unit']} by the learned exact ratio "
                f"{descriptor['ratio']}. The source-unit path and "
                f"{result.evidence_examples} aligned quantity examples are "
                f"recorded in provenance. "
                f"Artifact id: {result.provenance_id}.")
    return (f"CRMS retained generated artifact {result.provenance_id} with "
            f"{result.evidence_examples} examples and "
            f"{result.validation_cases} parity checks.")


def show_generated_code_evidence(result: GeneratedCode) -> str:
    """Show exact source examples retained for a generated artifact."""
    if not result.evidence_details:
        return "This generated artifact has no retained training examples."
    lines = [f"Evidence for generated artifact {result.provenance_id}:"]
    if result.domain == "list":
        for row in result.evidence_details:
            lines.append(
                f"'{row['phrase']}': {row['input']} -> {row['output']}")
    elif result.domain == "list_math_map":
        for row in result.evidence_details:
            if "input" in row:
                lines.append(
                    f"'{row['phrase']}': {row['input']} -> {row['output']}")
            elif row.get("kind") == "grounded_number":
                lines.append(
                    f"Grounded number '{row['phrase']}' = {row['value']} "
                    f"[sources: {', '.join(row['sources'])}]")
            else:
                lines.append(
                    f"'{row['left']} {row['phrase']} {row['right']}' -> "
                    f"{row['answer']}")
    elif result.domain in {"math", "math_map"}:
        for row in result.evidence_details:
            if row.get("kind") == "grounded_number":
                lines.append(
                    f"Grounded number '{row['phrase']}' = {row['value']} "
                    f"[sources: {', '.join(row['sources'])}]")
            else:
                lines.append(
                    f"'{row['left']} {row['phrase']} {row['right']}' -> "
                    f"{row['answer']}")
    elif result.domain == "unit":
        for row in result.evidence_details:
            lines.append(
                f"{row['left_unit']} <-> {row['right_unit']}: "
                f"{row['example']}")
    return "\n".join(lines)


def generate_python(model: CRMSModel, instruction: str) -> GeneratedCode | None:
    """Render a resolved learned procedure as an inspectable Python function."""
    key = model._clean_instruction(instruction)
    procedure = model._procedures.get(key)
    evidence_phrases: set[str] = set()
    retrieval_traces: list[dict[str, Any]] = []
    resolution = "exact"
    if procedure is not None:
        evidence_phrases.add(key)
        retrieval_traces.append({"route": "exact", "instruction": key})
    else:
        # Ask through the same language retriever as ordinary CRMS use, across
        # distinct inputs. Only generate if retrieval resolves one procedure
        # consistently and gives us source phrases that retain demonstrations.
        probes = [[], [0], [1, -1, 2], [3, 3, -2, 0], [7, -4, 2, 7]]
        predictions = [model.predict(instruction, values) for values in probes]
        if any(item.status != "ok" or item.procedure is None for item in predictions):
            return None
        fingerprints = {json.dumps(item.procedure, sort_keys=True,
                                   separators=(",", ":")) for item in predictions}
        if len(fingerprints) != 1:
            return None
        evidence_phrases.update(
            phrase for item in predictions for phrase in item.evidence_phrases)
        resolution = "learned_retrieval"
        retrieval_traces = [{
            "input": values,
            "status": item.status,
            "evidence_phrases": sorted(set(item.evidence_phrases or [])),
            "matched_templates": sorted(set(item.matched_templates or [])),
            "matched_tokens": sorted(set(item.matched_tokens or [])),
            "matched_bigrams": sorted(set(item.matched_bigrams or [])),
            "retrieval_score": item.retrieval_score,
            "retrieval_margin": item.retrieval_margin,
        } for values, item in zip(probes, predictions)]
        procedure = tuple(Step(item["operation"], item["parameters"])
                          for item in predictions[0].procedure)
    example_records = [
        {"phrase": phrase, "input": inputs, "output": outputs}
        for phrase in sorted(evidence_phrases)
        for inputs, outputs in model._examples.get(phrase, [])
    ]
    examples = [(item["input"], item["output"]) for item in example_records]
    if procedure is None or not examples:
        return None

    expressions = [_python_expression(step) for step in procedure]
    if any(expression is None for expression in expressions):
        return None

    descriptors = [
        {"operation": step.operation, "parameters": dict(step.parameters)}
        for step in procedure
    ]
    literal = json.dumps(descriptors, sort_keys=True, separators=(",", ":"))
    example_literal = json.dumps(
        example_records,
        sort_keys=True, separators=(",", ":"))
    validation_inputs = [inputs for inputs, _ in examples]
    validation_inputs.extend([[], [0], [1, -1, 2], [3, 3, -2, 0]])
    validation_examples = []
    for values in validation_inputs:
        try:
            expected = _apply_procedure(procedure, values)
        except ZeroDivisionError:
            validation_examples.append({
                "input": values, "raises": "ZeroDivisionError"})
        else:
            validation_examples.append({"input": values, "output": expected})
    provenance = {
        "schema": "crms-code-provenance-v1",
        "requested_instruction": key,
        "resolution": resolution,
        "evidence_phrases": sorted(evidence_phrases),
        "retrieval_traces": retrieval_traces,
        "procedure": descriptors,
        "examples": example_records,
        "runtime_parity_examples": validation_examples,
    }
    provenance_id = "crms-code-v1-" + hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    provenance["artifact_id"] = provenance_id
    # ``repr`` emits Python literals (not JSON's null/true/false tokens), while
    # the digest above continues to use canonical JSON for cross-run identity.
    provenance_literal = repr(provenance)
    source = (
        '"""CRMS-generated standalone implementation of a learned list rule.\n'
        f"Instruction: {key}\n\n"
        "Contract: transform accepts a list of integers and returns a new list\n"
        "of integers. The learned examples and provenance are included below.\n"
        '"""\n'
        f"PROCEDURE = {literal}\n\n"
        f"CRMS_PROVENANCE = {provenance_literal}\n\n"
        f"EVIDENCE_EXAMPLES = {example_literal}\n\n"
        f"VALIDATION_EXAMPLES = {repr(validation_examples)}\n\n"
        "def transform(values: list[int]) -> list[int]:\n"
        '    """Apply the CRMS-learned transformation to integer values."""\n'
        "    if not isinstance(values, list) or any(type(x) is not int for x in values):\n"
        "        raise TypeError('values must be a list of integers')\n"
        "    xs = list(values)\n"
        + "".join(f"    # {step.operation}: {_step_description(step)}\n"
                  f"    xs = {expression}\n"
                  for step, expression in zip(procedure, expressions))
        + "    return xs\n"
        "\n"
        "def validate_examples() -> bool:\n"
        '    """Check parity with CRMS on the recorded validation inputs."""\n'
        "    for example in VALIDATION_EXAMPLES:\n"
        "        try:\n"
        "            actual = transform(example['input'])\n"
        "        except ZeroDivisionError:\n"
        "            if example.get('raises') != 'ZeroDivisionError':\n"
        "                return False\n"
        "        else:\n"
        "            if 'raises' in example or actual != example['output']:\n"
        "                return False\n"
        "    return True\n"
    )
    ast.parse(source)
    compiled = compile(source, "<crms-generated>", "exec")
    namespace: dict[str, Any] = {"__name__": "crms_generated"}
    exec(compiled, namespace)
    transform = namespace["transform"]

    for values in validation_inputs:
        try:
            expected = _apply_procedure(procedure, values)
        except ZeroDivisionError:
            try:
                transform(list(values))
            except ZeroDivisionError:
                continue
            raise RuntimeError(
                "generated code did not preserve the learned operation's domain")
        actual = transform(list(values))
        if actual != expected:
            raise RuntimeError("generated code disagrees with the learned procedure")

    return GeneratedCode(
        instruction=key,
        source=source,
        evidence_examples=len(examples),
        validation_cases=len(validation_inputs),
        procedure=tuple(descriptors),
        evidence_phrases=tuple(sorted(evidence_phrases)),
        provenance_id=provenance_id,
        evidence_details=tuple(example_records),
    )


def _math_node_descriptor(node: Any) -> dict[str, Any]:
    if isinstance(node, MathLiteral):
        if isinstance(node.value, Fraction):
            return {"kind": "literal", "numerator": node.value.numerator,
                    "denominator": node.value.denominator}
        return {"kind": "literal", "value": node.value}
    if isinstance(node, MathVariable):
        return {"kind": "variable", "name": node.name}
    if isinstance(node, MathBinary):
        descriptor = {
            "kind": "binary",
            "operation": node.operation,
            "left": _math_node_descriptor(node.left),
            "right": _math_node_descriptor(node.right),
        }
        if node.operator_phrase == ("implicit",):
            descriptor["operator_source"] = "implicit_multiplication"
        elif node.operator_phrase in {(symbol,) for symbol in {
                "+", "-", "−", "*", "×", "/", "÷", "%"}}:
            descriptor["operator_source"] = "standard_symbol"
            descriptor["notation"] = node.operator_phrase[0]
        else:
            descriptor["operator_source"] = "learned_phrase"
            descriptor["learned_phrase"] = " ".join(node.operator_phrase)
        return descriptor
    raise ValueError("unsupported math expression node")


def _math_node_variables(node: Any) -> set[str]:
    if isinstance(node, MathLiteral):
        return set()
    if isinstance(node, MathVariable):
        return {node.name}
    if isinstance(node, MathBinary):
        return _math_node_variables(node.left) | _math_node_variables(node.right)
    raise ValueError("unsupported math expression node")


def _render_math_node(node: Any) -> str:
    if isinstance(node, MathLiteral):
        if isinstance(node.value, Fraction):
            return (f"Fraction({node.value.numerator}, {node.value.denominator})")
        return repr(node.value)
    if isinstance(node, MathVariable):
        return node.name
    if isinstance(node, MathBinary):
        left, right = _render_math_node(node.left), _render_math_node(node.right)
        if node.operation == "divide":
            return f"(Fraction({left}) / Fraction({right}))"
        operator = {"add": "+", "subtract": "-", "multiply": "*",
                    "modulo": "%"}.get(
            node.operation)
        if operator is None:
            raise ValueError("unsupported learned math operation")
        return f"({left} {operator} {right})"
    raise ValueError("unsupported math expression node")


def _evaluate_math_node(node: Any, values: dict[str, int]) -> Any:
    """Independent scalar evaluator used to check rendered expression behavior."""
    from fractions import Fraction

    if isinstance(node, MathLiteral):
        return Fraction(node.value)
    if isinstance(node, MathVariable):
        return Fraction(values[node.name])
    if isinstance(node, MathBinary):
        left = _evaluate_math_node(node.left, values)
        right = _evaluate_math_node(node.right, values)
        if node.operation == "add":
            return left + right
        if node.operation == "subtract":
            return left - right
        if node.operation == "multiply":
            return left * right
        if node.operation == "divide":
            return left / right
        if node.operation == "modulo":
            return left % right
    raise ValueError("unsupported math expression node")


def generate_math_python(
        model: CRMSMath, expression: str, *,
        grounded_cardinals: dict[tuple[str, ...], tuple[int, tuple[str, ...]]] | None = None
        ) -> GeneratedCode | None:
    """Render an exact learned scalar expression as a standalone Python function."""
    question = expression.strip()
    if not re.match(r"^(?:what\s+is|how\s+much\s+is|calculate|compute)\b",
                    question, flags=re.IGNORECASE):
        question = f"What is {question}?"
    expression_tokens = model._expression_tokens(question)
    if expression_tokens is None:
        return None
    parser = _ExpressionParser(
        model, expression_tokens, grounded_cardinals or {})
    try:
        node = parser.parse()
    except ValueError:
        return None
    if not isinstance(node, (MathBinary, MathLiteral, MathVariable)):
        return None

    def has_unit(value: Any) -> bool:
        if isinstance(value, MathLiteral):
            return value.unit is not None
        if isinstance(value, MathBinary):
            return has_unit(value.left) or has_unit(value.right)
        return False

    if has_unit(node):
        return None
    variable_names = sorted(_math_node_variables(node))
    if not all(re.fullmatch(r"[A-Za-z]", name) for name in variable_names):
        return None
    used: dict[tuple[str, ...], str] = {}

    def collect_operations(value: Any) -> None:
        if not isinstance(value, MathBinary):
            return
        used[value.operator_phrase] = value.operation
        collect_operations(value.left)
        collect_operations(value.right)

    collect_operations(node)
    evidence_phrases = tuple(sorted(
        " ".join(phrase) for phrase in used if phrase in model._examples))
    operator_examples = [
        {"phrase": " ".join(phrase), "left": str(left), "right": str(right),
         "answer": _format(answer)}
        for phrase in sorted(used)
        if phrase in model._examples
        for (left, right), answer in sorted(model._examples[phrase].items())
    ]
    standard_operators = [
        {"notation": phrase[0], "operation": operation}
        for phrase, operation in sorted(used.items())
        if len(phrase) == 1 and phrase[0] in {
                "+", "-", "−", "*", "×", "/", "÷", "%"}
    ]
    descriptor = _math_node_descriptor(node)
    procedure = (descriptor,)
    validation_inputs = (
        [{}] if not variable_names else [
            {name: sample[index % len(sample)]
             for index, name in enumerate(variable_names)}
            for sample in ((-2, 3, 5), (0, 1, -4), (7, -3, 2), (4, 6, -1),
                           (9, 2, 8))
        ])
    validation_cases = []
    for inputs in validation_inputs:
        try:
            expected = _evaluate_math_node(node, inputs)
        except ZeroDivisionError:
            continue
        validation_cases.append({
            "inputs": inputs,
            "output": f"{expected.numerator}/{expected.denominator}",
        })
    if not validation_cases:
        return None

    provenance = {
        "schema": "crms-math-code-provenance-v1",
        "requested_expression": question,
        "expression_tree": descriptor,
        "learned_phrases": list(evidence_phrases),
        "operator_examples": operator_examples,
        "standard_operators": standard_operators,
        "uses_implicit_multiplication": ("implicit",) in used,
        "grounded_number_evidence": [
            {"phrase": " ".join(phrase), "value": value,
             "sources": list(sources)}
            for phrase, (value, sources) in sorted(parser.number_evidence.items())
        ],
        "validation_cases": validation_cases,
    }
    provenance_id = "crms-code-v1-" + hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    provenance["artifact_id"] = provenance_id
    provenance_literal = repr(provenance)
    parameters = ", ".join(variable_names)
    function_signature = f"def compute({parameters}):"
    source = (
        '"""CRMS-generated standalone implementation of a learned math expression.\n'
        f"Expression: {question}\n\n"
        "Contract: compute accepts integer values for the listed variables and "
        "returns an exact integer or fractions.Fraction.\n"
        '"""\n'
        "from fractions import Fraction\n\n"
        f"PROCEDURE = {repr(procedure)}\n\n"
        f"CRMS_PROVENANCE = {provenance_literal}\n\n"
        f"VALIDATION_CASES = {repr(validation_cases)}\n\n"
        f"{function_signature}\n"
        '    """Evaluate the CRMS-learned exact expression."""\n'
        + "".join(
            f"    if not isinstance({name}, int) or isinstance({name}, bool):\n"
            f"        raise TypeError('{name} must be an integer')\n"
            f"    if abs({name}).bit_length() > 4096:\n"
            f"        raise OverflowError('{name} exceeds CRMS arithmetic bound')\n"
            for name in variable_names)
        + f"    value = {_render_math_node(node)}\n"
        "    exact_value = Fraction(value)\n"
        "    if max(abs(exact_value.numerator).bit_length(), "
        "exact_value.denominator.bit_length()) > 4096:\n"
        "        raise OverflowError('exact result exceeds CRMS arithmetic bound')\n"
        "    return value\n\n"
        "def validate_examples() -> bool:\n"
        '    """Check output parity on deterministic scalar probes."""\n'
        "    return all(compute(**row['inputs']) == "
        "Fraction(row['output']) for row in VALIDATION_CASES)\n"
    )
    ast.parse(source)
    namespace: dict[str, Any] = {"__name__": "crms_generated"}
    exec(compile(source, "<crms-math-generated>", "exec"), namespace)
    if not namespace["validate_examples"]():
        return None
    return GeneratedCode(
        instruction=question,
        source=source,
        evidence_examples=len(operator_examples),
        validation_cases=len(validation_cases),
        procedure=procedure,
        evidence_phrases=evidence_phrases,
        provenance_id=provenance_id,
        domain="math",
        evidence_details=tuple(operator_examples) + tuple(
            {"kind": "grounded_number", "phrase": " ".join(phrase),
             "value": value, "sources": list(sources)}
            for phrase, (value, sources) in sorted(parser.number_evidence.items())),
    )


def generate_mapped_math_python(
        model: CRMSMath, instruction: str, *,
        grounded_cardinals: dict[
            tuple[str, ...], tuple[int, tuple[str, ...]]] | None = None
        ) -> GeneratedCode | None:
    """Compose a learned exact scalar expression over each integer in a list.

    The expression must use exactly the variable ``x`` and no units. The
    scalar expression is independently rendered by ``generate_math_python``;
    the list wrapper adds a fixed input contract and exact parity probes.
    """
    patterns = (
        re.compile(
            r"\s*(?:please\s+)?apply\s+(.+?)\s+to\s+each\s+"
            r"(?:integer|number|value|item)(?:\s+in\s+(?:the\s+)?"
            r"(?:list|input))?\s*[.!?]*\s*", re.IGNORECASE),
        re.compile(
            r"\s*(?:please\s+)?map\s+(.+?)\s+over\s+each\s+"
            r"(?:integer|number|value|item)(?:\s+in\s+(?:the\s+)?"
            r"(?:list|input))?\s*[.!?]*\s*", re.IGNORECASE),
    )
    expression = None
    for pattern in patterns:
        match = pattern.fullmatch(instruction)
        if match is not None:
            expression = match.group(1).strip()
            break
    if not expression:
        return None
    scalar = generate_math_python(
        model, expression, grounded_cardinals=grounded_cardinals)
    if scalar is None:
        return None
    try:
        scalar_ast = ast.parse(scalar.source)
        scalar_provenance = next(
            ast.literal_eval(statement.value)
            for statement in scalar_ast.body
            if isinstance(statement, ast.Assign)
            and any(isinstance(target, ast.Name)
                    and target.id == "CRMS_PROVENANCE"
                    for target in statement.targets))
    except (SyntaxError, StopIteration, ValueError, TypeError):
        return None
    if not isinstance(scalar_provenance, dict):
        return None

    question = expression.strip()
    if not re.match(r"^(?:what\s+is|how\s+much\s+is|calculate|compute)\b",
                    question, flags=re.IGNORECASE):
        question = f"What is {question}?"
    expression_tokens = model._expression_tokens(question)
    if expression_tokens is None:
        return None
    parser = _ExpressionParser(model, expression_tokens,
                               grounded_cardinals or {})
    try:
        node = parser.parse()
    except ValueError:
        return None
    if (not isinstance(node, (MathBinary, MathLiteral, MathVariable))
            or _math_node_variables(node) != {"x"}):
        return None

    def contains_unit(value: Any) -> bool:
        if isinstance(value, MathLiteral):
            return value.unit is not None
        return (isinstance(value, MathBinary)
                and (contains_unit(value.left) or contains_unit(value.right)))

    if contains_unit(node):
        return None

    validation_inputs = ([], [0], [1, -1, 2], [4, 4, -1])
    validation_cases = []
    for values in validation_inputs:
        outputs = [_evaluate_math_node(node, {"x": value}) for value in values]
        validation_cases.append({
            "input": list(values),
            "output": [[value.numerator, value.denominator]
                       for value in outputs],
        })
    descriptor = {
        "operation": "map_exact_math_expression",
        "variable": "x",
        "expression": _math_node_descriptor(node),
        "input_type": "list[int]",
        "output_type": "list[exact rational]",
    }
    provenance = {
        "schema": "crms-math-map-code-provenance-v1",
        "requested_instruction": instruction.strip(),
        "expression_artifact_id": scalar.provenance_id,
        "scalar_artifact_provenance": scalar_provenance,
        "expression": _math_node_descriptor(node),
        "descriptor": descriptor,
        "evidence_phrases": list(scalar.evidence_phrases),
        "evidence_details": list(scalar.evidence_details),
        "validation_cases": validation_cases,
        "bounds": {"maximum_list_length": 10_000,
                   "integer_bits": 4096},
    }
    provenance_id = "crms-code-v1-" + hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    provenance["artifact_id"] = provenance_id
    source = scalar.source.replace(
        "CRMS-generated standalone implementation of a learned math expression.",
        "CRMS-generated standalone list mapping over a learned math expression.",
        1).replace(
        "def validate_examples() -> bool:",
        "def validate_math_examples() -> bool:", 1)
    if source == scalar.source:
        return None
    source = re.sub(
        r"^CRMS_PROVENANCE = .*?$",
        "CRMS_PROVENANCE = " + repr(provenance), source,
        count=1, flags=re.MULTILINE)
    source += (
        "\n\nMAP_VALIDATION_CASES = " + repr(validation_cases) + "\n\n"
        "def transform(values: list[int]) -> list[int | Fraction]:\n"
        '    """Apply the exact learned expression to every integer value."""\n'
        "    if not isinstance(values, list) or len(values) > 10000:\n"
        "        raise TypeError('values must be a list of at most 10000 integers')\n"
        "    if any(not isinstance(value, int) or isinstance(value, bool)\n"
        "           for value in values):\n"
        "        raise TypeError('values must contain only integers')\n"
        "    return [compute(x=value) for value in values]\n\n"
        "def validate_examples() -> bool:\n"
        '    """Check scalar and list behavior against exact math evaluation."""\n'
        "    if not validate_math_examples():\n"
        "        return False\n"
        "    for row in MAP_VALIDATION_CASES:\n"
        "        expected = [Fraction(numerator, denominator)\n"
        "                    for numerator, denominator in row['output']]\n"
        "        actual = [Fraction(value) for value in transform(row['input'])]\n"
        "        if actual != expected:\n"
        "            return False\n"
        "    return True\n"
    )
    try:
        ast.parse(source)
        namespace: dict[str, Any] = {"__name__": "crms_generated"}
        exec(compile(source, "<crms-math-map-generated>", "exec"), namespace)
        if not namespace["validate_examples"]():
            return None
    except (SyntaxError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None
    return GeneratedCode(
        instruction=instruction.strip(), source=source,
        evidence_examples=scalar.evidence_examples,
        validation_cases=len(validation_cases), procedure=(descriptor,),
        evidence_phrases=scalar.evidence_phrases,
        provenance_id=provenance_id, domain="math_map",
        evidence_details=scalar.evidence_details)


def _split_list_then_math_instruction(
        instruction: str) -> tuple[str, str] | None:
    """Parse the supported two-stage request shapes without resolving them."""
    suffix = (
        r"\s*(?:apply|map)\s+(.+?)\s+(?:to|over)\s+each\s+"
        r"(?:integer|number|value|item)(?:\s+in\s+(?:the\s+)?"
        r"(?:list|input))?\s*[.!?]*\s*")
    match = re.fullmatch(
        r"\s*(.+?)\s*,?\s+(?:(?:and\s+)?then\s+)" + suffix,
        instruction, flags=re.IGNORECASE)
    if match is None:
        # A common alternative ordering: "After [list operation], apply ...".
        match = re.fullmatch(
            r"\s*after\s+(.+?),\s*" + suffix,
            instruction, flags=re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).strip(), match.group(2).strip()


def diagnose_list_then_math_support(
        model: CRMSModel, math_model: CRMSMath, instruction: str, *,
        grounded_cardinals: dict[
            tuple[str, ...], tuple[int, tuple[str, ...]]] | None = None
        ) -> str | None:
    """Return a grounded next-step message for a recognized failed composition."""
    parts = _split_list_then_math_instruction(instruction)
    if parts is None:
        return None
    list_instruction, expression = parts
    list_artifact = generate_python(model, list_instruction)
    if list_artifact is None:
        return ("I couldn't resolve the first list step to a supported learned "
                "procedure. Teach that operation with input/output examples "
                "or rephrase it using a procedure CRMS already knows.")
    math_instruction = f"apply {expression} to each value in the list"
    math_artifact = generate_mapped_math_python(
        math_model, math_instruction, grounded_cardinals=grounded_cardinals)
    if math_artifact is None:
        return ("The list step is supported, but I couldn't resolve the math "
                "expression using learned exact operators. Teach the missing "
                "operator with examples or rephrase it with operators CRMS "
                "already knows.")
    return None


def generate_list_then_math_python(
        model: CRMSModel, math_model: CRMSMath, instruction: str, *,
        grounded_cardinals: dict[
            tuple[str, ...], tuple[int, tuple[str, ...]]] | None = None
        ) -> GeneratedCode | None:
    """Compose a learned list procedure with an exact learned math mapping."""
    parts = _split_list_then_math_instruction(instruction)
    if parts is None:
        return None
    list_instruction, expression = parts
    list_artifact = generate_python(model, list_instruction)
    if list_artifact is None:
        return None
    math_instruction = f"apply {expression} to each value in the list"
    math_artifact = generate_mapped_math_python(
        math_model, math_instruction, grounded_cardinals=grounded_cardinals)
    if math_artifact is None:
        return None

    def rename_names(source: str, names: dict[str, str]) -> str:
        for old, new in names.items():
            source = re.sub(rf"\b{re.escape(old)}\b", new, source)
        return source

    list_source = rename_names(list_artifact.source, {
        "transform": "transform_list",
        "validate_examples": "validate_list_examples",
        "PROCEDURE": "LIST_PROCEDURE",
        "CRMS_PROVENANCE": "LIST_PROVENANCE",
        "EVIDENCE_EXAMPLES": "LIST_EVIDENCE_EXAMPLES",
        "VALIDATION_EXAMPLES": "LIST_VALIDATION_EXAMPLES",
    })
    math_source = rename_names(math_artifact.source, {
        "transform": "map_math",
        "validate_examples": "validate_math_map_examples",
        "CRMS_PROVENANCE": "MATH_MAP_PROVENANCE",
        "MAP_VALIDATION_CASES": "MATH_MAP_VALIDATION_CASES",
    })
    validation_inputs = ([], [0], [1, -1, 2], [4, 4, -1])
    namespace: dict[str, Any] = {"__name__": "crms_generated"}
    try:
        component_source = list_source + "\n\n" + math_source
        exec(compile(component_source, "<crms-composed-components>", "exec"),
             namespace)
        list_steps = tuple(Step(
            row["operation"], dict(row.get("parameters", {})))
            for row in list_artifact.procedure)
        math_question = expression
        if not re.match(
                r"^(?:what\s+is|how\s+much\s+is|calculate|compute)\b",
                math_question, flags=re.IGNORECASE):
            math_question = f"What is {math_question}?"
        math_tokens = math_model._expression_tokens(math_question)
        if math_tokens is None:
            return None
        math_node = _ExpressionParser(
            math_model, math_tokens, grounded_cardinals or {}).parse()
        expected_cases = []
        for values in validation_inputs:
            intermediate = _apply_procedure(list_steps, values)
            output = [_evaluate_math_node(math_node, {"x": value})
                      for value in intermediate]
            expected_cases.append({
                "input": list(values),
                "output": [[Fraction(value).numerator,
                            Fraction(value).denominator]
                           for value in output],
            })
        provenance = {
            "schema": "crms-list-then-math-code-provenance-v1",
            "requested_instruction": instruction.strip(),
            "list_artifact_id": list_artifact.provenance_id,
            "list_provenance": namespace.get("LIST_PROVENANCE"),
            "math_map_artifact_id": math_artifact.provenance_id,
            "math_map_provenance": namespace.get("MATH_MAP_PROVENANCE"),
            "stage_order": ["learned_list_procedure", "exact_math_map"],
            "validation_cases": expected_cases,
        }
        provenance_id = "crms-code-v1-" + hashlib.sha256(
            json.dumps(provenance, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")).hexdigest()
        provenance["artifact_id"] = provenance_id
        combined = (
            component_source
            + "\n\nCOMPOSITION_PROVENANCE = " + repr(provenance) + "\n"
            + "COMPOSITION_VALIDATION_CASES = " + repr(expected_cases) + "\n\n"
            + "def transform(values: list[int]) -> list[int | Fraction]:\n"
            + '    """Run the learned list stage, then exact math per value."""\n'
            + "    return map_math(transform_list(values))\n\n"
            + "def validate_examples() -> bool:\n"
            + '    """Check both component artifacts and the composed behavior."""\n'
            + "    if not validate_list_examples() or not validate_math_map_examples():\n"
            + "        return False\n"
            + "    for row in COMPOSITION_VALIDATION_CASES:\n"
            + "        expected = [Fraction(n, d) for n, d in row['output']]\n"
            + "        actual = [Fraction(value) for value in transform(row['input'])]\n"
            + "        if actual != expected:\n"
            + "            return False\n"
            + "    return True\n"
        )
        ast.parse(combined)
        exec(compile(combined, "<crms-list-then-math>", "exec"), namespace)
        if not namespace["validate_examples"]():
            return None
    except (SyntaxError, TypeError, ValueError, OverflowError,
            ZeroDivisionError, KeyError):
        return None
    details = tuple(list_artifact.evidence_details) + tuple(
        math_artifact.evidence_details)
    return GeneratedCode(
        instruction=instruction.strip(), source=combined,
        evidence_examples=(list_artifact.evidence_examples
                           + math_artifact.evidence_examples),
        validation_cases=len(expected_cases),
        procedure=tuple(list_artifact.procedure) + tuple(math_artifact.procedure),
        evidence_phrases=tuple(dict.fromkeys(
            (*list_artifact.evidence_phrases,
             *math_artifact.evidence_phrases))),
        provenance_id=provenance_id, domain="list_math_map",
        evidence_details=details)


def generate_unit_conversion_python(
        model: CRMSMath, instruction: str) -> GeneratedCode | None:
    """Render a source-backed unit ratio as an exact standalone function."""
    patterns = (
        re.compile(
            r"\s*(?:please\s+)?convert\s+(?P<variable>[a-z])\s+"
            r"(?P<source>.+?)\s+(?:to|into)\s+(?P<target>.+?)"
            r"\s*[.!?]*\s*", re.IGNORECASE),
        re.compile(
            r"\s*(?:please\s+)?convert\s+(?:the\s+)?"
            r"(?:amount|quantity|value)\s+from\s+(?P<source>.+?)\s+"
            r"(?:to|into)\s+(?P<target>.+?)\s*[.!?]*\s*",
            re.IGNORECASE),
    )
    match = None
    for pattern in patterns:
        match = pattern.fullmatch(instruction)
        if match is not None:
            break
    if match is None:
        return None
    variable = (match.groupdict().get("variable") or "amount").casefold()
    try:
        source = model._unit_name(match.group("source"))
        target = model._unit_name(match.group("target"))
    except ValueError:
        return None
    if source == target:
        return None
    graph = model._unit_edges(model._unit_examples)
    if source not in graph:
        return None

    # Resolve one deterministic evidence path and multiply its exact ratios.
    scales = {source: Fraction(1)}
    parents: dict[tuple[str, ...], tuple[str, ...] | None] = {source: None}
    queue = [source]
    while queue and target not in scales:
        current = queue.pop(0)
        for neighbor, factor in sorted(graph[current].items()):
            if neighbor in scales:
                continue
            scales[neighbor] = scales[current] * factor
            parents[neighbor] = current
            queue.append(neighbor)
    if target not in scales:
        return None
    ratio = scales[target]
    path = [target]
    while path[-1] != source:
        parent = parents[path[-1]]
        if parent is None:
            return None
        path.append(parent)
    path.reverse()
    edge_examples = []
    for left, right in zip(path, path[1:]):
        pair = tuple(sorted((left, right)))
        rows = model._unit_examples.get(pair, {})
        if len(rows) < 2:
            return None
        edge_examples.extend({
            "left_unit": " ".join(pair[0]),
            "right_unit": " ".join(pair[1]),
            "example": example,
        } for _quantities, example in sorted(rows.items()))
    validation_cases = []
    for amount in (-3, 0, 1, 17):
        value = Fraction(amount) * ratio
        validation_cases.append({
            "input": amount,
            "output": f"{value.numerator}/{value.denominator}",
        })
    descriptor = {
        "operation": "exact_unit_conversion",
        "variable": variable,
        "source_unit": " ".join(source),
        "target_unit": " ".join(target),
        "ratio": f"{ratio.numerator}/{ratio.denominator}",
    }
    provenance = {
        "schema": "crms-unit-code-provenance-v1",
        "requested_conversion": instruction.strip(),
        "descriptor": descriptor,
        "evidence_path": [" ".join(unit) for unit in path],
        "aligned_examples": edge_examples,
        "validation_cases": validation_cases,
    }
    provenance_id = "crms-code-v1-" + hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    provenance["artifact_id"] = provenance_id
    examples_literal = repr(edge_examples)
    validation_literal = repr(validation_cases)
    source_code = (
        '"""CRMS-generated exact conversion licensed by aligned examples.\n'
        f"Conversion: {instruction.strip()}\n\n"
        "Contract: convert_amount accepts an integer and returns an exact "
        "fractions.Fraction. Results beyond CRMS's 4096-bit bound raise "
        "OverflowError.\n"
        '"""\n'
        "from fractions import Fraction\n\n"
        f"PROCEDURE = {repr((descriptor,))}\n\n"
        f"CRMS_PROVENANCE = {repr(provenance)}\n\n"
        f"ALIGNED_EXAMPLES = {examples_literal}\n\n"
        f"VALIDATION_CASES = {validation_literal}\n\n"
        "def convert_amount(amount: int) -> Fraction:\n"
        '    """Convert using the exact ratio from the recorded examples."""\n'
        "    if not isinstance(amount, int) or isinstance(amount, bool):\n"
        "        raise TypeError('amount must be an integer')\n"
        "    if abs(amount).bit_length() > 4096:\n"
        "        raise OverflowError('input exceeds CRMS arithmetic bound')\n"
        f"    result = Fraction(amount * {ratio.numerator}, {ratio.denominator})\n"
        "    if max(abs(result.numerator).bit_length(), "
        "result.denominator.bit_length()) > 4096:\n"
        "        raise OverflowError('exact conversion exceeds CRMS arithmetic bound')\n"
        "    return result\n\n"
        "def validate_examples() -> bool:\n"
        '    """Check exact parity on deterministic conversion amounts."""\n'
        "    return all(convert_amount(row['input']) == "
        "Fraction(row['output']) for row in VALIDATION_CASES)\n"
    )
    ast.parse(source_code)
    namespace: dict[str, Any] = {"__name__": "crms_generated"}
    exec(compile(source_code, "<crms-unit-generated>", "exec"), namespace)
    if not namespace["validate_examples"]():
        return None
    return GeneratedCode(
        instruction=instruction.strip(),
        source=source_code,
        evidence_examples=len(edge_examples),
        validation_cases=len(validation_cases),
        procedure=(descriptor,),
        evidence_phrases=(),
        provenance_id=provenance_id,
        domain="unit",
        evidence_details=tuple(edge_examples),
    )


def natural_language_request(text: str) -> str | None:
    """Extract a bounded family of natural-language Python code requests."""
    import re

    patterns = (
        # Explicit language-led task requests such as "Can you sort this in
        # Python?" The task still has to resolve through learned CRMS evidence.
        r"(?:(?:can|could|would)\s+you|please|i\s+(?:want|need)\s+to)\s+"
        r"(.+?)\s+in\s+(?:the\s+)?(?:python|py)\s*",
        # Polite requests such as "Could you please write me a function ...?"
        r"(?:(?:please\s+)?|(?:can|could|would)\s+you\s+(?:please\s+)?)"
        r"(?:write|generate|create)\s+(?:me\s+)?"
        r"(?:(?:a|some)\s+)?(?:python\s+|py\s+)?"
        r"(?:code|program|script|function)(?:\s+in\s+(?:python|py))?\s+"
        r"(?:that|to|which\s+does)\s+(.+?)\s*",
        # "I need Python code that ..." / "I'd like a Python function to ..."
        r"(?:i\s+need|i\s+want|i'd\s+like)\s+"
        r"(?:(?:some|a)\s+)?(?:python\s+|py\s+)?"
        r"(?:code|program|script|function)\s+(?:that|to)\s+(.+?)\s*",
        # "I need you to write Python code that ..."
        r"i\s+(?:need|want)\s+you\s+to\s+"
        r"(?:write|generate|create)\s+(?:me\s+)?"
        r"(?:(?:a|some)\s+)?(?:python\s+|py\s+)?"
        r"(?:code|program|script|function)(?:\s+in\s+(?:python|py))?\s+"
        r"(?:that|to|which\s+does)\s+(.+?)\s*",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern + r"[.!?]?", text.strip(),
                             flags=re.IGNORECASE)
        if match:
            instruction = match.group(1).strip().rstrip(".!? ")
            return instruction or None
    return None


def render(result: GeneratedCode | None, instruction: str) -> str:
    if result is None:
        return (f"I could not resolve '{instruction}' to a supported learned "
                "operation with enough evidence to generate code. Teach the "
                "operation with examples or clarify the request first.")
    sources = ", ".join(f"'{phrase}'" for phrase in result.evidence_phrases)
    if result.domain == "math":
        basis = (f"using standard arithmetic notation and learned evidence from {sources} "
                 if result.evidence_phrases else
                 "using standard arithmetic notation without learned word operators ")
        return (f"Generated exact-arithmetic Python for '{result.instruction}', "
                f"{basis}"
                f"({result.evidence_examples} operator examples; exact-output "
                f"parity checked on {result.validation_cases} scalar inputs). "
                f"The standalone source records its expression and "
                f"provenance id {result.provenance_id}:\n\n"
                f"```python\n{result.source}```")
    if result.domain == "math_map":
        return (f"Generated exact-arithmetic list-mapping Python for "
                f"'{result.instruction}' using learned evidence from {sources} "
                f"({result.evidence_examples} operator examples; exact list "
                f"parity checked on {result.validation_cases} probes). The "
                f"artifact retains the scalar expression provenance and its "
                f"composition record, id {result.provenance_id}:\n\n"
                f"```python\n{result.source}```")
    if result.domain == "list_math_map":
        return (f"Generated composed Python for '{result.instruction}' from "
                f"the learned list procedure and exact math evidence "
                f"({result.evidence_examples} aligned examples; exact output "
                f"checked on {result.validation_cases} composed probes). The "
                f"artifact records both stage provenances, id "
                f"{result.provenance_id}:\n\n```python\n{result.source}```")
    if result.domain == "unit":
        return (f"Generated exact Python conversion for '{result.instruction}' "
                f"from {result.evidence_examples} aligned quantity examples; "
                f"wrapper parity checked on {result.validation_cases} amounts. "
                f"The standalone source retains its evidence path and provenance "
                f"id {result.provenance_id}:\n\n"
                f"```python\n{result.source}```")
    return (f"Generated Python for '{result.instruction}', using learned evidence "
            f"from {sources} ({result.evidence_examples} examples; "
            f"wrapper parity checked on "
            f"{result.validation_cases} inputs). The source includes "
            f"source-linked evidence examples, separate runtime-parity cases, "
            f"validate_examples(), and provenance id {result.provenance_id}. "
            "The artifact is standalone "
            "for its supported operation subset:\n\n"
            f"```python\n{result.source}```")
