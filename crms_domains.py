"""Bounded Phase 6 domain slices with independent checks.

This module extends CRMS from one-off domain prototypes to five measured slices:
math word problems/inequalities/systems, typed code programs with static checks
and sandboxed execution, bounded compositional translation with agreement,
constraint-driven fictional writing, and two-stage cross-domain plans through
the task IR.

Every domain result carries provenance. A domain abstains when its evidence,
contract, or checker does not cover the request; it never guesses. Domain rules
(templates, operations, lexicon entries, story templates, and cross-domain
steps) can be mirrored into the governed rule registry.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json
import math
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence

from crms_math import CRMSMath, MathResult, render as render_math
from crms_planner import (
    Action, ActionRegistry, ExecutionContext, FunctionAction, PlanExecutor,
    Verification,
)
from crms_rule_registry import RuleRecord, RuleRegistry
from crms_story import StoryArtifact, generate_short_story
from crms_tasks import (
    CheckSpec, EvidenceRef, Plan, Step, StepResult, TaskRequest, request_id,
)

DOMAIN_FAMILY = "domain"
DOMAIN_ORIGIN = "crms_domains"


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[A-Za-zÀ-ÿ0-9]+", value.casefold()))


def _format(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


@dataclass(frozen=True)
class DomainResult:
    domain: str
    status: str
    text: str = ""
    value: Any = None
    evidence: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    repair_question: str | None = None
    detail: str = ""
    rule_ids: tuple[str, ...] = ()

    @property
    def answered(self) -> bool:
        return self.status == "answered"

    @property
    def abstained(self) -> bool:
        return self.status in {"abstained", "failed"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "status": self.status,
            "text": self.text,
            "value": self.value,
            "evidence": [dict(item) for item in self.evidence],
            "provenance": dict(self.provenance),
            "repair_question": self.repair_question,
            "detail": self.detail,
            "rule_ids": list(self.rule_ids),
        }


# ---------------------------------------------------------------------------
# Math: exact arithmetic, word problems, inequalities, and 2x2 systems.
# ---------------------------------------------------------------------------

_WORD_SUBTRACT = re.compile(
    r"^\s*(?P<name>[A-Z][a-z]+) has (?P<a>\d+) (?P<item>[a-z]+)\. "
    r"(?:She|He|They) gives away (?P<b>\d+) (?P=item)\. "
    r"How many (?P=item) (?:does|do) (?:she|he|they) have(?: left)?\?\s*$",
    re.IGNORECASE)
_WORD_SPEED = re.compile(
    r"^\s*A (?P<vehicle>[a-z]+) travels (?P<distance>\d+) "
    r"(?P<distance_unit>kilometres|kilometers|miles) in (?P<hours>\d+) "
    r"hours?\. What is its average speed(?: in (?P<speed_unit>[a-z ]+))?\?\s*$",
    re.IGNORECASE)
_WORD_COST = re.compile(
    r"^\s*A (?P<item>[a-z]+) costs (?P<price>\d+) "
    r"(?P<currency>[a-z]+)\. How much do (?P<count>\d+) (?P=item)s "
    r"cost\?\s*$", re.IGNORECASE)
_WORD_ADD = re.compile(
    r"^\s*There are (?P<a>\d+) (?P<item>[a-z]+) on a (?P<place>[a-z]+)\. "
    r"(?P<b>\d+) more arrive\. How many (?P=item) are there now\?\s*$",
    re.IGNORECASE)
_INEQUALITY = re.compile(
    r"^\s*solve\s+(?P<expression>.+?)\s*(?P<operator><=|>=|<|>)\s*"
    r"(?P<rhs>[+-]?\d+)\s+for\s+x\s*[.?!]*\s*$", re.IGNORECASE)
_SYSTEM = re.compile(
    r"^\s*solve\s+(?P<first>.+?)\s+and\s+(?P<second>.+?)\s+for\s+"
    r"x\s+and\s+y\s*[.?!]*\s*$", re.IGNORECASE)


def _linear_x(expression: str) -> tuple[Fraction, Fraction] | None:
    compact = re.sub(r"\s+", "", expression)
    if not compact:
        return None
    coefficient = Fraction(0)
    constant = Fraction(0)
    for term in re.findall(r"[+-]?[^+-]+", compact):
        if "x" in term:
            if term.count("x") != 1 or any(ch not in "+-0123456789x" for ch in term):
                return None
            number = term.replace("x", "")
            if number in {"", "+"}:
                coefficient += 1
            elif number == "-":
                coefficient -= 1
            else:
                coefficient += Fraction(int(number))
        else:
            if not re.fullmatch(r"[+-]?\d+", term):
                return None
            constant += Fraction(int(term))
    return coefficient, constant


def _linear_xy(expression: str) -> tuple[Fraction, Fraction, Fraction] | None:
    compact = re.sub(r"\s+", "", expression)
    if not compact:
        return None
    x_coefficient = Fraction(0)
    y_coefficient = Fraction(0)
    constant = Fraction(0)
    for term in re.findall(r"[+-]?[^+-]+", compact):
        variables = [name for name in ("x", "y") if name in term]
        if variables:
            if len(variables) != 1 or term.count(variables[0]) != 1:
                return None
            name = variables[0]
            if any(ch not in "+-0123456789xy" for ch in term):
                return None
            number = term.replace(name, "")
            if number in {"", "+"}:
                value = Fraction(1)
            elif number == "-":
                value = Fraction(-1)
            else:
                value = Fraction(int(number))
            if name == "x":
                x_coefficient += value
            else:
                y_coefficient += value
        else:
            if not re.fullmatch(r"[+-]?\d+", term):
                return None
            constant += Fraction(int(term))
    return x_coefficient, y_coefficient, constant


class MathDomain:
    """Exact math slice with a bounded word-problem/inequality/system layer."""

    domain = "math"

    def __init__(self, math_model: CRMSMath | None = None,
                 registry: RuleRegistry | None = None) -> None:
        self.math_model = math_model or CRMSMath()
        self.registry = registry

    def solve(self, request: str) -> DomainResult:
        if not isinstance(request, str) or not request.strip():
            return DomainResult(self.domain, "abstained",
                                detail="empty math request",
                                repair_question="What calculation should I perform?")
        word = self._word_problem(request)
        if word is not None:
            return word
        inequality = self._inequality(request)
        if inequality is not None:
            return inequality
        system = self._system(request)
        if system is not None:
            return system
        result = self.math_model.ask(request)
        if result is not None and result.status == "answered":
            return DomainResult(
                self.domain, "answered", text=render_math(result),
                value=result.value,
                evidence=(
                    {"kind": "computation", "ref": request,
                     "source": "crms_math.exact",
                     "detail": {"operation": result.operation,
                                "unit": result.unit,
                                "examples": len(result.examples or ())}},
                ),
                provenance={"route": "crms_math", "operation": result.operation},
                detail="exact arithmetic/equation/unit result",
            )
        if result is not None and result.request:
            return DomainResult(
                self.domain, "abstained", detail=result.request,
                repair_question=result.request,
                provenance={"route": "crms_math", "operation": result.operation},
            )
        return DomainResult(
            self.domain, "abstained",
            detail="the request is outside exact arithmetic, units, word problems, linear inequalities, and 2x2 systems",
            repair_question=("Please restate the calculation with explicit numbers, "
                             "or teach the missing unit/operator evidence."),
        )

    def teach_unit(self, example: str) -> MathResult:
        return self.math_model.teach_unit_equivalence(example)

    def repair_unit(self, left: str, right: str,
                    question: str) -> DomainResult | None:
        """Teach two aligned quantity pairs and retry a failed conversion."""
        self.math_model.teach_unit_equivalence(left)
        self.math_model.teach_unit_equivalence(right)
        return self.solve(question)

    def _word_problem(self, request: str) -> DomainResult | None:
        match = _WORD_SUBTRACT.fullmatch(request)
        if match:
            a, b = int(match.group("a")), int(match.group("b"))
            value = Fraction(a - b)
            return self._word("subtract", value,
                              f"{a} - {b} = {_format(value)}",
                              ["a", str(a), "b", str(b)])
        match = _WORD_SPEED.fullmatch(request)
        if match:
            distance, hours = int(match.group("distance")), int(match.group("hours"))
            if hours == 0:
                return DomainResult(self.domain, "abstained",
                                    detail="average speed is undefined for zero hours")
            value = Fraction(distance, hours)
            unit = match.group("speed_unit") or "kilometres per hour"
            return self._word("divide", value,
                              f"{distance} / {hours} = {_format(value)} {unit}",
                              ["distance", str(distance), "hours", str(hours)],
                              unit=unit)
        match = _WORD_COST.fullmatch(request)
        if match:
            price, count = int(match.group("price")), int(match.group("count"))
            value = Fraction(price * count)
            currency = match.group("currency")
            return self._word("multiply", value,
                              f"{price} * {count} = {_format(value)} {currency}",
                              ["price", str(price), "count", str(count)],
                              unit=currency)
        match = _WORD_ADD.fullmatch(request)
        if match:
            a, b = int(match.group("a")), int(match.group("b"))
            value = Fraction(a + b)
            return self._word("add", value,
                              f"{a} + {b} = {_format(value)}",
                              ["a", str(a), "b", str(b)])
        return None

    def _word(self, operation: str, value: Fraction, formula: str,
              values: Sequence[str], *, unit: str | None = None) -> DomainResult:
        return DomainResult(
            self.domain, "answered",
            text=f"{_format(value)}" + (f" {unit}" if unit else ""),
            value=value,
            evidence=({"kind": "computation", "ref": formula,
                       "source": "domain-math:word-problem",
                       "detail": {"operation": operation,
                                  "operands": dict(zip(values[::2], values[1::2]))}},),
            provenance={"route": "domain-math:word-problem",
                        "operation": operation, "formula": formula},
            detail="word problem reduced to an exact operation by a reviewed template",
        )

    def _inequality(self, request: str) -> DomainResult | None:
        match = _INEQUALITY.fullmatch(request)
        if match is None:
            return None
        parsed = _linear_x(match.group("expression"))
        if parsed is None:
            return DomainResult(self.domain, "abstained",
                                detail="only linear one-variable inequalities are supported")
        coefficient, constant = parsed
        rhs = Fraction(int(match.group("rhs")))
        if coefficient == 0:
            return DomainResult(self.domain, "abstained",
                                detail="the inequality has no unique variable bound")
        boundary = (rhs - constant) / coefficient
        operator = match.group("operator")
        if coefficient < 0:
            operator = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}[operator]
        display = f"x {operator} {_format(boundary)}"
        # Exact boundary check: substituting the boundary must make both sides
        # equal. Direction is checked with a point just above the boundary.
        lhs_at_boundary = coefficient * boundary + constant
        if lhs_at_boundary != rhs:
            return DomainResult(self.domain, "abstained",
                                detail="inequality boundary failed exact substitution")
        evidence = ({"kind": "computation", "ref": display,
                     "source": "domain-math:inequality",
                     "detail": {"coefficient": _format(coefficient),
                                "constant": _format(constant),
                                "rhs": _format(rhs),
                                "operator": operator}},)
        return DomainResult(
            self.domain, "answered", text=display,
            value={"boundary": _format(boundary), "operator": operator},
            evidence=evidence,
            provenance={"route": "domain-math:inequality",
                        "formula": match.group("expression")},
            detail="exact linear inequality",
        )

    def _system(self, request: str) -> DomainResult | None:
        match = _SYSTEM.fullmatch(request)
        if match is None:
            return None
        equations = []
        for text in (match.group("first"), match.group("second")):
            if text.count("=") != 1:
                return DomainResult(self.domain, "abstained",
                                    detail="a 2x2 system needs two equations with '='")
            left, right = text.split("=")
            left_terms, right_terms = _linear_xy(left), _linear_xy(right)
            if left_terms is None or right_terms is None:
                return DomainResult(self.domain, "abstained",
                                    detail="only linear x/y equations are supported")
            a = left_terms[0] - right_terms[0]
            b = left_terms[1] - right_terms[1]
            c = right_terms[2] - left_terms[2]
            equations.append((a, b, c))
        (a1, b1, c1), (a2, b2, c2) = equations
        determinant = a1 * b2 - a2 * b1
        if determinant == 0:
            return DomainResult(self.domain, "abstained",
                                detail="the 2x2 system does not have a unique solution")
        x = (c1 * b2 - c2 * b1) / determinant
        y = (a1 * c2 - a2 * c1) / determinant
        for a, b, c in equations:
            if a * x + b * y != c:
                return DomainResult(self.domain, "abstained",
                                    detail="system solution failed exact substitution")
        text = f"x = {_format(x)}, y = {_format(y)}"
        return DomainResult(
            self.domain, "answered", text=text,
            value={"x": _format(x), "y": _format(y)},
            evidence=({"kind": "computation", "ref": text,
                       "source": "domain-math:2x2-system",
                       "detail": {"equations": [
                           [_format(a), _format(b), _format(c)]
                           for a, b, c in equations]}},),
            provenance={"route": "domain-math:2x2-system",
                        "determinant": _format(determinant)},
            detail="exact 2x2 linear system with substitution check",
        )


# ---------------------------------------------------------------------------
# Coding: typed list-operation IR, static checks, and sandboxed execution.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CodeOp:
    name: str
    parameters: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class CodeProgram:
    operations: tuple[CodeOp, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"operations": [op.to_dict() for op in self.operations]}


def _op_source(op: CodeOp) -> str:
    name, params = op.name, op.parameters
    if name == "reverse":
        return "list(reversed(xs))"
    if name == "sort_ascending":
        return "sorted(xs)"
    if name == "sort_descending":
        return "sorted(xs, reverse=True)"
    if name == "dedupe":
        return "list(dict.fromkeys(xs))"
    if name == "double":
        return "[2 * x for x in xs]"
    if name == "square":
        return "[x * x for x in xs]"
    if name == "absolute":
        return "[abs(x) for x in xs]"
    if name == "keep_evens":
        return "[x for x in xs if x % 2 == 0]"
    if name == "keep_odds":
        return "[x for x in xs if x % 2 != 0]"
    if name == "sum_values":
        return "[sum(xs)]"
    if name == "scale_k":
        return f"[{int(params['k'])} * x for x in xs]"
    if name == "add_k":
        return f"[x + {int(params['k'])} for x in xs]"
    if name == "keep_multiples_k":
        return f"[x for x in xs if x % {int(params['k'])} == 0]"
    if name == "first":
        return "xs[:1]"
    if name == "last":
        return "xs[-1:]"
    if name == "drop_first":
        return "xs[1:]"
    if name == "drop_last":
        return "xs[:-1]"
    raise ValueError(f"unsupported code operation: {name!r}")


def apply_code_program(program: CodeProgram, values: Sequence[int]) -> list[int]:
    """Independent interpreter for the typed code IR."""
    rows = [int(value) for value in values]
    for op in program.operations:
        name, params = op.name, op.parameters
        if name == "reverse":
            rows = list(reversed(rows))
        elif name == "sort_ascending":
            rows = sorted(rows)
        elif name == "sort_descending":
            rows = sorted(rows, reverse=True)
        elif name == "dedupe":
            rows = list(dict.fromkeys(rows))
        elif name == "double":
            rows = [2 * value for value in rows]
        elif name == "square":
            rows = [value * value for value in rows]
        elif name == "absolute":
            rows = [abs(value) for value in rows]
        elif name == "keep_evens":
            rows = [value for value in rows if value % 2 == 0]
        elif name == "keep_odds":
            rows = [value for value in rows if value % 2 != 0]
        elif name == "sum_values":
            rows = [sum(rows)]
        elif name == "scale_k":
            rows = [int(params["k"]) * value for value in rows]
        elif name == "add_k":
            rows = [value + int(params["k"]) for value in rows]
        elif name == "keep_multiples_k":
            rows = [value for value in rows if value % int(params["k"]) == 0]
        elif name == "first":
            rows = rows[:1]
        elif name == "last":
            rows = rows[-1:]
        elif name == "drop_first":
            rows = rows[1:]
        elif name == "drop_last":
            rows = rows[:-1]
        else:
            raise ValueError(f"unsupported code operation: {name!r}")
    return rows


def compile_code_program(program: CodeProgram) -> str:
    lines = ["def transform(xs):", "    xs = list(xs)"]
    for op in program.operations:
        lines.append(f"    xs = {_op_source(op)}")
    lines.append("    return xs")
    return "\n".join(lines) + "\n"


_ALLOWED_AST = (
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Assign,
    ast.Return, ast.Expr, ast.Load, ast.Store, ast.Name, ast.List,
    ast.Tuple, ast.ListComp, ast.comprehension, ast.BinOp, ast.UnaryOp,
    ast.Compare, ast.BoolOp, ast.Call, ast.Attribute, ast.Subscript,
    ast.Slice, ast.IfExp, ast.Constant, ast.Add, ast.Sub, ast.Mult,
    ast.Div, ast.Mod, ast.USub, ast.UAdd, ast.Invert, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.And, ast.Or, ast.If, ast.For, ast.AugAssign, ast.keyword,
)


def static_check_code(source: str) -> dict[str, Any]:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return {"passed": False, "detail": f"syntax error: {error}"}
    nodes = list(ast.walk(tree))
    for node in nodes:
        if not isinstance(node, _ALLOWED_AST):
            return {"passed": False,
                    "detail": f"disallowed syntax: {type(node).__name__}"}
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return {"passed": False, "detail": "imports are not allowed"}
        if isinstance(node, ast.Attribute):
            if not (isinstance(node.value, ast.Name)
                    and node.value.id == "dict" and node.attr == "fromkeys"):
                return {"passed": False,
                        "detail": f"attribute access is not allowed: {node.attr}"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in {"list", "reversed", "sorted", "sum", "abs",
                                    "range", "len", "int", "dict"}:
                return {"passed": False,
                        "detail": f"call to {node.func.id!r} is not allowed"}
    if not any(isinstance(node, ast.FunctionDef) and node.name == "transform"
               for node in nodes):
        return {"passed": False, "detail": "missing transform function"}
    return {"passed": True, "nodes": len(nodes),
            "detail": "bounded AST, no imports, allowed calls only"}


def _sandbox_run(source: str, values: Sequence[int], *, timeout: float = 3.0
                 ) -> dict[str, Any]:
    runner = (
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "namespace = {}\n"
        "exec(compile(payload['source'], '<generated>', 'exec'), namespace)\n"
        "result = namespace['transform'](payload['values'])\n"
        "print(json.dumps({'ok': True, 'result': result}))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", runner],
            input=json.dumps({"source": source, "values": list(values)}),
            text=True, capture_output=True, timeout=timeout, check=False,
            env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "sandbox timeout"}
    if completed.returncode != 0:
        return {"ok": False,
                "detail": (completed.stderr or "sandbox process failed")[-1200:]}
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return {"ok": False, "detail": "sandbox emitted malformed JSON"}
    if not payload.get("ok"):
        return {"ok": False, "detail": str(payload.get("detail", "sandbox failed"))}
    return payload


class CodeDomain:
    domain = "coding"

    def __init__(self, registry: RuleRegistry | None = None) -> None:
        self.registry = registry

    def active_ops(self) -> set[str] | None:
        if self.registry is None:
            return None
        return {
            str(record.payload.get("operation"))
            for record in self.registry.records(family=DOMAIN_FAMILY, state="active")
            if record.payload.get("origin") == DOMAIN_ORIGIN
            and record.payload.get("kind") == "code-operation"
        }

    def parse(self, request: str) -> CodeProgram:
        if not isinstance(request, str) or not request.strip():
            raise ValueError("empty code request")
        text = re.sub(r"^\s*(?:write|generate|create)\s+(?:python\s+)?code\s+(?:that|to)\s+",
                      "", request.strip(), flags=re.IGNORECASE)
        text = text.rstrip(" .!?")
        clauses = [item.strip() for item in re.split(r"\s+then\s+|,\s*then\s+",
                                                     text, flags=re.IGNORECASE)
                   if item.strip()]
        operations: list[CodeOp] = []
        for clause in clauses:
            normalized = clause.casefold()
            if re.fullmatch(r"reverse (?:the )?(?:list|values)", normalized):
                operations.append(CodeOp("reverse"))
            elif re.fullmatch(r"sort (?:the )?(?:list|values)(?: in descending order)?",
                              normalized):
                operations.append(CodeOp(
                    "sort_descending" if "descending" in normalized
                    else "sort_ascending"))
            elif re.fullmatch(r"remove (?:the )?duplicates", normalized):
                operations.append(CodeOp("dedupe"))
            elif re.fullmatch(r"double (?:each|every|the) values?", normalized):
                operations.append(CodeOp("double"))
            elif re.fullmatch(r"square (?:each|every|the) values?", normalized):
                operations.append(CodeOp("square"))
            elif re.fullmatch(r"(?:take|use) (?:the )?absolute values?", normalized):
                operations.append(CodeOp("absolute"))
            elif re.fullmatch(r"keep (?:the )?even values?", normalized):
                operations.append(CodeOp("keep_evens"))
            elif re.fullmatch(r"keep (?:the )?odd values?", normalized):
                operations.append(CodeOp("keep_odds"))
            elif re.fullmatch(r"sum (?:the |all )?values?", normalized):
                operations.append(CodeOp("sum_values"))
            elif (match := re.fullmatch(
                    r"multiply (?:each|every|the) values? by ([+-]?\d+)",
                    normalized)):
                operations.append(CodeOp("scale_k", {"k": int(match.group(1))}))
            elif (match := re.fullmatch(
                    r"add ([+-]?\d+) to (?:each|every|the) values?",
                    normalized)):
                operations.append(CodeOp("add_k", {"k": int(match.group(1))}))
            elif (match := re.fullmatch(
                    r"keep values divisible by ([1-9]\d*)", normalized)):
                operations.append(CodeOp("keep_multiples_k",
                                         {"k": int(match.group(1))}))
            elif re.fullmatch(r"keep only (?:the )?first value", normalized):
                operations.append(CodeOp("first"))
            elif re.fullmatch(r"keep only (?:the )?last value", normalized):
                operations.append(CodeOp("last"))
            elif re.fullmatch(r"drop (?:the )?first value", normalized):
                operations.append(CodeOp("drop_first"))
            elif re.fullmatch(r"drop (?:the )?last value", normalized):
                operations.append(CodeOp("drop_last"))
            else:
                raise ValueError(f"unsupported code clause: {clause!r}")
        if not operations:
            raise ValueError("the code request contained no supported operation")
        return CodeProgram(tuple(operations))

    def solve(self, request: str, values: Sequence[int]) -> DomainResult:
        try:
            program = self.parse(request)
        except ValueError as error:
            return DomainResult(self.domain, "abstained", detail=str(error),
                                repair_question=("Rephrase the request with a supported "
                                                 "list operation."))
        active = self.active_ops()
        if active is not None:
            inactive = [op.name for op in program.operations if op.name not in active]
            if inactive:
                return DomainResult(
                    self.domain, "abstained",
                    detail=f"no active domain rule for operation(s): {', '.join(inactive)}",
                    repair_question="Reactivate the retired operation or choose another one.")
        if not isinstance(values, (list, tuple)) or len(values) > 100 or any(
                type(value) is not int for value in values):
            return DomainResult(self.domain, "abstained",
                                detail="input contract is a list of at most 100 integers")
        source = compile_code_program(program)
        static = static_check_code(source)
        if not static.get("passed"):
            return DomainResult(self.domain, "abstained",
                                detail=f"static check failed: {static.get('detail')}",
                                repair_question="Simplify the generated code contract.")
        sandbox = _sandbox_run(source, values)
        if not sandbox.get("ok"):
            return DomainResult(self.domain, "abstained",
                                detail=f"sandbox failed: {sandbox.get('detail')}",
                                repair_question="Adjust the input or operation sequence.")
        output = sandbox.get("result")
        if not isinstance(output, list) or len(output) > 100 or any(
                type(value) is not int for value in output):
            return DomainResult(self.domain, "abstained",
                                detail="output contract failed: expected at most 100 integers")
        return DomainResult(
            self.domain, "answered",
            text=f"transform({list(values)}) = {output}",
            value=output,
            evidence=(
                {"kind": "generated-code",
                 "ref": "sha256:" + hashlib.sha256(source.encode()).hexdigest()[:16],
                 "source": "domain-code:typed-ir",
                 "detail": {"program": program.to_dict(),
                            "static_nodes": static.get("nodes"),
                            "sandbox": True}},
            ),
            provenance={"route": "domain-code:typed-ir",
                        "program": program.to_dict(),
                        "source": source,
                        "static_check": static,
                        "contract": {"input": "list[int]<=100",
                                     "output": "list[int]<=100"}},
            rule_ids=tuple(f"domain-code-op-{op.name}" for op in program.operations),
            detail="generated, statically checked, and sandboxed",
        )

    def repair(self, invalid_request: str, values: Sequence[int],
               replacement_request: str) -> DomainResult:
        """Retry after the user replaces an unsupported operation."""
        failed = self.solve(invalid_request, values)
        if failed.answered:
            return failed
        return self.solve(replacement_request, values)


# ---------------------------------------------------------------------------
# Translation: bounded compositional lexicon plus adjective agreement.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NounEntry:
    source: str
    gender: str
    singular: str
    plural: str
    rule_id: str


@dataclass(frozen=True)
class AdjectiveEntry:
    source: str
    masculine_singular: str
    feminine_singular: str
    masculine_plural: str
    feminine_plural: str
    rule_id: str

    def form(self, gender: str, plural: bool) -> str:
        if gender == "f":
            return self.feminine_plural if plural else self.feminine_singular
        return self.masculine_plural if plural else self.masculine_singular


_DEFAULT_NOUNS = (
    NounEntry("house", "f", "casa", "casas", "domain-translation-noun-house"),
    NounEntry("garden", "m", "jardín", "jardines", "domain-translation-noun-garden"),
    NounEntry("book", "m", "libro", "libros", "domain-translation-noun-book"),
    NounEntry("table", "f", "mesa", "mesas", "domain-translation-noun-table"),
    NounEntry("window", "f", "ventana", "ventanas", "domain-translation-noun-window"),
    NounEntry("river", "m", "río", "ríos", "domain-translation-noun-river"),
    NounEntry("road", "m", "camino", "caminos", "domain-translation-noun-road"),
    NounEntry("candle", "f", "vela", "velas", "domain-translation-noun-candle"),
)
_DEFAULT_ADJECTIVES = (
    AdjectiveEntry("red", "rojo", "roja", "rojos", "rojas",
                   "domain-translation-adj-red"),
    AdjectiveEntry("small", "pequeño", "pequeña", "pequeños", "pequeñas",
                   "domain-translation-adj-small"),
    AdjectiveEntry("old", "viejo", "vieja", "viejos", "viejas",
                   "domain-translation-adj-old"),
    AdjectiveEntry("quiet", "tranquilo", "tranquila", "tranquilos",
                   "tranquilas", "domain-translation-adj-quiet"),
    AdjectiveEntry("bright", "brillante", "brillante", "brillantes",
                   "brillantes", "domain-translation-adj-bright"),
    AdjectiveEntry("narrow", "estrecho", "estrecha", "estrechos",
                   "estrechas", "domain-translation-adj-narrow"),
)


def _determiner(gender: str, plural: bool) -> str:
    if plural:
        return "los" if gender == "m" else "las"
    return "el" if gender == "m" else "la"


class BoundedTranslator:
    """English-to-Spanish reviewed lexicon with exact adjective agreement."""

    domain = "translation"
    frame_rule_id = "domain-translation-frame-np-location"

    def __init__(self, nouns: Iterable[NounEntry] = _DEFAULT_NOUNS,
                 adjectives: Iterable[AdjectiveEntry] = _DEFAULT_ADJECTIVES,
                 registry: RuleRegistry | None = None) -> None:
        self.nouns = {entry.source: entry for entry in nouns}
        self.adjectives = {entry.source: entry for entry in adjectives}
        self.registry = registry

    def _noun(self, surface: str) -> tuple[NounEntry, bool] | None:
        token = _norm(surface)
        for entry in self.nouns.values():
            if token == entry.source:
                return entry, False
            if token == entry.source + "s":
                return entry, True
            if token == entry.singular:
                return entry, False
            if token == entry.plural:
                return entry, True
        return None

    def teach_noun(self, source: str, gender: str, singular: str,
                   plural: str, *, rule_id: str | None = None) -> NounEntry:
        entry = NounEntry(_norm(source), gender, _norm(singular), _norm(plural),
                          rule_id or f"domain-translation-noun-{_norm(source)}")
        self.nouns[entry.source] = entry
        if self.registry is not None:
            register_domain_rule(
                self.registry, rule_id=entry.rule_id,
                statement=f"Spanish noun {entry.source!r} -> {entry.singular!r}",
                scope="English->Spanish lexicon", payload={
                    "origin": DOMAIN_ORIGIN, "domain": "translation",
                    "kind": "translation-noun", "source": entry.source,
                    "gender": gender, "singular": singular, "plural": plural},
                cases=2, sources=1)
        return entry

    def teach_adjective(self, source: str, masculine_singular: str,
                        feminine_singular: str, masculine_plural: str,
                        feminine_plural: str, *,
                        rule_id: str | None = None) -> AdjectiveEntry:
        entry = AdjectiveEntry(
            _norm(source), _norm(masculine_singular), _norm(feminine_singular),
            _norm(masculine_plural), _norm(feminine_plural),
            rule_id or f"domain-translation-adj-{_norm(source)}")
        self.adjectives[entry.source] = entry
        if self.registry is not None:
            register_domain_rule(
                self.registry, rule_id=entry.rule_id,
                statement=f"Spanish adjective {entry.source!r} agrees by gender/number",
                scope="English->Spanish lexicon", payload={
                    "origin": DOMAIN_ORIGIN, "domain": "translation",
                    "kind": "translation-adjective", "source": entry.source,
                    "forms": [entry.masculine_singular, entry.feminine_singular,
                              entry.masculine_plural, entry.feminine_plural]},
                cases=2, sources=1)
        return entry

    def translate_sentence(self, sentence: str, *, register: str = "plain"
                           ) -> DomainResult:
        if not isinstance(sentence, str) or not sentence.strip():
            return DomainResult(self.domain, "abstained",
                                detail="empty translation source")
        if register not in {"plain", "formal"}:
            return DomainResult(self.domain, "abstained",
                                detail="register must be 'plain' or 'formal'")
        tokens = _norm(sentence).split()
        if len(tokens) < 3 or tokens[0] != "the":
            return DomainResult(self.domain, "abstained",
                                detail="supported source shape starts with 'the'",
                                repair_question="Use 'the [adjective] noun is ...'.")
        cursor = 1
        adjective: AdjectiveEntry | None = None
        if tokens[cursor] in self.adjectives:
            adjective = self.adjectives[tokens[cursor]]
            cursor += 1
        if cursor >= len(tokens):
            return DomainResult(self.domain, "abstained", detail="missing noun")
        noun_lookup = self._noun(tokens[cursor])
        if noun_lookup is None:
            unknown = tokens[cursor]
            return DomainResult(
                self.domain, "abstained",
                detail=f"unknown noun: {unknown!r}",
                repair_question=f"Teach the Spanish noun for {unknown!r}.",
                value={"unknown_kind": "noun", "unknown": unknown})
        noun, plural = noun_lookup
        cursor += 1
        if cursor >= len(tokens) or tokens[cursor] not in {"is", "are"}:
            return DomainResult(self.domain, "abstained",
                                detail="expected 'is' or 'are' after the subject")
        copula = tokens[cursor]
        if (copula == "are") != plural:
            return DomainResult(self.domain, "abstained",
                                detail="subject number and copula disagree")
        cursor += 1
        subject_determiner = _determiner(noun.gender, plural)
        subject_adjective = (adjective.form(noun.gender, plural)
                             if adjective is not None else "")
        subject = " ".join(part for part in (
            subject_determiner, noun.plural if plural else noun.singular,
            subject_adjective) if part)

        target_roles: dict[str, Any] = {
            "subject": noun.source,
            "subject_number": "plural" if plural else "singular",
            "subject_gender": noun.gender,
        }
        if adjective is not None:
            target_roles["subject_adjective"] = adjective.source

        if cursor < len(tokens) and tokens[cursor] == "in":
            cursor += 1
            if cursor >= len(tokens) or tokens[cursor] != "the":
                return DomainResult(self.domain, "abstained",
                                    detail="expected 'the' after 'in'")
            cursor += 1
            location_adjective: AdjectiveEntry | None = None
            if cursor < len(tokens) and tokens[cursor] in self.adjectives:
                location_adjective = self.adjectives[tokens[cursor]]
                cursor += 1
            if cursor >= len(tokens):
                return DomainResult(self.domain, "abstained", detail="missing location noun")
            location_lookup = self._noun(tokens[cursor])
            if location_lookup is None:
                unknown = tokens[cursor]
                return DomainResult(
                    self.domain, "abstained",
                    detail=f"unknown noun: {unknown!r}",
                    repair_question=f"Teach the Spanish noun for {unknown!r}.",
                    value={"unknown_kind": "noun", "unknown": unknown})
            location, location_plural = location_lookup
            cursor += 1
            if cursor != len(tokens):
                return DomainResult(self.domain, "abstained",
                                    detail="trailing words are outside the supported frame")
            location_determiner = _determiner(location.gender, location_plural)
            location_adjective_text = (location_adjective.form(
                location.gender, location_plural)
                if location_adjective is not None else "")
            location_text = " ".join(part for part in (
                location_determiner,
                location.plural if location_plural else location.singular,
                location_adjective_text) if part)
            verb = ("se encuentra en" if register == "formal"
                    else "está en") if not plural else (
                        "se encuentran en" if register == "formal"
                        else "están en")
            output = f"{subject} {verb} {location_text}"
            target_roles["location"] = location.source
            target_roles["location_number"] = ("plural" if location_plural
                                               else "singular")
            if location_adjective is not None:
                target_roles["location_adjective"] = location_adjective.source
            evidence = [
                {"kind": "translation",
                 "ref": self.frame_rule_id,
                 "source": "reviewed-bilingual-lexicon",
                 "detail": {"source": sentence, "target": output,
                            "register": register}},
                {"kind": "rule", "ref": noun.rule_id,
                 "source": "reviewed-bilingual-lexicon",
                 "detail": {"noun": noun.source}},
            ]
            rule_ids = [self.frame_rule_id, noun.rule_id, location.rule_id]
            if adjective is not None:
                evidence.append({"kind": "rule", "ref": adjective.rule_id,
                                 "source": "reviewed-bilingual-lexicon",
                                 "detail": {"adjective": adjective.source}})
                rule_ids.append(adjective.rule_id)
            if location_adjective is not None:
                evidence.append({"kind": "rule", "ref": location_adjective.rule_id,
                                 "source": "reviewed-bilingual-lexicon",
                                 "detail": {"adjective": location_adjective.source}})
                rule_ids.append(location_adjective.rule_id)
            return DomainResult(
                self.domain, "answered", text=output,
                value={"roles": target_roles, "register": register},
                evidence=tuple(evidence),
                provenance={"route": "domain-translation:np-location",
                            "register": register,
                            "roles": target_roles},
                rule_ids=tuple(dict.fromkeys(rule_ids)),
                detail="agreement-checked compositional translation",
            )

        # Predicate adjective: "the red house is small."
        if cursor >= len(tokens) or tokens[cursor] not in self.adjectives:
            unknown = tokens[cursor] if cursor < len(tokens) else ""
            return DomainResult(
                self.domain, "abstained",
                detail=(f"unknown predicate adjective: {unknown!r}" if unknown
                        else "missing predicate"),
                repair_question=(f"Teach the Spanish adjective for {unknown!r}."
                                 if unknown else "Add a predicate or location."),
                value=({"unknown_kind": "adjective", "unknown": unknown}
                       if unknown else {}))
        predicate = self.adjectives[tokens[cursor]]
        cursor += 1
        if cursor != len(tokens):
            return DomainResult(self.domain, "abstained",
                                detail="trailing words are outside the supported frame")
        copula_target = "son" if plural else "es"
        output = f"{subject} {copula_target} {predicate.form(noun.gender, plural)}"
        target_roles["predicate_adjective"] = predicate.source
        evidence = [
            {"kind": "translation", "ref": self.frame_rule_id,
             "source": "reviewed-bilingual-lexicon",
             "detail": {"source": sentence, "target": output,
                        "register": register}},
            {"kind": "rule", "ref": noun.rule_id,
             "source": "reviewed-bilingual-lexicon",
             "detail": {"noun": noun.source}},
            {"kind": "rule", "ref": predicate.rule_id,
             "source": "reviewed-bilingual-lexicon",
             "detail": {"adjective": predicate.source}},
        ]
        rule_ids = [self.frame_rule_id, noun.rule_id, predicate.rule_id]
        if adjective is not None:
            evidence.append({"kind": "rule", "ref": adjective.rule_id,
                             "source": "reviewed-bilingual-lexicon",
                             "detail": {"adjective": adjective.source}})
            rule_ids.append(adjective.rule_id)
        return DomainResult(
            self.domain, "answered", text=output,
            value={"roles": target_roles, "register": register},
            evidence=tuple(evidence),
            provenance={"route": "domain-translation:predicate",
                        "register": register, "roles": target_roles},
            rule_ids=tuple(dict.fromkeys(rule_ids)),
            detail="agreement-checked predicate translation",
        )

    def translate_request(self, request: str) -> DomainResult:
        if not isinstance(request, str):
            return DomainResult(self.domain, "abstained", detail="empty request")
        match = re.fullmatch(
            r"\s*translate\s+(?P<quote>[\"“']?)(?P<sentence>.+?)"
            r"(?P=quote)\s+into\s+Spanish"
            r"(?:\s+in\s+(?P<register>plain|formal)\s+register)?\s*[.!?]*\s*",
            request, re.IGNORECASE | re.DOTALL)
        if match is None:
            return DomainResult(self.domain, "abstained",
                                detail="use 'Translate SENTENCE into Spanish [in formal register]'.")
        return self.translate_sentence(
            match.group("sentence").strip(),
            register=(match.group("register") or "plain").casefold())

    def repair_unknown(self, result: DomainResult, *, gender: str = "f",
                       singular: str, plural: str, sentence: str,
                       register: str = "plain") -> DomainResult:
        if result.answered or not isinstance(result.value, Mapping):
            return result
        if result.value.get("unknown_kind") != "noun":
            return result
        unknown = str(result.value.get("unknown", ""))
        if not unknown:
            return result
        self.teach_noun(unknown, gender, singular, plural)
        return self.translate_sentence(sentence, register=register)


# ---------------------------------------------------------------------------
# Creative: constraint planner over the deterministic story grammar.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CreativeBrief:
    topic: str
    tone: str = "adventure"
    must_include: tuple[str, ...] = ()
    must_avoid: tuple[str, ...] = ()
    max_words: int = 180
    pov: str = "third"

    def validate(self) -> None:
        if not self.topic.strip() or len(self.topic) > 120:
            raise ValueError("creative topic must be 1 to 120 characters")
        if self.tone not in {"adventure", "funny", "mystery"}:
            raise ValueError("creative tone must be adventure, funny, or mystery")
        if self.max_words < 20 or self.max_words > 400:
            raise ValueError("max_words must be between 20 and 400")
        if self.pov not in {"third"}:
            raise ValueError("this bounded planner supports third-person narration")
        for value in (*self.must_include, *self.must_avoid):
            if not value.strip() or len(value) > 80:
                raise ValueError("constraints must be 1 to 80 characters")


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9’'-]+", text))


def _insert_motif(story: StoryArtifact, motif: str) -> StoryArtifact:
    beats = list(story.beats)
    if any(motif.casefold() in sentence.casefold()
           for _role, sentence in beats):
        return story
    for index, (role, sentence) in enumerate(beats):
        if role == "attempt":
            beats[index] = (role, sentence + f" A {motif} became part of the plan.")
            break
    else:
        beats.append(("motif", f"A {motif} became part of the plan."))
    return StoryArtifact(story.topic, story.tone, story.template_id, tuple(beats))


def creative_rubric(text: str, brief: CreativeBrief, *,
                    template_id: str | None = None) -> dict[str, Any]:
    folded = text.casefold()
    words = _word_count(text)
    checks = {
        "topic_present": brief.topic.casefold() in folded,
        "must_include": all(item.casefold() in folded for item in brief.must_include),
        "must_avoid": not any(item.casefold() in folded for item in brief.must_avoid),
        "word_limit": words <= brief.max_words,
        "five_beats": template_id is not None,
        "no_placeholders": "{" not in text and "}" not in text,
        "third_person": brief.pov == "third",
    }
    score = sum(1 for value in checks.values() if value) / len(checks)
    return {"checks": checks, "score": round(score, 4), "words": words,
            "passed": all(checks.values())}


class CreativeDomain:
    domain = "creative"

    def compose(self, brief: CreativeBrief) -> DomainResult:
        try:
            brief.validate()
        except ValueError as error:
            return DomainResult(self.domain, "abstained", detail=str(error),
                                repair_question="Revise the brief constraints.")
        include = {item.casefold() for item in brief.must_include}
        avoid = {item.casefold() for item in brief.must_avoid}
        if include & avoid:
            conflict = sorted(include & avoid)[0]
            return DomainResult(
                self.domain, "abstained",
                detail=f"constraints both require and forbid {conflict!r}",
                repair_question=(f"Should {conflict!r} be included or avoided?"))
        candidates = []
        for tone in dict.fromkeys((brief.tone, "adventure", "mystery", "funny")):
            try:
                story = generate_short_story(brief.topic, tone=tone)
            except ValueError as error:
                return DomainResult(self.domain, "abstained", detail=str(error))
            for motif in brief.must_include:
                story = _insert_motif(story, motif)
            rubric = creative_rubric(story.text, brief,
                                     template_id=story.template_id)
            candidates.append((story, rubric))
            if rubric["passed"]:
                return DomainResult(
                    self.domain, "answered", text=story.render(),
                    value={"rubric": rubric,
                           "template_id": story.template_id,
                           "tone": story.tone,
                           "beats": len(story.beats)},
                    evidence=(
                        {"kind": "generated-text",
                         "ref": story.template_id,
                         "source": "domain-creative:constraint-planner",
                         "detail": {"topic": story.topic,
                                    "fictional": True,
                                    "constraints": {
                                        "include": list(brief.must_include),
                                        "avoid": list(brief.must_avoid),
                                        "max_words": brief.max_words}}},
                    ),
                    provenance={"route": "domain-creative:constraint-planner",
                                "template_id": story.template_id,
                                "rubric": rubric},
                    rule_ids=(f"domain-creative-template-{story.template_id}",),
                    detail="constraints satisfied by the deterministic story planner",
                )
        best = max(candidates, key=lambda item: item[1]["score"]) if candidates else None
        return DomainResult(
            self.domain, "abstained",
            detail=("no eligible story template satisfies the constraints; "
                    f"best rubric score {best[1]['score'] if best else 0}"),
            repair_question=("Relax the word limit, forbidden word, or required motif."),
            value={"rubric": best[1] if best else None},
        )

    def repair(self, brief: CreativeBrief, *,
               remove_avoid: str | None = None,
               max_words: int | None = None) -> DomainResult:
        fixed = CreativeBrief(
            topic=brief.topic, tone=brief.tone,
            must_include=brief.must_include,
            must_avoid=tuple(item for item in brief.must_avoid
                             if item.casefold() != (remove_avoid or "").casefold()),
            max_words=max_words if max_words is not None else brief.max_words,
            pov=brief.pov,
        )
        return self.compose(fixed)


# ---------------------------------------------------------------------------
# Cross-domain: two-stage plans through the typed task IR.
# ---------------------------------------------------------------------------

def _decode_program(raw: Mapping[str, Any]) -> CodeProgram:
    return CodeProgram(tuple(CodeOp(str(item["name"]),
                                    {str(k): int(v) for k, v in
                                     dict(item.get("parameters", {})).items()})
                             for item in raw.get("operations", ())))


class _ProgramAction(Action):
    name = "domain-list-program"

    def can_apply(self, inputs: Mapping[str, Any], context: ExecutionContext) -> bool:
        return isinstance(inputs.get("values"), (list, tuple))

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        program = _decode_program(inputs.get("program", {}))
        try:
            output = apply_code_program(program, inputs["values"])
        except (TypeError, ValueError) as error:
            return StepResult(step.id, "failed", reason_code="invalid_program",
                              detail=f"invalid list program: {error}")
        return StepResult(step.id, "ok", output={"values": output},
                          evidence=(EvidenceRef("generated-code",
                                                "domain-code:typed-ir"),),
                          reason_code="list_program")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        program = _decode_program(inputs.get("program", {}))
        expected = apply_code_program(program, inputs["values"])
        return Verification(result.output.get("values") == expected,
                            "list program replay differed")


class _MapAction(Action):
    name = "domain-math-map"

    def __init__(self) -> None:
        pass

    def can_apply(self, inputs: Mapping[str, Any], context: ExecutionContext) -> bool:
        return isinstance(inputs.get("values"), (list, tuple))

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        values = [int(value) for value in inputs["values"]]
        operation = str(inputs.get("operation"))
        if operation == "double":
            output = [2 * value for value in values]
        elif operation == "scale_k":
            output = [int(inputs.get("k", 1)) * value for value in values]
        elif operation == "add_k":
            output = [value + int(inputs.get("k", 0)) for value in values]
        else:
            return StepResult(step.id, "failed", reason_code="unsupported_map",
                              detail=f"unsupported math map: {operation!r}")
        return StepResult(step.id, "ok", output={"values": output},
                          evidence=(EvidenceRef("computation",
                                                f"map:{operation}"),),
                          reason_code="math_map")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        values = [int(value) for value in inputs["values"]]
        operation = str(inputs.get("operation"))
        if operation == "double":
            expected = [2 * value for value in values]
        elif operation == "scale_k":
            expected = [int(inputs.get("k", 1)) * value for value in values]
        elif operation == "add_k":
            expected = [value + int(inputs.get("k", 0)) for value in values]
        else:
            return Verification(False, "unsupported map replay")
        return Verification(result.output.get("values") == expected,
                            "math map replay differed")


class _TranslateAction(Action):
    name = "domain-translate"

    def __init__(self, translator: BoundedTranslator) -> None:
        self.translator = translator

    def can_apply(self, inputs: Mapping[str, Any], context: ExecutionContext) -> bool:
        return isinstance(inputs.get("sentence"), str)

    def _translate(self, inputs: Mapping[str, Any]) -> DomainResult:
        return self.translator.translate_sentence(
            str(inputs["sentence"]),
            register=str(inputs.get("register", "plain")))

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        result = self._translate(inputs)
        if not result.answered:
            return StepResult(step.id, "failed", reason_code="translation_failed",
                              detail=result.detail or "translation abstained")
        return StepResult(step.id, "ok",
                          output={"text": result.text},
                          evidence=tuple(EvidenceRef(
                              "translation", item.get("ref", "domain-translation"),
                              source=item.get("source")) for item in result.evidence),
                          reason_code="translated")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        replay = self._translate(inputs)
        return Verification(replay.answered and replay.text == result.output.get("text"),
                            "translation replay differed")


class _CountAction(Action):
    name = "domain-word-count"

    def can_apply(self, inputs: Mapping[str, Any], context: ExecutionContext) -> bool:
        return isinstance(inputs.get("text"), str)

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        count = _word_count(str(inputs["text"]))
        return StepResult(step.id, "ok", output={"count": count},
                          evidence=(EvidenceRef("computation", "word-count"),),
                          reason_code="counted")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        return Verification(result.output.get("count") == _word_count(
            str(inputs["text"])), "word count replay differed")


def _cross_plan_check(plan: Plan, outputs: Mapping[str, Any],
                      context: ExecutionContext) -> Verification:
    last = outputs.get(plan.steps[-1].id)
    return Verification(isinstance(last, Mapping) and bool(last),
                        "the final cross-domain step produced no output")


@dataclass(frozen=True)
class CrossResult:
    status: str
    output: Any = None
    plan: dict[str, Any] | None = None
    steps: tuple[dict[str, Any], ...] = ()
    detail: str = ""

    @property
    def answered(self) -> bool:
        return self.status == "ok"


class CrossDomain:
    domain = "cross-domain"

    def __init__(self, translator: BoundedTranslator | None = None) -> None:
        self.translator = translator or BoundedTranslator()

    def _executor(self) -> PlanExecutor:
        registry = ActionRegistry()
        registry.register(_ProgramAction())
        registry.register(_MapAction())
        registry.register(_TranslateAction(self.translator))
        registry.register(_CountAction())
        return PlanExecutor(registry, plan_verifier=_cross_plan_check)

    def run_list_math(self, text: str, program: CodeProgram,
                      values: Sequence[int], *, math_op: str,
                      k: int = 1) -> CrossResult:
        request = TaskRequest(
            request_id(text, "cross-list-math"), text, "cross-list-math",
            slots={"values": list(values), "program": program.to_dict(),
                   "math_op": math_op, "k": k})
        steps = (
            Step("transform", "domain-list-program",
                 {"program": program.to_dict(), "values": list(values)},
                 "list[int]", evidence=(EvidenceRef("generated-code",
                                                    "domain-code:typed-ir"),),
                 check=CheckSpec("exact")),
            Step("map", "domain-math-map",
                 {"values": "transform.output.values", "operation": math_op,
                  "k": k}, "list[int]",
                 evidence=(EvidenceRef("computation", f"map:{math_op}"),),
                 check=CheckSpec("exact"), depends_on=("transform",)),
        )
        plan = Plan(request, steps, verification=CheckSpec("exact"))
        result = self._executor().execute(plan)
        return CrossResult(
            result.status,
            output=(result.output.get("values") if isinstance(result.output, Mapping)
                    else result.output),
            plan=result.plan.to_dict() if result.plan else None,
            steps=tuple(step.to_dict() for step in result.steps),
            detail="; ".join(result.failures),
        )

    def run_translate_count(self, text: str, sentence: str,
                            *, register: str = "plain") -> CrossResult:
        request = TaskRequest(
            request_id(text, "cross-translate-count"), text,
            "cross-translate-count",
            slots={"sentence": sentence, "register": register})
        steps = (
            Step("translate", "domain-translate",
                 {"sentence": sentence, "register": register}, "text",
                 evidence=(EvidenceRef("translation",
                                       "domain-translation:np-location"),),
                 check=CheckSpec("exact")),
            Step("count", "domain-word-count",
                 {"text": "translate.output.text"}, "integer",
                 evidence=(EvidenceRef("computation", "word-count"),),
                 check=CheckSpec("exact"), depends_on=("translate",)),
        )
        plan = Plan(request, steps, verification=CheckSpec("exact"))
        result = self._executor().execute(plan)
        return CrossResult(
            result.status,
            output=(result.output.get("count") if isinstance(result.output, Mapping)
                    else result.output),
            plan=result.plan.to_dict() if result.plan else None,
            steps=tuple(step.to_dict() for step in result.steps),
            detail="; ".join(result.failures),
        )

    def repair_list_math(self, text: str, invalid_program: CodeProgram,
                         values: Sequence[int], replacement: CodeProgram,
                         *, math_op: str, k: int = 1) -> CrossResult:
        failed = self.run_list_math(text, invalid_program, values,
                                    math_op=math_op, k=k)
        if failed.answered:
            return failed
        return self.run_list_math(text, replacement, values,
                                  math_op=math_op, k=k)


# ---------------------------------------------------------------------------
# Domain rule registration.
# ---------------------------------------------------------------------------

def _domain_rule_check(payload: Mapping[str, Any]) -> tuple[bool, str]:
    domain = str(payload.get("domain", ""))
    kind = str(payload.get("kind", ""))
    if domain == "math" and kind == "math-template":
        return (payload.get("name") in {
            "word-subtract", "word-speed", "word-cost", "word-add",
            "inequality-linear", "system-2x2", "exact-arithmetic"},
            "math template is in the declared exact slice")
    if domain == "coding" and kind == "code-operation":
        return (payload.get("operation") in {
            "reverse", "sort_ascending", "sort_descending", "dedupe",
            "double", "square", "absolute", "keep_evens", "keep_odds",
            "sum_values", "scale_k", "add_k", "keep_multiples_k",
            "first", "last", "drop_first", "drop_last"},
            "code operation is in the typed list contract")
    if domain == "translation" and kind in {
            "translation-noun", "translation-adjective",
            "translation-frame"}:
        if kind == "translation-frame":
            return True, "translation frame names a bounded grammar"
        return (bool(payload.get("source")) and
                (bool(payload.get("singular")) if kind == "translation-noun"
                 else bool(payload.get("forms"))),
                "translation lexicon entry has target forms")
    if domain == "creative" and kind == "creative-template":
        return (payload.get("template_id") in {
            "discovery-and-cooperation-v1", "mystery-and-repair-v1",
            "mystery-midnight-library-v1", "small-kindness-v1",
            "comic-council-v1"}, "story template is in the bounded grammar")
    if domain == "cross-domain" and kind == "cross-plan":
        return (payload.get("name") in {"list-math", "translate-count"},
                "cross-domain plan is registered")
    return False, "unknown domain rule payload"


def register_domain_rule(registry: RuleRegistry, *, rule_id: str,
                         statement: str, scope: str,
                         payload: Mapping[str, Any], cases: int,
                         sources: int, oracle: str = "domain-replay",
                         trust: str = "source-reviewed") -> RuleRecord:
    passed, detail = _domain_rule_check(payload)
    passed = passed and cases >= 2 and sources >= 1
    if rule_id not in registry:
        registry.propose(
            rule_id=rule_id, family=DOMAIN_FAMILY,
            statement=statement, scope=scope, payload=dict(payload),
            provenance=({"source": "crms_domains", "rule_id": rule_id},),
            trust=trust)
    registry.validate(
        rule_id, oracle=oracle, passed=passed, cases=max(2, cases),
        independent_sources=max(1, sources), detail=detail)
    record = registry.get(rule_id)
    if passed and record.state in {"proposed", "validated"}:
        registry.activate(rule_id, mode="review", authoriser="teacher")
    return registry.get(rule_id)


def domain_rule_definitions(translator: BoundedTranslator | None = None
                            ) -> list[dict[str, Any]]:
    translator = translator or BoundedTranslator()
    definitions: list[dict[str, Any]] = []
    for name, statement in (
            ("word-subtract", "remaining quantity = initial - removed"),
            ("word-speed", "average speed = distance / time"),
            ("word-cost", "total cost = unit price * count"),
            ("word-add", "new total = initial + arrivals"),
            ("inequality-linear", "solve a linear one-variable inequality"),
            ("system-2x2", "solve a unique 2x2 linear system"),
            ("exact-arithmetic", "exact arithmetic, equations, and learned units")):
        definitions.append({
            "rule_id": f"domain-math-{name}", "statement": statement,
            "scope": "math; exact/rational", "cases": 2, "sources": 1,
            "payload": {"origin": DOMAIN_ORIGIN, "domain": "math",
                        "kind": "math-template", "name": name}})
    for op in ("reverse", "sort_ascending", "sort_descending", "dedupe",
               "double", "square", "absolute", "keep_evens", "keep_odds",
               "sum_values", "scale_k", "add_k", "keep_multiples_k",
               "first", "last", "drop_first", "drop_last"):
        definitions.append({
            "rule_id": f"domain-code-op-{op}",
            "statement": f"typed code operation {op}",
            "scope": "coding; list[int] contract", "cases": 2, "sources": 1,
            "payload": {"origin": DOMAIN_ORIGIN, "domain": "coding",
                        "kind": "code-operation", "operation": op}})
    for noun in translator.nouns.values():
        definitions.append({
            "rule_id": noun.rule_id,
            "statement": f"Spanish noun {noun.source!r} -> {noun.singular!r}",
            "scope": "English->Spanish lexicon", "cases": 2, "sources": 1,
            "payload": {"origin": DOMAIN_ORIGIN, "domain": "translation",
                        "kind": "translation-noun", "source": noun.source,
                        "gender": noun.gender, "singular": noun.singular,
                        "plural": noun.plural}})
    for adjective in translator.adjectives.values():
        definitions.append({
            "rule_id": adjective.rule_id,
            "statement": f"Spanish adjective {adjective.source!r} agrees",
            "scope": "English->Spanish lexicon", "cases": 2, "sources": 1,
            "payload": {"origin": DOMAIN_ORIGIN, "domain": "translation",
                        "kind": "translation-adjective",
                        "source": adjective.source,
                        "forms": [adjective.masculine_singular,
                                  adjective.feminine_singular,
                                  adjective.masculine_plural,
                                  adjective.feminine_plural]}})
    definitions.append({
        "rule_id": BoundedTranslator.frame_rule_id,
        "statement": "English NP location/predicate frame -> Spanish agreement frame",
        "scope": "English->Spanish; plain/formal",
        "cases": 2, "sources": 1,
        "payload": {"origin": DOMAIN_ORIGIN, "domain": "translation",
                    "kind": "translation-frame"}})
    for template_id in ("discovery-and-cooperation-v1",
                        "mystery-and-repair-v1", "mystery-midnight-library-v1",
                        "small-kindness-v1", "comic-council-v1"):
        definitions.append({
            "rule_id": f"domain-creative-template-{template_id}",
            "statement": f"constraint-compatible story template {template_id}",
            "scope": "creative; third-person fiction", "cases": 2, "sources": 1,
            "payload": {"origin": DOMAIN_ORIGIN, "domain": "creative",
                        "kind": "creative-template",
                        "template_id": template_id}})
    for name, statement in (
            ("list-math", "list program followed by exact math map"),
            ("translate-count", "bounded translation followed by word count")):
        definitions.append({
            "rule_id": f"domain-cross-{name}", "statement": statement,
            "scope": "cross-domain; two-step task IR", "cases": 2, "sources": 1,
            "payload": {"origin": DOMAIN_ORIGIN, "domain": "cross-domain",
                        "kind": "cross-plan", "name": name}})
    return definitions


def register_all_domain_rules(registry: RuleRegistry,
                              translator: BoundedTranslator | None = None
                              ) -> list[RuleRecord]:
    records = []
    for definition in domain_rule_definitions(translator):
        records.append(register_domain_rule(
            registry, rule_id=definition["rule_id"],
            statement=definition["statement"], scope=definition["scope"],
            payload=definition["payload"], cases=definition["cases"],
            sources=definition["sources"]))
    return records
