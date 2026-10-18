"""Exact, example-grounded arithmetic with learned natural-language operators.

This math slice handles exact arithmetic in a small set of explicit natural-
language question frames. Operator phrases are learned from input/output
examples; no English operator synonyms are built in.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from math import isqrt
import json
import re
from pathlib import Path
from typing import Mapping

from crms_text import tokens


_QUESTION_BODY_PATTERNS = (
    re.compile(r"\s*what\s+does\s+(.+?)\s+equal\s*\??\s*", re.IGNORECASE),
    re.compile(r"\s*what\s+is\s+(?:the\s+)?result\s+of\s+"
               r"(.+?)\s*\??\s*", re.IGNORECASE),
    re.compile(r"\s*(?:(?:can|could|would)\s+you\s+)?"
               r"(?:please\s+)?(?:calculate|compute)\s+"
               r"(.+?)\s*[?!.]*\s*", re.IGNORECASE),
    re.compile(r"\s*what\s+is\s+(.+?)\s*\??\s*", re.IGNORECASE),
    re.compile(r"\s*how\s+much\s+is\s+(.+?)\s*\??\s*", re.IGNORECASE),
)
_BINARY_EXPRESSION_RE = re.compile(
    r"\s*([+-]?\d{1,100})\s+(.+?)\s+([+-]?\d{1,100})\s*\Z")
_SOLVE_EQUATION_RE = re.compile(
    r"\s*solve\s+(.+?)\s+(?:equals|=)\s+(.+?)\s+for\s+([^\W\d_])\s*[?!.]*\s*",
    re.IGNORECASE | re.UNICODE)
_EXPRESSION_TOKEN_RE = re.compile(
    r"(?:\d{1,100}(?:\.\d{1,100})?|\.\d{1,100})(?:[eE][+-]?\d{1,3})?|"
    r"[^\W\d_]+(?:['’][^\W\d_]+)*|[()+*/%=]|[-−×÷]", re.UNICODE)
_INTEGER_RE = re.compile(r"[+-]?\d{1,100}\Z")
_NUMBER_LITERAL_RE = re.compile(
    r"(?:\d{1,100}(?:\.\d{1,100})?|\.\d{1,100})(?:[eE][+-]?\d{1,3})?\Z")
_FRACTION_RE = re.compile(r"([+-]?\d{1,100})/([1-9]\d{0,99})\Z")
_UNIT_QUANTITY_RE = re.compile(r"\s*([1-9]\d{0,99})\s+(.+?)\s*[.!?]*\s*\Z")
_UNIT_TEACH_RE = re.compile(r"\s*([1-9]\d{0,99})\s+(.+?)\s*\Z")
_UNIT_CONVERT_PATTERNS = (
    re.compile(r"\s*what\s+is\s+(.+?)\s+in\s+(.+?)\s*[?!.]*\s*\Z",
               re.IGNORECASE),
    re.compile(
        r"\s*(?:(?:please\s+)|(?:(?:can|could|would)\s+you"
        r"(?:\s+please)?\s+))?convert\s+(.+?)\s+(?:to|into)\s+"
        r"(.+?)\s*[?!.]*\s*\Z", re.IGNORECASE),
)
_NUMBER_CUE_WORDS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen",
    "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty", "thirty", "forty", "fifty", "sixty",
    "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "trillion", "dozen", "score", "half", "quarter",
})
_OPERATIONS = ("add", "subtract", "multiply", "divide", "modulo")
_SYMBOL_OPERATIONS = {
    "+": "add", "-": "subtract", "−": "subtract",
    "*": "multiply", "×": "multiply",
    "/": "divide", "÷": "divide", "%": "modulo",
}
_MAX_RESULT_BITS = 4096
_MAX_POLYNOMIAL_TERMS = 512


@dataclass(frozen=True)
class MathExpression:
    left: int
    operator_phrase: tuple[str, ...]
    right: int


@dataclass(frozen=True)
class MathLiteral:
    value: int | Fraction
    phrase: tuple[str, ...] | None = None
    sources: tuple[str, ...] = ()
    unit: tuple[str, ...] | None = None
    unit_dimension: tuple[str, ...] | None = None
    unit_scale: Fraction = Fraction(1)
    unit_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class MathVariable:
    name: str


@dataclass(frozen=True)
class MathBinary:
    left: "MathNode"
    operator_phrase: tuple[str, ...]
    operation: str
    right: "MathNode"


@dataclass(frozen=True)
class MathEquation:
    left: "MathNode"
    right: "MathNode"
    variable: str


MathNode = MathLiteral | MathVariable | MathBinary
Monomial = tuple[tuple[str, int], ...]
Polynomial = dict[Monomial, Fraction]


@dataclass(frozen=True)
class MathResult:
    status: str
    expression: MathExpression | MathBinary | MathEquation | None = None
    value: Fraction | str | None = None
    operation: str | None = None
    request: str | None = None
    examples: tuple[dict[str, str], ...] = ()
    number_evidence: tuple[dict[str, object], ...] = ()
    symbolic_terms: tuple[dict[str, object], ...] = ()
    solutions: tuple[Fraction, ...] = ()
    unit: str | None = None
    unit_evidence: tuple[dict[str, object], ...] = ()
    candidate_operations: tuple[str, ...] = ()
    contrastive_input: tuple[int, int] | None = None


def _fraction(value: str) -> Fraction:
    match = _FRACTION_RE.fullmatch(value.strip())
    if match:
        return Fraction(int(match.group(1)), int(match.group(2)))
    if _INTEGER_RE.fullmatch(value.strip()):
        return Fraction(int(value))
    raise ValueError("answer must be an integer or exact fraction such as 3/2")


def _format(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _evaluate(operation: str, left: int, right: int) -> Fraction:
    if operation == "add":
        return Fraction(left + right)
    if operation == "subtract":
        return Fraction(left - right)
    if operation == "multiply":
        return Fraction(left * right)
    if operation == "divide":
        if right == 0:
            raise ZeroDivisionError
        return Fraction(left, right)
    if operation == "modulo":
        if right == 0:
            raise ZeroDivisionError
        return Fraction(left % right)
    raise ValueError("unknown operation")


def _bounded_polynomial(terms: Polynomial) -> Polynomial:
    terms = {monomial: coefficient for monomial, coefficient in terms.items()
             if coefficient}
    if len(terms) > _MAX_POLYNOMIAL_TERMS:
        raise OverflowError("symbolic expression exceeds the term-count bound")
    if any(max(abs(value.numerator).bit_length(), value.denominator.bit_length())
           > _MAX_RESULT_BITS for value in terms.values()):
        raise OverflowError("exact result exceeds the arithmetic size bound")
    return terms


def _multiply_monomials(left: Monomial, right: Monomial) -> Monomial:
    powers: dict[str, int] = dict(left)
    for variable, exponent in right:
        powers[variable] = powers.get(variable, 0) + exponent
    return tuple(sorted(powers.items()))


def _evaluate_node(node: MathNode) -> Polynomial:
    if isinstance(node, MathLiteral):
        return {(): Fraction(node.value) * node.unit_scale}
    if isinstance(node, MathVariable):
        return {((node.name, 1),): Fraction(1)}
    left = _evaluate_node(node.left)
    right = _evaluate_node(node.right)
    if node.operation in {"add", "subtract"}:
        result = dict(left)
        sign = 1 if node.operation == "add" else -1
        for monomial, coefficient in right.items():
            result[monomial] = (result.get(monomial, Fraction(0))
                                + sign * coefficient)
    elif node.operation == "multiply":
        result: Polynomial = {}
        for left_monomial, left_coefficient in left.items():
            for right_monomial, right_coefficient in right.items():
                monomial = _multiply_monomials(left_monomial, right_monomial)
                result[monomial] = (result.get(monomial, Fraction(0))
                                    + left_coefficient * right_coefficient)
                if len(result) > _MAX_POLYNOMIAL_TERMS:
                    raise OverflowError("symbolic expression exceeds the term-count bound")
    elif node.operation == "divide":
        if not right:
            raise ZeroDivisionError
        if set(right) != {()}:
            raise _UnsupportedMath("division by a variable expression is not supported")
        divisor = right[()]
        if divisor == 0:
            raise ZeroDivisionError
        result = {monomial: coefficient / divisor
                  for monomial, coefficient in left.items()}
    elif node.operation == "modulo":
        if set(left) - {()} or set(right) - {()}:
            raise _UnsupportedMath(
                "remainder is supported only for exact constant operands")
        left_value = left.get((), Fraction(0))
        right_value = right.get((), Fraction(0))
        if right_value == 0:
            raise ZeroDivisionError
        return {(): left_value % right_value}
    else:
        raise ValueError("unknown operation")
    return _bounded_polynomial(result)


def _substitute_node(node: MathNode, bindings: Mapping[str, Fraction]) -> Fraction:
    """Evaluate the original expression tree directly at exact values.

    This interpreter is intentionally separate from polynomial reduction so
    equation candidates can be checked against the parsed source expressions.
    Unitful literals are represented in their learned base unit.
    """
    if isinstance(node, MathLiteral):
        return Fraction(node.value) * node.unit_scale
    if isinstance(node, MathVariable):
        return Fraction(bindings[node.name])
    left = _substitute_node(node.left, bindings)
    right = _substitute_node(node.right, bindings)
    if node.operation == "add":
        return left + right
    if node.operation == "subtract":
        return left - right
    if node.operation == "multiply":
        return left * right
    if node.operation == "divide":
        if right == 0:
            raise ZeroDivisionError
        return left / right
    if node.operation == "modulo":
        if right == 0:
            raise ZeroDivisionError
        return left % right
    raise ValueError("unknown operation in expression tree")


def _polynomial_value(terms: Polynomial) -> Fraction | str:
    if not terms:
        return Fraction(0)
    if set(terms) == {()}:
        return terms[()]
    ordered = sorted(
        terms.items(),
        key=lambda item: (-sum(power for _, power in item[0]), item[0]))
    output = ""
    for monomial, coefficient in ordered:
        if coefficient == 0:
            continue
        negative = coefficient < 0
        magnitude = abs(coefficient)
        variables = "*".join(
            name if power == 1 else f"{name}^{power}"
            for name, power in monomial)
        term = (("" if magnitude == 1 else _format(magnitude) + "*")
                + variables if variables else _format(magnitude))
        if not output:
            output = ("-" if negative else "") + term
        else:
            output += (" - " if negative else " + ") + term
    return output or "0"


class _UnknownOperator(ValueError):
    pass


class _UnknownNumber(ValueError):
    pass


class _UnsupportedMath(ValueError):
    pass


class _ExpressionParser:
    """Pratt parser for learned natural-language operators and integer leaves."""

    _PRECEDENCE = {"add": 1, "subtract": 1, "multiply": 2,
                   "divide": 2, "modulo": 2}

    def __init__(self, model: "CRMSMath", values: list[str],
                 number_words: Mapping[
                     tuple[str, ...], tuple[int, tuple[str, ...]]], *,
                 require_operator: bool = True) -> None:
        self.model = model
        self.values = values
        self.number_words = number_words
        self.require_operator = require_operator
        self.index = 0
        self.operator_count = 0
        self.number_evidence: dict[
            tuple[str, ...], tuple[int, tuple[str, ...]]
        ] = {}

    def _primary(self, depth: int) -> MathNode:
        if depth > 64 or self.index >= len(self.values):
            raise ValueError("expression is incomplete or too deeply nested")
        token = self.values[self.index]
        sign = 1
        if (token in {"+", "-", "−"} and self.index + 1 < len(self.values)
                and _NUMBER_LITERAL_RE.fullmatch(self.values[self.index + 1])):
            sign = -1 if token in {"-", "−"} else 1
            self.index += 1
            token = self.values[self.index]
        elif (token in {"+", "-", "−"} and self.index + 1 < len(self.values)
              and (self.values[self.index + 1] == "("
                   or (len(self.values[self.index + 1]) == 1
                       and self.values[self.index + 1].isalpha()))):
            negative = token in {"-", "−"}
            self.index += 1
            operand = self._primary(depth + 1)
            if not negative:
                return operand
            self.operator_count += 1
            return MathBinary(MathLiteral(-1), ("implicit",), "multiply", operand)
        if token == "(":
            self.index += 1
            value = self._expression(0, depth + 1)
            if self.index >= len(self.values) or self.values[self.index] != ")":
                raise ValueError("expression has an unmatched parenthesis")
            self.index += 1
            return value
        if _NUMBER_LITERAL_RE.fullmatch(token):
            self.index += 1
            unit_matches = self.model._matching_unit(self.values, self.index)
            if unit_matches:
                unit, width = unit_matches
                info = self.model._unit_info(unit)
                if info is not None:
                    self.index += width
                    dimension, scale, sources = info
                    display_unit = tuple(tokens(" ".join(
                        self.values[self.index - width:self.index])))
                    literal = (Fraction(Decimal(token))
                               if "." in token or "e" in token.casefold()
                               else int(token))
                    return MathLiteral(sign * literal, unit=display_unit,
                                       unit_dimension=dimension,
                                       unit_scale=scale,
                                       unit_sources=sources)
            literal = (Fraction(Decimal(token))
                       if "." in token or "e" in token.casefold()
                       else int(token))
            return MathLiteral(sign * literal)
        matches = [phrase for phrase in self.number_words
                   if self.values[self.index:self.index + len(phrase)] == list(phrase)]
        if matches:
            phrase = max(matches, key=len)
            value, sources = self.number_words[phrase]
            self.number_evidence[phrase] = (value, sources)
            self.index += len(phrase)
            unit_match = self.model._matching_unit(self.values, self.index)
            if unit_match:
                unit, width = unit_match
                info = self.model._unit_info(unit)
                if info is not None:
                    self.index += width
                    dimension, scale, unit_sources = info
                    display_unit = tuple(tokens(" ".join(
                        self.values[self.index - width:self.index])))
                    return MathLiteral(value, phrase, sources, display_unit,
                                       dimension, scale, unit_sources)
            return MathLiteral(value, phrase, sources)
        if len(token) == 1 and token.isalpha():
            self.index += 1
            return MathVariable(token)
        end = self.index
        while end < len(self.values) and self.values[end] not in {"(", ")"} \
                and not _NUMBER_LITERAL_RE.fullmatch(self.values[end]):
            if (self.values[end] in {"+", "-", "−"} and end + 1 < len(self.values)
                    and _NUMBER_LITERAL_RE.fullmatch(self.values[end + 1])):
                break
            if end > self.index and any(
                    self.values[end:end + len(phrase)] == list(phrase)
                    for phrase in self.model._examples):
                break
            end += 1
        unknown = " ".join(self.values[self.index:end]) or token
        raise _UnknownNumber(unknown)

    def _expression(self, minimum: int, depth: int = 0) -> MathNode:
        left = self._primary(depth)
        while self.index < len(self.values) and self.values[self.index] != ")":
            implicit = False
            try:
                phrase, operation = self._operator_at(self.index)
            except _UnknownOperator:
                token = self.values[self.index]
                starts_primary = (
                    token == "("
                    or (len(token) == 1 and token.isalpha())
                    or (not isinstance(left, MathLiteral)
                        and _NUMBER_LITERAL_RE.fullmatch(token) is not None))
                if not starts_primary:
                    raise
                phrase, operation = ("implicit",), "multiply"
                implicit = True
            precedence = self._PRECEDENCE[operation]
            if precedence < minimum:
                break
            if not implicit:
                self.index += len(phrase)
            self.operator_count += 1
            right = self._expression(precedence + 1, depth + 1)
            left = MathBinary(left, phrase, operation, right)
        return left

    def _operator_at(self, start: int) -> tuple[tuple[str, ...], str]:
        if start < len(self.values) and self.values[start] in _SYMBOL_OPERATIONS:
            symbol = self.values[start]
            return (symbol,), _SYMBOL_OPERATIONS[symbol]
        matches = [phrase for phrase in self.model._examples
                   if self.values[start:start + len(phrase)] == list(phrase)]
        if not matches:
            end = start
            while end < len(self.values) and self.values[end] not in {"(", ")"} \
                    and not _NUMBER_LITERAL_RE.fullmatch(self.values[end]):
                if (self.values[end] in {"+", "-", "−"} and end + 1 < len(self.values)
                        and _NUMBER_LITERAL_RE.fullmatch(self.values[end + 1])):
                    break
                end += 1
            unknown = " ".join(self.values[start:end]) or self.values[start]
            raise _UnknownOperator(unknown)
        phrase = max(matches, key=len)
        examples = self.model._examples[phrase]
        candidates = self.model._candidates(examples)
        if len(examples) < 2 or len(candidates) != 1:
            raise _UnknownOperator(" ".join(phrase))
        return phrase, candidates[0]

    def parse(self) -> MathNode:
        if len(self.values) > 128:
            raise ValueError("math expressions are limited to 128 tokens")
        result = self._expression(0)
        if (self.index != len(self.values)
                or (self.require_operator and self.operator_count == 0)):
            raise ValueError("expression does not match the learned arithmetic grammar")
        return result


class CRMSMath:
    """Learn exact binary operations and compose their phrases in expressions."""

    VERSION = 3

    def __init__(self) -> None:
        self._examples: dict[tuple[str, ...], dict[tuple[int, int], Fraction]] = {}
        self._unit_examples: dict[
            tuple[tuple[str, ...], tuple[str, ...]], dict[tuple[int, int], str]
        ] = {}

    @staticmethod
    def _unit_name(value: str) -> tuple[str, ...]:
        name = tuple(tokens(value))
        if not name or len(name) > 8 or any(not token.isalpha() for token in name):
            raise ValueError("unit names must contain 1 to 8 alphabetic words")
        normalized = list(name)
        last = normalized[-1]
        if len(last) > 4 and last.endswith("ies"):
            normalized[-1] = last[:-3] + "y"
        elif len(last) > 4 and last.endswith(("sses", "shes", "ches", "xes", "zes")):
            normalized[-1] = last[:-2]
        elif len(last) > 3 and last.endswith("s") and not last.endswith("ss"):
            normalized[-1] = last[:-1]
        return tuple(normalized)

    @staticmethod
    def _unit_edges(records: Mapping[
            tuple[tuple[str, ...], tuple[str, ...]], Mapping[tuple[int, int], str]
            ]) -> dict[tuple[str, ...], dict[tuple[str, ...], Fraction]]:
        """Build only independently grounded, ratio-consistent conversion edges."""
        graph: dict[tuple[str, ...], dict[tuple[str, ...], Fraction]] = {}
        for (left, right), rows in records.items():
            if len(rows) < 2:
                continue
            ratios = {Fraction(rv, lv) for lv, rv in rows if lv > 0 and rv > 0}
            if len(ratios) != 1 or len(rows) < 2:
                continue
            ratio = next(iter(ratios))
            graph.setdefault(left, {})[right] = ratio
            graph.setdefault(right, {})[left] = 1 / ratio
        # Refuse every edge participating in an inconsistent cycle.
        valid = {key: dict(edges) for key, edges in graph.items()}
        for start in tuple(graph):
            scales = {start: Fraction(1)}
            stack = [start]
            inconsistent: set[tuple[str, ...]] = set()
            while stack:
                node = stack.pop()
                for neighbor, factor in graph[node].items():
                    candidate = scales[node] * factor
                    if neighbor in scales:
                        if scales[neighbor] != candidate:
                            inconsistent.update(scales)
                            inconsistent.add(neighbor)
                    else:
                        scales[neighbor] = candidate
                        stack.append(neighbor)
            if inconsistent:
                for node in inconsistent:
                    valid.pop(node, None)
                for edges in valid.values():
                    for node in inconsistent:
                        edges.pop(node, None)
        return valid

    def _matching_unit(self, values: list[str], start: int
                       ) -> tuple[tuple[str, ...], int] | None:
        names = {name for pair in self._unit_examples for name in pair}
        matches = []
        for name in names:
            width = len(name)
            if start + width > len(values):
                continue
            try:
                observed = self._unit_name(" ".join(values[start:start + width]))
            except ValueError:
                continue
            if observed == name:
                matches.append((name, width))
        return max(matches, key=lambda match: match[1]) if matches else None

    def _unit_info(self, unit: tuple[str, ...]
                   ) -> tuple[tuple[str, ...], Fraction, tuple[str, ...]] | None:
        """Return component identity, scale to its canonical unit, and lineage."""
        graph = self._unit_edges(self._unit_examples)
        if unit not in graph:
            return None
        scales = {unit: Fraction(1)}
        sources: list[str] = []
        queue = [unit]
        while queue:
            node = queue.pop(0)
            for neighbor, factor in graph[node].items():
                if neighbor in scales:
                    continue
                scales[neighbor] = scales[node] * factor
                queue.append(neighbor)
                pair = tuple(sorted((node, neighbor)))
                sources.extend(self._unit_examples[pair].values())
        anchor = min(scales)
        if anchor not in scales:
            return None
        return anchor, scales[anchor], tuple(dict.fromkeys(sources))

    def _expression_unit(self, node: MathNode
                         ) -> tuple[tuple[str, ...] | None,
                                    tuple[str, ...] | None]:
        """Check unit algebra and retain the leftmost display unit."""
        if isinstance(node, MathLiteral):
            return node.unit_dimension, node.unit
        if isinstance(node, MathVariable):
            return None, None
        left_dimension, left_unit = self._expression_unit(node.left)
        right_dimension, right_unit = self._expression_unit(node.right)
        if node.operation in {"add", "subtract"}:
            if left_dimension != right_dimension:
                raise _UnsupportedMath(
                    "addition and subtraction require quantities with matching learned units")
            return left_dimension, left_unit or right_unit
        if node.operation == "multiply":
            if left_dimension is not None and right_dimension is not None:
                raise _UnsupportedMath(
                    "multiplication of two unitful quantities is not supported")
            return ((left_dimension, left_unit) if left_dimension is not None
                    else (right_dimension, right_unit))
        if node.operation == "divide":
            if right_dimension is not None:
                raise _UnsupportedMath(
                    "division by a unitful quantity is not supported")
            return left_dimension, left_unit
        if node.operation == "modulo":
            if left_dimension != right_dimension:
                raise _UnsupportedMath(
                    "remainder requires quantities with matching learned units")
            return left_dimension, left_unit or right_unit
        raise ValueError("unknown operation")

    def teach_unit_equivalence(self, example: str) -> MathResult:
        """Learn a unit ratio from quantity pairs; require two varied examples."""
        if not isinstance(example, str) or example.count("|") != 1:
            raise ValueError("use LEFT_QUANTITY|RIGHT_QUANTITY")
        sides = []
        for text in example.split("|"):
            match = _UNIT_TEACH_RE.fullmatch(text)
            if match is None:
                raise ValueError("each side must be a positive integer and unit phrase")
            amount = int(match.group(1))
            if amount.bit_length() > _MAX_RESULT_BITS:
                raise ValueError("quantity exceeds the exact arithmetic bound")
            sides.append((amount, self._unit_name(match.group(2))))
        (left_amount, left_unit), (right_amount, right_unit) = sides
        if left_unit == right_unit:
            raise ValueError("equivalence examples must name two different units")
        pair = tuple(sorted((left_unit, right_unit)))
        # Normalize all rows to the sorted phrase order.
        row = ((left_amount, right_amount) if pair == (left_unit, right_unit)
               else (right_amount, left_amount))
        prior = dict(self._unit_examples.get(pair, {}))
        old = prior.get(row)
        if old is not None and old != example:
            raise ValueError("that quantity pair already has conflicting evidence")
        prior[row] = example
        if len(prior) >= 2:
            ratios = {Fraction(b, a) for a, b in prior}
            if len(ratios) != 1:
                raise ValueError("example conflicts with the learned unit ratio")
        candidate = dict(self._unit_examples)
        candidate[pair] = prior
        graph = self._unit_edges(candidate)
        # Check whether this candidate creates an inconsistent cycle.
        if (len(prior) >= 2 and
                (pair[0] not in graph or pair[1] not in graph.get(pair[0], {}))):
            raise ValueError("unit example conflicts with an existing conversion cycle")
        self._unit_examples = candidate
        return MathResult(
            "licensed" if len(prior) >= 2 else "needs_more_examples",
            unit=" ".join(pair[0]) + " = " + _format(next(iter(
                {Fraction(b, a) for a, b in prior}))) + " " + " ".join(pair[1])
                 if len(prior) >= 2 else None,
            unit_evidence=tuple({"example": text} for _, text in sorted(prior.items())),
            request=(None if len(prior) >= 2 else
                     "Provide a second distinct quantity pair to license this conversion."))

    def convert_unit(self, question: str, *, grounded_cardinals: Mapping[
            tuple[str, ...], tuple[int, tuple[str, ...]]] | None = None
            ) -> MathResult | None:
        """Convert a numeric quantity, leaving ambiguous definition frames alone."""
        match = None
        matched_pattern_index = None
        if isinstance(question, str):
            for pattern_index, pattern in enumerate(_UNIT_CONVERT_PATTERNS):
                match = pattern.fullmatch(question)
                if match is not None:
                    matched_pattern_index = pattern_index
                    break
        if match is None:
            return None
        quantity_text = match.group(1).strip()
        target_text = match.group(2).strip()
        numeral_evidence: tuple[dict[str, object], ...] = ()
        numeric_match = re.fullmatch(r"([+-]?\d{1,100})\s+(.+)", quantity_text)
        if matched_pattern_index == 0 and numeric_match is None:
            quantity_tokens = tuple(tokens(quantity_text))
            grounded = grounded_cardinals or {}
            has_grounded_prefix = any(
                quantity_tokens[:len(phrase)] == phrase
                and len(quantity_tokens) > len(phrase)
                for phrase in grounded)
            has_number_cue = bool(
                quantity_tokens
                and (quantity_tokens[0] in _NUMBER_CUE_WORDS
                     or (len(quantity_tokens) > 1
                         and quantity_tokens[0] in {"a", "an"}
                         and quantity_tokens[1] in {"dozen", "couple", "score"})))
            if not has_grounded_prefix and not has_number_cue:
                # "What is X in Y?" is also an ordinary definition frame
                # ("What is causal forgetting in CRMS?"). Only claim this
                # ambiguous syntax for unit conversion when X looks numeric.
                return None
        if numeric_match:
            amount = int(numeric_match.group(1))
            source_text = numeric_match.group(2)
        else:
            grounded = grounded_cardinals or {}
            quantity_tokens = tuple(tokens(quantity_text))
            candidates = [phrase for phrase in grounded
                          if quantity_tokens[:len(phrase)] == phrase
                          and len(quantity_tokens) > len(phrase)]
            if not candidates:
                return MathResult("unknown", request=(
                    f"I have no grounded cardinal value in '{quantity_text}'. "
                    "Ground this number phrase in CRMS examples first."))
            phrase = max(candidates, key=len)
            grounded_value = grounded[phrase]
            amount, sources = grounded_value
            if (type(amount) is not int or amount <= 0
                    or amount.bit_length() > _MAX_RESULT_BITS
                    or not isinstance(sources, (tuple, list))
                    or not all(isinstance(source, str) for source in sources)):
                return MathResult("unknown", request=(
                    "The grounded cardinal evidence is malformed or outside "
                    "the positive quantity bound."))
            source_text = " ".join(quantity_tokens[len(phrase):])
            numeral_evidence = ({"phrase": " ".join(phrase), "value": amount,
                                 "sources": list(sources)},)
        try:
            source, target = self._unit_name(source_text), self._unit_name(target_text)
        except ValueError as error:
            return MathResult("unknown", request=str(error))
        target_label = " ".join(tokens(target_text))
        graph = self._unit_edges(self._unit_examples)
        scales = {source: Fraction(1)}
        evidence: list[str] = []
        stack = [source]
        while stack:
            current = stack.pop()
            if current == target:
                break
            for neighbor, factor in graph.get(current, {}).items():
                if neighbor in scales:
                    continue
                scales[neighbor] = scales[current] * factor
                stack.append(neighbor)
                pair = tuple(sorted((current, neighbor)))
                evidence.extend(self._unit_examples[pair].values())
        if target not in scales:
            return MathResult("unknown", request=(
                f"No verified conversion connects '{' '.join(source)}' and "
                f"'{ ' '.join(target)}'. Teach two aligned quantity examples."))
        result = Fraction(amount) * scales[target]
        if max(abs(result.numerator).bit_length(), result.denominator.bit_length()) > _MAX_RESULT_BITS:
            return MathResult("unknown", request="The exact conversion exceeds the arithmetic size bound.")
        return MathResult("answered", value=result, unit=target_label,
                          number_evidence=numeral_evidence,
                          unit_evidence=tuple({"example": item} for item in dict.fromkeys(evidence)))

    @staticmethod
    def parse_question(question: str) -> MathExpression | None:
        """Parse one exact binary math question in a supported wording frame."""
        if not isinstance(question, str):
            return None
        body = CRMSMath._question_body(question)
        match = _BINARY_EXPRESSION_RE.fullmatch(body) if body is not None else None
        if not match:
            return None
        phrase = tuple(tokens(match.group(2)))
        if not phrase or not all(token.isalpha() for token in phrase):
            return None
        return MathExpression(int(match.group(1)), phrase, int(match.group(3)))

    @staticmethod
    def _tokenize_body(body: str) -> list[str] | None:
        values: list[str] = []
        cursor = 0
        for item in _EXPRESSION_TOKEN_RE.finditer(body):
            gap = body[cursor:item.start()]
            if gap.strip(" \t\r\n.,;:!?"):
                return None
            token = item.group(0)
            values.append(token if token in {"(", ")", "+", "-", "−",
                                             "*", "×", "/", "÷", "%", "="}
                          or _NUMBER_LITERAL_RE.fullmatch(token)
                          else tuple(tokens(token))[0])
            cursor = item.end()
        if body[cursor:].strip(" \t\r\n.,;:!?"):
            return None
        return values or None

    @classmethod
    def _expression_tokens(cls, question: str) -> list[str] | None:
        body = cls._question_body(question)
        return cls._tokenize_body(body) if body is not None else None

    @staticmethod
    def _question_body(question: str) -> str | None:
        for pattern in _QUESTION_BODY_PATTERNS:
            match = pattern.fullmatch(question)
            if match is not None:
                return match.group(1)
        return None

    @staticmethod
    def _candidates(examples: dict[tuple[int, int], Fraction]) -> tuple[str, ...]:
        candidates = []
        for operation in _OPERATIONS:
            valid = True
            for (left, right), expected in examples.items():
                try:
                    actual = _evaluate(operation, left, right)
                except ZeroDivisionError:
                    valid = False
                    break
                if actual != expected:
                    valid = False
                    break
            if valid:
                candidates.append(operation)
        return tuple(candidates)

    @staticmethod
    def _contrastive_pair(
        candidates: tuple[str, ...], seen: set[tuple[int, int]],
    ) -> tuple[int, int] | None:
        """Find a small operand pair that separates remaining operations."""
        pairs = sorted(
            ((left, right) for left in range(-8, 9) for right in range(-8, 9)
             if (left, right) not in seen
             and not (right == 0
                      and {"divide", "modulo"}.intersection(candidates))),
            key=lambda pair: (abs(pair[0]) + abs(pair[1]), pair[0], pair[1]))
        for left, right in pairs:
            try:
                outputs = {_evaluate(operation, left, right)
                           for operation in candidates}
            except ZeroDivisionError:
                continue
            if len(outputs) > 1:
                return left, right
        return None

    def teach(self, question: str, answer: str) -> MathResult:
        """Align a natural-language expression with an exact numeric answer.

        Candidate operations are intersected across examples. A contradictory
        example is rejected atomically. Execution is licensed only after at
        least two distinct operand pairs leave exactly one operation.
        """
        expression = self.parse_question(question)
        if expression is None:
            raise ValueError("example must use 'What is INTEGER PHRASE INTEGER?'")
        expected = _fraction(answer)
        phrase = expression.operator_phrase
        if phrase in {("solve",), ("equals",), ("for",)}:
            raise ValueError("operator phrase is reserved by the math question grammar")
        pair = (expression.left, expression.right)
        prior = dict(self._examples.get(phrase, {}))
        existing = prior.get(pair)
        if existing is not None and existing != expected:
            raise ValueError("the same math example already has a different answer")
        prior[pair] = expected
        candidates = self._candidates(prior)
        if not candidates:
            raise ValueError("example conflicts with every supported exact operation")
        self._examples[phrase] = prior
        operation = candidates[0] if len(candidates) == 1 else None
        licensed = operation is not None and len(prior) >= 2
        probe = None if licensed else self._contrastive_pair(candidates, set(prior))
        request = None
        if not licensed:
            if probe is None:
                request = ("Provide another operand pair where the remaining exact "
                           "operations predict different answers.")
            else:
                probe_outputs = ", ".join(
                    f"{candidate}={_format(_evaluate(candidate, *probe))}"
                    for candidate in candidates)
                request = (
                    f"The examples still fit {', '.join(candidates)}. "
                    f"For '{probe[0]} {' '.join(phrase)} {probe[1]}', "
                    f"they predict {probe_outputs}. What answer does the phrase mean?")
        return MathResult(
            "licensed" if licensed else "needs_more_examples",
            expression=expression, value=expected, operation=operation,
            request=request,
            examples=tuple({"left": str(left), "right": str(right),
                            "answer": _format(value)}
                           for (left, right), value in sorted(prior.items())),
            candidate_operations=candidates, contrastive_input=probe)

    def _solve_equation(self, question: str, *, grounded_cardinals: Mapping[
            tuple[str, ...], tuple[int, tuple[str, ...]]] | None = None
            ) -> MathResult:
        match = _SOLVE_EQUATION_RE.fullmatch(question)
        if match is None:
            return MathResult("unknown", request=(
                "Use 'Solve EXPRESSION equals EXPRESSION for x.' with one-letter x."))
        left_values = self._tokenize_body(match.group(1))
        right_values = self._tokenize_body(match.group(2))
        if left_values is None or right_values is None:
            return MathResult("unknown", request="The equation does not fit CRMS's expression grammar.")
        number_words = grounded_cardinals or {}
        left_parser = _ExpressionParser(
            self, left_values, number_words, require_operator=False)
        right_parser = _ExpressionParser(
            self, right_values, number_words, require_operator=False)
        try:
            left_node, right_node = left_parser.parse(), right_parser.parse()
            if (self._expression_unit(left_node)[0]
                    != self._expression_unit(right_node)[0]):
                return MathResult("unknown", request=(
                    "Both sides of an equation must have matching learned units."))
            left_poly, right_poly = (_evaluate_node(left_node),
                                     _evaluate_node(right_node))
        except _UnknownOperator as error:
            return MathResult(
                "unknown", request=f"I have no verified math meaning for '{error}'.")
        except _UnknownNumber as error:
            return MathResult(
                "unknown", request=f"I have no grounded cardinal value for '{error}'.")
        except ZeroDivisionError:
            return MathResult("unknown", request=(
                "Division and remainder by zero are undefined."))
        except OverflowError:
            return MathResult("unknown", request=(
                "The equation exceeds CRMS's exact arithmetic or term-count bound."))
        except _UnsupportedMath as error:
            return MathResult("unknown", request=str(error))
        except ValueError:
            return MathResult("unknown", request="The equation does not fit CRMS's expression grammar.")

        difference = dict(left_poly)
        for monomial, coefficient in right_poly.items():
            difference[monomial] = (difference.get(monomial, Fraction(0))
                                    - coefficient)
        try:
            difference = _bounded_polynomial(difference)
        except OverflowError:
            return MathResult("unknown", request=(
                "The equation exceeds CRMS's exact arithmetic or term-count bound."))
        variable_tokens = tuple(tokens(match.group(3)))
        if len(variable_tokens) != 1 or len(variable_tokens[0]) != 1:
            return MathResult("unknown", request="Use one single-letter variable.")
        variable = variable_tokens[0]
        for monomial in difference:
            if any(name != variable for name, _power in monomial):
                return MathResult("unknown", request=(
                    "CRMS currently solves only univariate equations."))
            if sum(power for _name, power in monomial) > 2:
                return MathResult(
                    "unknown", request=(f"The equation exceeds quadratic degree "
                                       f"in '{variable}'."))
        constant = difference.get((), Fraction(0))
        linear = difference.get(((variable, 1),), Fraction(0))
        quadratic = difference.get(((variable, 2),), Fraction(0))
        solutions: tuple[Fraction, ...]
        if quadratic:
            discriminant = linear * linear - 4 * quadratic * constant
            if discriminant < 0:
                return MathResult(
                    "unknown", request=("The quadratic has no real solutions; "
                                        "complex roots are outside the current grammar."))
            numerator_root = isqrt(discriminant.numerator)
            denominator_root = isqrt(discriminant.denominator)
            if (numerator_root * numerator_root != discriminant.numerator
                    or denominator_root * denominator_root != discriminant.denominator):
                return MathResult(
                    "unknown", request=("The quadratic roots are irrational; "
                                        "CRMS currently returns exact rational roots only."))
            square_root = Fraction(numerator_root, denominator_root)
            denominator = 2 * quadratic
            solutions = tuple(sorted({
                (-linear - square_root) / denominator,
                (-linear + square_root) / denominator,
            }))
        else:
            if linear == 0:
                reason = ("The equation does not determine a unique solution for "
                          "the requested variable." if constant == 0 else
                          "The equation has no solution for the requested variable.")
                return MathResult("unknown", request=reason)
            solutions = (-constant / linear,)
        for solution in solutions:
            if max(abs(solution.numerator).bit_length(),
                   solution.denominator.bit_length()) > _MAX_RESULT_BITS:
                return MathResult(
                    "unknown", request="The exact solution exceeds the arithmetic size bound.")
            # Substitute every candidate back into the independently reduced
            # polynomial before returning any roots.
            if (quadratic * solution * solution + linear * solution
                    + constant != 0):
                return MathResult(
                    "unknown", request="An exact solution failed substitution verification.")
            try:
                left_value = _substitute_node(
                    left_node, {variable: solution})
                right_value = _substitute_node(
                    right_node, {variable: solution})
            except (KeyError, ZeroDivisionError, ValueError):
                return MathResult(
                    "unknown", request="An exact solution could not be checked against the original equation.")
            if left_value != right_value:
                return MathResult(
                    "unknown", request="An exact solution failed substitution in the original equation.")
        solution_value = solutions[0] if len(solutions) == 1 else None

        used: dict[tuple[str, ...], str] = {}
        def collect(node: MathNode) -> None:
            if not isinstance(node, MathBinary):
                return
            used[node.operator_phrase] = node.operation
            collect(node.left)
            collect(node.right)
        collect(left_node)
        collect(right_node)
        examples = tuple(
            {"phrase": " ".join(phrase), "left": str(a), "right": str(b),
             "answer": _format(expected)}
            for phrase in sorted(used)
            if phrase in self._examples
            for (a, b), expected in sorted(self._examples[phrase].items()))
        evidence = dict(left_parser.number_evidence)
        evidence.update(right_parser.number_evidence)
        return MathResult(
            "answered", expression=MathEquation(left_node, right_node, variable),
            value=solution_value, operation="solve", examples=examples,
            number_evidence=tuple(
                {"phrase": " ".join(phrase), "value": number,
                 "sources": list(sources)}
                for phrase, (number, sources) in sorted(evidence.items())),
            symbolic_terms=tuple(
                {"powers": [[name, power] for name, power in monomial],
                 "coefficient": _format(coefficient)}
                for monomial, coefficient in sorted(difference.items())),
            solutions=solutions)

    def ask(self, question: str, *, grounded_cardinals: Mapping[
            tuple[str, ...], tuple[int, tuple[str, ...]]] | None = None
            ) -> MathResult | None:
        """Evaluate a recognized question or return None outside the grammar."""
        if not isinstance(question, str):
            return None
        conversion = self.convert_unit(
            question, grounded_cardinals=grounded_cardinals)
        if conversion is not None:
            return conversion
        if re.match(r"\s*solve\b", question, flags=re.IGNORECASE):
            return self._solve_equation(
                question, grounded_cardinals=grounded_cardinals)
        values = self._expression_tokens(question)
        if values is None:
            return None
        has_known_operator = any(value in _SYMBOL_OPERATIONS for value in values) or any(
            values[index:index + len(phrase)] == list(phrase)
            for index in range(len(values)) for phrase in self._examples)
        if not has_known_operator:
            unlearned = self.parse_question(question)
            if unlearned is not None:
                phrase = " ".join(unlearned.operator_phrase)
                return MathResult(
                    "unknown", expression=unlearned,
                    request=(f"I have no verified math meaning for '{phrase}'. "
                             "Teach 2 to 8 aligned examples with 'Teach math from "
                             "examples: \"What is 2 PHRASE 3?\" -> ANSWER; "
                             "\"What is 5 PHRASE 3?\" -> ANSWER.'"))
            return None
        number_words = grounded_cardinals or {}
        parser = _ExpressionParser(self, values, number_words)
        try:
            expression = parser.parse()
        except _UnknownOperator as error:
            phrase = str(error)
            if phrase in {" ".join(key) for key in self._examples}:
                request = (f"The operation phrase '{phrase}' is ambiguous or "
                           "not yet learned from enough examples.")
            else:
                request = (f"I have no verified math meaning for '{phrase}'. "
                           "Teach it with /teach-math QUESTION|ANSWER.")
            return MathResult(
                "unknown", request=request)
        except _UnknownNumber as error:
            phrase = str(error)
            return MathResult(
                "unknown", request=(f"I have no grounded cardinal value for "
                                    f"'{phrase}'. Teach number phrases through "
                                    "grounded CRMS examples first."))
        except ValueError:
            return None
        try:
            _, output_unit = self._expression_unit(expression)
            polynomial = _evaluate_node(expression)
            if output_unit is not None:
                normalized_output = self._unit_name(" ".join(output_unit))
                output_info = self._unit_info(normalized_output)
                if output_info is None:
                    return MathResult("unknown", request=(
                        "The output unit lost its verified conversion path."))
                polynomial = {monomial: coefficient / output_info[1]
                              for monomial, coefficient in polynomial.items()}
            value = _polynomial_value(polynomial)
        except ZeroDivisionError:
            return MathResult(
                "unknown",
                request="Division and remainder by zero are undefined.")
        except OverflowError:
            return MathResult(
                "unknown",
                request="The expression exceeds CRMS's exact arithmetic or term-count bound.")
        except _UnsupportedMath as error:
            return MathResult("unknown", request=str(error))
        unit_sources: list[str] = []
        def collect_unit_sources(node: MathNode) -> None:
            if isinstance(node, MathLiteral):
                unit_sources.extend(node.unit_sources)
            elif isinstance(node, MathBinary):
                collect_unit_sources(node.left)
                collect_unit_sources(node.right)
        collect_unit_sources(expression)
        used: dict[tuple[str, ...], str] = {}
        def collect(node: MathNode) -> None:
            if not isinstance(node, MathBinary):
                return
            used[node.operator_phrase] = node.operation
            collect(node.left)
            collect(node.right)
        collect(expression)
        example_rows = tuple(
            {"phrase": " ".join(phrase), "left": str(left), "right": str(right),
             "answer": _format(expected)}
            for phrase in sorted(used)
            if phrase in self._examples
            for (left, right), expected in sorted(self._examples[phrase].items()))
        operations = tuple(sorted(set(used.values())))
        operation = operations[0] if len(operations) == 1 else "composed"
        return MathResult("answered", expression=expression, value=value,
                          operation=operation, examples=example_rows,
                          unit=(" ".join(output_unit)
                                if output_unit is not None else None),
                          unit_evidence=tuple(
                              {"example": item}
                              for item in dict.fromkeys(unit_sources)),
                          symbolic_terms=tuple(
                              {"powers": [[name, power] for name, power in monomial],
                               "coefficient": _format(coefficient)}
                              for monomial, coefficient in sorted(polynomial.items())),
                          number_evidence=tuple(
                              {"phrase": " ".join(phrase), "value": number,
                               "sources": list(sources)}
                              for phrase, (number, sources) in
                              sorted(parser.number_evidence.items())))

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.VERSION,
            "examples": [
                {"phrase": list(phrase), "rows": [
                    {"left": left, "right": right, "answer": _format(answer)}
                    for (left, right), answer in sorted(rows.items())]}
                for phrase, rows in sorted(self._examples.items())
            ],
            "unit_examples": [
                {"left_unit": list(pair[0]), "right_unit": list(pair[1]),
                 "rows": [{"left": left, "right": right, "example": example}
                          for (left, right), example in sorted(rows.items())]}
                for pair, rows in sorted(self._unit_examples.items())
            ],
        }
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        temporary.replace(destination)

    @classmethod
    def load(cls, path: str | Path) -> "CRMSMath":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if (not isinstance(payload, dict)
                or payload.get("version") not in {1, 2, cls.VERSION}):
            raise ValueError("unsupported math-memory format")
        records = payload.get("examples")
        if not isinstance(records, list):
            raise ValueError("math examples must be a list")
        model = cls()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("math phrase record is malformed")
            phrase_value, rows_value = record.get("phrase"), record.get("rows")
            if (not isinstance(phrase_value, list)
                    or not all(isinstance(token, str) for token in phrase_value)
                    or not phrase_value or tuple(tokens(" ".join(phrase_value))) != tuple(phrase_value)
                    or not isinstance(rows_value, list)):
                raise ValueError("math phrase or rows are malformed")
            phrase = tuple(phrase_value)
            if phrase in model._examples:
                raise ValueError("duplicate math phrase record")
            rows: dict[tuple[int, int], Fraction] = {}
            for row in rows_value:
                if not isinstance(row, dict):
                    raise ValueError("math example row is malformed")
                left, right, answer = row.get("left"), row.get("right"), row.get("answer")
                if (type(left) is not int or type(right) is not int
                        or not isinstance(answer, str)):
                    raise ValueError("math example fields are malformed")
                pair = (left, right)
                if pair in rows:
                    raise ValueError("duplicate math operand pair")
                rows[pair] = _fraction(answer)
            if not rows or not cls._candidates(rows):
                raise ValueError("math examples do not fit a supported operation")
            model._examples[phrase] = rows
        unit_records = payload.get("unit_examples", [])
        if not isinstance(unit_records, list):
            raise ValueError("unit examples must be a list")
        for record in unit_records:
            if not isinstance(record, dict):
                raise ValueError("unit equivalence record is malformed")
            left_raw, right_raw, rows_raw = (record.get("left_unit"),
                                              record.get("right_unit"),
                                              record.get("rows"))
            if not (isinstance(left_raw, list) and isinstance(right_raw, list)
                    and all(isinstance(x, str) for x in left_raw + right_raw)
                    and isinstance(rows_raw, list)):
                raise ValueError("unit equivalence fields are malformed")
            left, right = tuple(left_raw), tuple(right_raw)
            if (not left or not right or left >= right
                    or tuple(tokens(" ".join(left))) != left
                    or tuple(tokens(" ".join(right))) != right):
                raise ValueError("unit names are malformed")
            pair = (left, right)
            if pair in model._unit_examples:
                raise ValueError("duplicate unit equivalence record")
            rows: dict[tuple[int, int], str] = {}
            for row in rows_raw:
                if (not isinstance(row, dict) or type(row.get("left")) is not int
                        or type(row.get("right")) is not int
                        or not isinstance(row.get("example"), str)):
                    raise ValueError("unit quantity example is malformed")
                key = (row["left"], row["right"])
                if key in rows or min(key) <= 0:
                    raise ValueError("unit quantity example is duplicated or nonpositive")
                if row["left"].bit_length() > _MAX_RESULT_BITS or row["right"].bit_length() > _MAX_RESULT_BITS:
                    raise ValueError("unit quantity example exceeds the arithmetic bound")
                sides = row["example"].split("|")
                if len(sides) != 2:
                    raise ValueError("unit evidence must contain two aligned quantities")
                parsed = []
                for side in sides:
                    match = _UNIT_TEACH_RE.fullmatch(side)
                    if match is None:
                        raise ValueError("unit evidence has a malformed quantity")
                    parsed.append((int(match.group(1)), cls._unit_name(match.group(2))))
                (amount_a, unit_a), (amount_b, unit_b) = parsed
                expected_key = ((amount_a, amount_b) if (unit_a, unit_b) == pair
                                else (amount_b, amount_a))
                if {unit_a, unit_b} != {left, right} or expected_key != key:
                    raise ValueError("unit evidence does not match its stored quantity pair")
                rows[key] = row["example"]
            if not rows or (len(rows) >= 2 and len({Fraction(b, a) for a, b in rows}) != 1):
                raise ValueError("unit examples do not fit one exact ratio")
            model._unit_examples[pair] = rows
        if model._unit_examples:
            graph = cls._unit_edges(model._unit_examples)
            if any(a not in graph or b not in graph.get(a, {})
                   for a, b in model._unit_examples
                   if len(model._unit_examples[(a, b)]) >= 2):
                raise ValueError("unit examples contain an inconsistent conversion cycle")
        return model


def render(result: MathResult) -> str:
    """Render a concise answer while exposing the learned operation evidence."""
    if result.status == "answered" and result.expression is None and result.unit:
        amount = _format(result.value) if isinstance(result.value, Fraction) else str(result.value)
        examples = "; ".join(str(row["example"]) for row in result.unit_evidence)
        numeral_note = ""
        if result.number_evidence:
            numeral_note = "; grounded numeral: " + "; ".join(
                f"'{item['phrase']}'={item['value']} from "
                + ", ".join(str(source) for source in item["sources"])
                for item in result.number_evidence)
        return (f"{amount} {result.unit} (exact conversion; grounded by "
                f"{examples}{numeral_note})")
    if (result.status != "answered" or result.expression is None
            or (result.value is None
                and not (isinstance(result.expression, MathEquation)
                         and result.solutions))):
        return result.request or "I cannot answer that math question from the learned examples."
    value_text = _format(result.value) if isinstance(result.value, Fraction) else result.value
    numeral_note = ""
    if result.number_evidence:
        alignments = "; ".join(
            f"'{item['phrase']}'={item['value']} from "
            + ", ".join(str(source) for source in item["sources"])
            for item in result.number_evidence)
        numeral_note = f"; grounded numerals: {alignments}"
    if isinstance(result.expression, MathExpression):
        phrase = " ".join(result.expression.operator_phrase)
        return (f"{value_text} (learned '{phrase}' as exact "
                f"{result.operation}; checked against {len(result.examples)} examples"
                f"{numeral_note})")
    if isinstance(result.expression, MathEquation):
        solutions = result.solutions or (
            (result.value,) if isinstance(result.value, Fraction) else ())
        if len(solutions) > 1:
            answer = (f"{result.expression.variable} ∈ "
                      "{" + ", ".join(_format(value) for value in solutions) + "}")
        else:
            answer = (f"{result.expression.variable} = "
                      f"{_format(solutions[0]) if solutions else value_text}")
        degree = max((sum(power for _name, power in item["powers"])
                      for item in result.symbolic_terms), default=1)
        kind = "quadratic" if degree == 2 else "linear"
        noun = "solutions" if len(solutions) > 1 else "solution"
        return (f"{answer} "
                f"(exact {kind} {noun}; substitution verified; "
                f"learned operation evidence: {len(result.examples)} examples"
                f"{numeral_note})")
    used: dict[tuple[str, ...], str] = {}

    def collect(node: MathNode) -> None:
        if not isinstance(node, MathBinary):
            return
        used[node.operator_phrase] = node.operation
        collect(node.left)
        collect(node.right)

    collect(result.expression)
    if len(used) == 1:
        phrase, operation = next(iter(used.items()))
        if phrase == ("implicit",):
            return (f"{value_text} (exact implicit multiplication"
                    f"{numeral_note})" + _unit_evidence_note(result))
        if phrase in {(symbol,) for symbol in _SYMBOL_OPERATIONS}:
            return (f"{value_text} (exact arithmetic using '{' '.join(phrase)}' "
                    f"for {operation}{numeral_note})"
                    + (f" {result.unit}" if result.unit else "")
                    + _unit_evidence_note(result))
        return (f"{value_text} (learned '{' '.join(phrase)}' as exact "
                f"{operation}; checked against {len(result.examples)} examples"
                f"{numeral_note})" + (f" {result.unit}" if result.unit else "")
                + _unit_evidence_note(result))
    mappings = ", ".join(
        ("implicit multiplication"
         if phrase == ("implicit",) else
         f"symbol '{' '.join(phrase)}' for {operation}"
         if phrase in {(symbol,) for symbol in _SYMBOL_OPERATIONS}
         else "'" + " ".join(phrase) + f"' as learned exact {operation}")
        for phrase, operation in sorted(used.items()))
    return (f"{value_text} (composed operations: {mappings}; "
            f"multiplication/division before addition/subtraction unless grouped; "
            f"checked against {len(result.examples)} examples{numeral_note})"
            + (f" {result.unit}" if result.unit else "")
            + _unit_evidence_note(result))


def _unit_evidence_note(result: MathResult) -> str:
    if not result.unit_evidence:
        return ""
    examples = "; ".join(str(item["example"]) for item in result.unit_evidence)
    return f" (unit evidence: {examples})"
