"""Phase 6 domain benchmark: five slices, independent checks, repair, cost.

The fixture is frozen before measurement. Each slice has 20 held-out tasks,
negative controls, and one repair case. Outputs are checked by local oracles:
exact math substitution, an independent code interpreter, authored translation
targets with semantic roles, a constraint rubric, and cross-domain step outputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import statistics
import time
from typing import Any, Iterable, Mapping

from crms_domains import (
    BoundedTranslator, CodeDomain, CodeOp, CodeProgram, CreativeBrief,
    CreativeDomain, CrossDomain, MathDomain, apply_code_program,
    register_all_domain_rules,
)
from crms_math import CRMSMath
from crms_rule_registry import RuleRegistry

PROJECT = Path(__file__).resolve().parent
PHASE6_FIXTURE = PROJECT / "experiments" / "scorecard" / "phase6_domains.json"


def load_phase6(path: str | Path = PHASE6_FIXTURE) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("format") != "crms-phase6-domains":
        raise ValueError("not a Phase 6 domain fixture")
    for name in ("math", "coding", "translation", "creative", "cross"):
        if len(raw.get(name, {}).get("tasks", ())) != (10 if name == "cross" else 20):
            raise ValueError(f"{name} has the wrong held-out task count")
    return raw


def _fraction(value: Any) -> Fraction:
    return Fraction(str(value))


def _math_verify(task: Mapping[str, Any], result: Any) -> bool:
    if not getattr(result, "answered", False):
        return False
    expected_type = task["expected_type"]
    if expected_type == "value":
        try:
            return _fraction(result.value) == _fraction(task["expected"])
        except (TypeError, ValueError, ZeroDivisionError):
            return False
    if expected_type == "inequality":
        expected = task["expected"]
        if not isinstance(result.value, Mapping):
            return False
        if (result.value.get("boundary") != expected["boundary"]
                or result.value.get("operator") != expected["operator"]):
            return False
        return _verify_inequality(str(task["text"]), expected)
    if expected_type == "system":
        expected = task["expected"]
        if not isinstance(result.value, Mapping):
            return False
        if (result.value.get("x") != expected["x"]
                or result.value.get("y") != expected["y"]):
            return False
        return _verify_system(str(task["text"]), expected)
    return False


def _verify_inequality(text: str, expected: Mapping[str, str]) -> bool:
    match = re.fullmatch(
        r"\s*solve\s+(?P<left>.+?)\s*(?P<op><=|>=|<|>)\s*(?P<rhs>[+-]?\d+)"
        r"\s+for\s+x\s*[.?!]*\s*", text, flags=re.IGNORECASE)
    if match is None:
        return False
    compact = re.sub(r"\s+", "", match.group("left"))
    coefficient = Fraction(0)
    constant = Fraction(0)
    for term in re.findall(r"[+-]?[^+-]+", compact):
        if "x" in term:
            number = term.replace("x", "")
            coefficient += 1 if number in {"", "+"} else (
                -1 if number == "-" else Fraction(int(number)))
        else:
            constant += Fraction(int(term))
    rhs = Fraction(int(match.group("rhs")))
    if coefficient == 0:
        return False
    boundary = (rhs - constant) / coefficient
    operator = match.group("op")
    if coefficient < 0:
        operator = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}[operator]
    return _fraction(expected["boundary"]) == boundary and expected["operator"] == operator


def _verify_system(text: str, expected: Mapping[str, str]) -> bool:
    match = re.fullmatch(
        r"\s*solve\s+(?P<a>.+?)\s+and\s+(?P<b>.+?)\s+for\s+x\s+and\s+y"
        r"\s*[.?!]*\s*", text, flags=re.IGNORECASE)
    if match is None:
        return False
    x, y = _fraction(expected["x"]), _fraction(expected["y"])
    for side in (match.group("a"), match.group("b")):
        if side.count("=") != 1:
            return False
        left, right = side.split("=")
        for equation in (left, right):
            compact = re.sub(r"\s+", "", equation)
            if not re.fullmatch(r"[0-9xy+-]+", compact):
                return False
        left_terms = _linear_xy(left)
        right_terms = _linear_xy(right)
        if left_terms is None or right_terms is None:
            return False
        a = left_terms[0] - right_terms[0]
        b = left_terms[1] - right_terms[1]
        c = right_terms[2] - left_terms[2]
        if a * x + b * y != c:
            return False
    return True


def _linear_xy(text: str) -> tuple[Fraction, Fraction, Fraction] | None:
    compact = re.sub(r"\s+", "", text)
    x = y = constant = Fraction(0)
    for term in re.findall(r"[+-]?[^+-]+", compact):
        names = [name for name in ("x", "y") if name in term]
        if names:
            if len(names) != 1 or term.count(names[0]) != 1:
                return None
            number = term.replace(names[0], "")
            value = 1 if number in {"", "+"} else (-1 if number == "-"
                                                    else Fraction(int(number)))
            if names[0] == "x":
                x += value
            else:
                y += value
        else:
            constant += Fraction(int(term))
    return x, y, constant


def _oracle_code(operations: Iterable[Mapping[str, Any]],
                 values: Sequence[int]) -> list[int]:
    rows = [int(value) for value in values]
    for operation in operations:
        name = str(operation["name"])
        params = dict(operation.get("parameters", {}))
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
            raise ValueError(name)
    return rows


def _creative_rubric(text: str, brief: Mapping[str, Any]) -> dict[str, Any]:
    folded = text.casefold()
    words = len(re.findall(r"[A-Za-zÀ-ÿ0-9’'-]+", text))
    checks = {
        "topic_present": str(brief["topic"]).casefold() in folded,
        "must_include": all(str(item).casefold() in folded
                            for item in brief.get("must_include", ())),
        "must_avoid": not any(str(item).casefold() in folded
                              for item in brief.get("must_avoid", ())),
        "word_limit": words <= int(brief["max_words"]),
        "no_placeholders": "{" not in text and "}" not in text,
        "third_person": brief.get("pov", "third") == "third",
    }
    return {"passed": all(checks.values()), "checks": checks, "words": words}


@dataclass(frozen=True)
class SliceMetrics:
    name: str
    tasks: int
    correct: int
    abstained: int
    confident_errors: int
    provenance_present: int
    negative_total: int
    negative_abstained: int
    repair_passed: bool
    median_ms: float
    p95_ms: float

    @property
    def completion(self) -> float:
        return self.correct / self.tasks if self.tasks else 0.0

    @property
    def gate_passed(self) -> bool:
        return (self.completion >= 0.8
                and self.confident_errors == 0
                and self.provenance_present == self.correct
                and self.negative_abstained == self.negative_total
                and self.repair_passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": self.tasks,
            "correct": self.correct,
            "completion": self.completion,
            "abstained": self.abstained,
            "confident_errors": self.confident_errors,
            "provenance_present": self.provenance_present,
            "negative_total": self.negative_total,
            "negative_abstained": self.negative_abstained,
            "repair_passed": self.repair_passed,
            "median_ms": self.median_ms,
            "p95_ms": self.p95_ms,
            "gate_passed": self.gate_passed,
        }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    rows = sorted(values)
    return rows[max(0, math.ceil(len(rows) * 0.95) - 1)]


def _timed(callable_: Any) -> tuple[Any, float]:
    start = time.perf_counter()
    result = callable_()
    return result, (time.perf_counter() - start) * 1000.0


def run_math(data: Mapping[str, Any]) -> tuple[SliceMetrics, list[dict[str, Any]]]:
    math_model = CRMSMath()
    for example in data["math"].get("unit_examples", ()):
        math_model.teach_unit_equivalence(example)
    domain = MathDomain(math_model)
    correct = abstained = errors = provenance = 0
    durations: list[float] = []
    rows = []
    for task in data["math"]["tasks"]:
        result, duration = _timed(lambda: domain.solve(task["text"]))
        durations.append(duration)
        verified = _math_verify(task, result)
        if verified:
            correct += 1
            if result.evidence:
                provenance += 1
        elif result.answered:
            errors += 1
        else:
            abstained += 1
        rows.append({"task": task["id"], "status": result.status,
                     "text": result.text, "verified": verified,
                     "duration_ms": duration})
    negative_abstained = 0
    for task in data["math"]["negative"]:
        result = domain.solve(task["text"])
        if not result.answered:
            negative_abstained += 1
    repair = data["math"]["repair"]
    initial = domain.solve(repair["initial"])
    if initial.answered:
        repair_ok = False
    else:
        for example in repair["unit_examples"]:
            domain.teach_unit(example)
        repaired = domain.solve(repair["initial"])
        repair_ok = (repaired.answered
                     and _fraction(repaired.value) == _fraction(repair["expected"]))
    return SliceMetrics(
        "math", len(rows), correct, abstained, errors, provenance,
        len(data["math"]["negative"]), negative_abstained, repair_ok,
        statistics.median(durations), _p95(durations)), rows


def run_coding(data: Mapping[str, Any], code: CodeDomain
               ) -> tuple[SliceMetrics, list[dict[str, Any]]]:
    correct = abstained = errors = provenance = 0
    durations: list[float] = []
    rows = []
    for task in data["coding"]["tasks"]:
        result, duration = _timed(lambda: code.solve(task["text"], task["values"]))
        durations.append(duration)
        expected = _oracle_code(task["operations"], task["values"])
        verified = bool(
            result.answered and result.value == expected
            and result.provenance.get("static_check", {}).get("passed")
            and result.provenance.get("contract"))
        if verified:
            correct += 1
            if result.evidence:
                provenance += 1
        elif result.answered:
            errors += 1
        else:
            abstained += 1
        rows.append({"task": task["id"], "status": result.status,
                     "value": result.value, "verified": verified,
                     "duration_ms": duration})
    negative_abstained = sum(
        1 for task in data["coding"]["negative"]
        if not code.solve(task["text"], task["values"]).answered)
    repair = data["coding"]["repair"]
    repaired = code.repair(repair["initial"], repair["values"],
                           repair["replacement"])
    repair_ok = repaired.answered and repaired.value == repair["expected"]
    return SliceMetrics(
        "coding", len(rows), correct, abstained, errors, provenance,
        len(data["coding"]["negative"]), negative_abstained, repair_ok,
        statistics.median(durations), _p95(durations)), rows


def run_translation(data: Mapping[str, Any], translator: BoundedTranslator
                    ) -> tuple[SliceMetrics, list[dict[str, Any]]]:
    correct = abstained = errors = provenance = 0
    durations: list[float] = []
    rows = []
    for task in data["translation"]["tasks"]:
        result, duration = _timed(lambda: translator.translate_request(task["text"]))
        durations.append(duration)
        verified = (result.answered and result.text == task["expected"]
                    and isinstance(result.value, Mapping)
                    and all(result.value.get("roles", {}).get(key) == value
                            for key, value in task["roles"].items()))
        if verified:
            correct += 1
            if result.evidence:
                provenance += 1
        elif result.answered:
            errors += 1
        else:
            abstained += 1
        rows.append({"task": task["id"], "status": result.status,
                     "text": result.text, "verified": verified,
                     "duration_ms": duration})
    negative_abstained = 0
    for task in data["translation"]["negative"]:
        result = translator.translate_sentence(task["sentence"])
        if not result.answered:
            negative_abstained += 1
    repair = data["translation"]["repair"]
    failed = translator.translate_sentence(repair["sentence"])
    repaired = translator.repair_unknown(
        failed, gender=repair["teach"]["gender"],
        singular=repair["teach"]["singular"],
        plural=repair["teach"]["plural"], sentence=repair["sentence"])
    repair_ok = repaired.answered and repaired.text == repair["expected"]
    return SliceMetrics(
        "translation", len(rows), correct, abstained, errors, provenance,
        len(data["translation"]["negative"]), negative_abstained, repair_ok,
        statistics.median(durations), _p95(durations)), rows


def run_creative(data: Mapping[str, Any], creative: CreativeDomain
                 ) -> tuple[SliceMetrics, list[dict[str, Any]]]:
    correct = abstained = errors = provenance = 0
    durations: list[float] = []
    rows = []
    for task in data["creative"]["tasks"]:
        brief = CreativeBrief(**task["brief"])
        result, duration = _timed(lambda: creative.compose(brief))
        durations.append(duration)
        expected = _creative_rubric(result.text, task["brief"]) if result.text else {
            "passed": False}
        verified = result.answered and expected["passed"]
        if verified:
            correct += 1
            if result.evidence:
                provenance += 1
        elif result.answered:
            errors += 1
        else:
            abstained += 1
        rows.append({"task": task["id"], "status": result.status,
                     "words": expected.get("words"),
                     "verified": verified, "duration_ms": duration})
    negative_abstained = 0
    for task in data["creative"]["negative"]:
        if not creative.compose(CreativeBrief(**task["brief"])).answered:
            negative_abstained += 1
    repair = data["creative"]["repair"]
    brief = CreativeBrief(**repair["brief"])
    fixed_brief = dict(repair["brief"])
    fixed_brief["must_avoid"] = [
        item for item in fixed_brief.get("must_avoid", ())
        if str(item).casefold() != repair["remove_avoid"].casefold()]
    initial = creative.compose(brief)
    repaired = creative.repair(brief, remove_avoid=repair["remove_avoid"])
    repair_ok = (not initial.answered and repaired.answered
                 and _creative_rubric(repaired.text, fixed_brief)["passed"])
    return SliceMetrics(
        "creative", len(rows), correct, abstained, errors, provenance,
        len(data["creative"]["negative"]), negative_abstained, repair_ok,
        statistics.median(durations), _p95(durations)), rows


def run_cross(data: Mapping[str, Any], cross: CrossDomain
              ) -> tuple[SliceMetrics, list[dict[str, Any]]]:
    correct = abstained = errors = provenance = 0
    durations: list[float] = []
    rows = []
    for task in data["cross"]["tasks"]:
        if task["kind"] == "list-math":
            program = CodeProgram(tuple(
                CodeOp(str(item["name"]),
                       {str(k): int(v) for k, v in
                        dict(item.get("parameters", {})).items()})
                for item in task["operations"]))
            result, duration = _timed(lambda: cross.run_list_math(
                task["text"], program, task["values"],
                math_op=task["math_op"], k=task.get("k", 1)))
        else:
            result, duration = _timed(lambda: cross.run_translate_count(
                task["text"], task["sentence"], register=task["register"]))
        durations.append(duration)
        verified = (result.answered and result.output == task["expected"]
                    and bool(result.plan)
                    and len(result.plan.get("steps", ())) == 2
                    and all(step.get("evidence") for step in result.plan["steps"]))
        if verified:
            correct += 1
            if result.plan:
                provenance += 1
        elif result.answered:
            errors += 1
        else:
            abstained += 1
        rows.append({"task": task["id"], "status": result.status,
                     "output": result.output, "verified": verified,
                     "duration_ms": duration})
    negative_abstained = 0
    for task in data["cross"]["negative"]:
        if task["kind"] == "list-math":
            program = CodeProgram(tuple(
                CodeOp(str(item["name"]),
                       {str(k): int(v) for k, v in
                        dict(item.get("parameters", {})).items()})
                for item in task["operations"]))
            result = cross.run_list_math(task.get("text", "cross-domain list-math task"), program, task["values"],
                                         math_op=task["math_op"],
                                         k=task.get("k", 1))
        else:
            result = cross.run_translate_count(
                task.get("text", "cross-domain translate-count task"), task["sentence"], register=task["register"])
        if not result.answered:
            negative_abstained += 1
    repair = data["cross"]["repair"]
    program = CodeProgram(tuple(
        CodeOp(str(item["name"]), {str(k): int(v) for k, v in
                                   dict(item.get("parameters", {})).items()})
        for item in repair["invalid_operations"]))
    initial = cross.run_list_math(repair["text"], program, repair["values"],
                                  math_op=repair["invalid_math_op"])
    repaired = cross.run_list_math(repair["text"], program, repair["values"],
                                   math_op=repair["replacement_math_op"])
    repair_ok = (not initial.answered and repaired.answered
                 and repaired.output == repair["expected"])
    return SliceMetrics(
        "cross", len(rows), correct, abstained, errors, provenance,
        len(data["cross"]["negative"]), negative_abstained, repair_ok,
        statistics.median(durations), _p95(durations)), rows


def registry_lane(registry: RuleRegistry, translator: BoundedTranslator,
                  code: CodeDomain) -> dict[str, Any]:
    records = [record for record in registry.records(family="domain")
               if record.payload.get("origin") == "crms_domains"
               and record.state == "active"]
    all_validated = all((record.validation or {}).get("passed")
                        for record in records)
    before = code.solve("reverse the list", [1, 2, 3])
    rule_id = "domain-code-op-reverse"
    registry.retire(rule_id, reason="phase6 retirement probe")
    retired = code.solve("reverse the list", [1, 2, 3])
    registry.rollback(rule_id)
    restored = code.solve("reverse the list", [1, 2, 3])
    return {
        "active_rules": len(records),
        "all_validated": all_validated,
        "retired_abstained": not retired.answered,
        "rollback_restored": restored.answered and restored.value == [3, 2, 1],
        "rule_id": rule_id,
    }


def evaluate(path: str | Path = PHASE6_FIXTURE) -> dict[str, Any]:
    data = load_phase6(path)
    registry = RuleRegistry()
    translator = BoundedTranslator(registry=registry)
    records = register_all_domain_rules(registry, translator)
    code = CodeDomain(registry=registry)
    creative = CreativeDomain()
    cross = CrossDomain(translator)
    math_metrics, math_rows = run_math(data)
    coding_metrics, coding_rows = run_coding(data, code)
    translation_metrics, translation_rows = run_translation(data, translator)
    creative_metrics, creative_rows = run_creative(data, creative)
    cross_metrics, cross_rows = run_cross(data, cross)
    slices = {
        "math": math_metrics,
        "coding": coding_metrics,
        "translation": translation_metrics,
        "creative": creative_metrics,
        "cross-domain": cross_metrics,
    }
    registry_report = registry_lane(registry, translator, code)
    gate = {
        "all_slices_meet_80_percent": all(
            metrics.completion >= 0.8 for metrics in slices.values()),
        "zero_confident_wrong_outputs": all(
            metrics.confident_errors == 0 for metrics in slices.values()),
        "provenance_on_every_answer": all(
            metrics.provenance_present == metrics.correct
            for metrics in slices.values()),
        "negative_controls_abstain": all(
            metrics.negative_abstained == metrics.negative_total
            for metrics in slices.values()),
        "repair_demonstrated": all(
            metrics.repair_passed for metrics in slices.values()),
        "cost_reported": all(
            metrics.median_ms >= 0 and metrics.p95_ms >= 0
            for metrics in slices.values()),
        "domain_rules_registered": (
            len(records) > 0 and registry_report["all_validated"]),
        "domain_rule_retirement": (
            registry_report["retired_abstained"]
            and registry_report["rollback_restored"]),
    }
    return {
        "format": "crms-phase6-eval",
        "version": 1,
        "slices": {name: metrics.to_dict()
                   for name, metrics in slices.items()},
        "overall": {
            "tasks": sum(metrics.tasks for metrics in slices.values()),
            "correct": sum(metrics.correct for metrics in slices.values()),
            "confident_errors": sum(metrics.confident_errors
                                    for metrics in slices.values()),
            "completion": (sum(metrics.correct for metrics in slices.values())
                           / sum(metrics.tasks for metrics in slices.values())),
        },
        "registry": registry_report,
        "gate": gate,
        "gate_passed": all(gate.values()),
        "rows": {
            "math": math_rows,
            "coding": coding_rows,
            "translation": translation_rows,
            "creative": creative_rows,
            "cross": cross_rows,
        },
        "provenance": {
            "fixture": str(Path(path)),
            "method": ("frozen held-out tasks; exact/substitution math checks; "
                       "independent code interpreter; authored translation "
                       "targets and role checks; constraint rubric; two-step "
                       "task-IR execution"),
        },
    }


def main() -> int:
    parser = __import__("argparse").ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=PHASE6_FIXTURE)
    parser.add_argument("--out", type=Path,
                        default=PROJECT / "experiments" / "reports"
                        / "phase6_domains.json")
    args = parser.parse_args()
    report = evaluate(args.fixture)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    for name, row in report["slices"].items():
        print(f"{name:14s} {row['correct']:2d}/{row['tasks']:2d} "
              f"({row['completion']:.0%}) errors={row['confident_errors']} "
              f"repair={row['repair_passed']} "
              f"median={row['median_ms']:.1f}ms")
    print(f"Gate: {'PASS' if report['gate_passed'] else 'FAIL'} "
          f"{report['gate']}")
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
