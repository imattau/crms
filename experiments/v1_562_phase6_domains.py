"""Phase 6 contract: five domain slices, independent checks, repair, registry."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_domains import (  # noqa: E402
    BoundedTranslator, CodeDomain, CodeOp, CodeProgram, CreativeBrief,
    CreativeDomain, CrossDomain, MathDomain, compile_code_program,
    register_all_domain_rules, static_check_code,
)
from crms_math import CRMSMath  # noqa: E402
from crms_phase6_benchmark import evaluate  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def module_contracts() -> None:
    math_model = CRMSMath()
    math_model.teach_unit_equivalence("1000 metres|1 kilometre")
    math_model.teach_unit_equivalence("2000 metres|2 kilometres")
    math = MathDomain(math_model)
    word = math.solve("Marta has 12 marbles. She gives away 5 marbles. "
                      "How many marbles does she have left?")
    require(word.answered and str(word.value) == "7",
            "math word problem did not reduce to an exact operation")
    inequality = math.solve("Solve -2x + 4 >= 10 for x.")
    require(inequality.answered
            and inequality.value == {"boundary": "-3", "operator": "<="},
            f"linear inequality failed: {inequality.to_dict()}")
    system = math.solve("Solve 2x + y = 5 and x - y = 1 for x and y.")
    require(system.answered and system.value == {"x": "2", "y": "1"},
            f"2x2 system failed: {system.to_dict()}")
    require(not math.solve("Solve x^2 = 4 for x.").answered,
            "nonlinear equation did not abstain")

    code = CodeDomain()
    program = CodeProgram((CodeOp("reverse"), CodeOp("double")))
    source = compile_code_program(program)
    require(static_check_code(source)["passed"],
            "generated code failed its static contract")
    code_result = code.solve("reverse the list then double each value", [1, 2, 3])
    require(code_result.answered and code_result.value == [6, 4, 2],
            f"sandboxed code result failed: {code_result.to_dict()}")
    require(not code.solve("reverse the list", ["a", "b"]).answered,
            "code input contract did not abstain")
    require(code.repair("compute the median", [4, 2, 9, 1],
                        "sort the list").value == [1, 2, 4, 9],
            "code repair did not close an unsupported operation")

    translator = BoundedTranslator()
    translated = translator.translate_sentence(
        "the red houses are in the small gardens")
    require(translated.answered
            and translated.text == "las casas rojas están en los jardines pequeños",
            f"translation agreement failed: {translated.to_dict()}")
    formal = translator.translate_sentence(
        "the red house is in the small garden", register="formal")
    require(formal.answered
            and formal.text == "la casa roja se encuentra en el jardín pequeño",
            "formal register translation failed")
    unknown = translator.translate_sentence(
        "the red lamp is in the old house")
    require(not unknown.answered, "unknown translation noun did not abstain")
    repaired = translator.repair_unknown(
        unknown, gender="f", singular="lámpara", plural="lámparas",
        sentence="the red lamp is in the old house")
    require(repaired.answered
            and repaired.text == "la lámpara roja está en la casa vieja",
            "translation repair did not learn the missing noun")

    creative = CreativeDomain()
    brief = CreativeBrief("a village bridge", must_include=("lantern",),
                          must_avoid=("dragon",), max_words=180)
    story = creative.compose(brief)
    require(story.answered and story.value["rubric"]["passed"],
            f"creative constraints failed: {story.to_dict()}")
    conflict = CreativeBrief("a village bridge", must_include=("lantern",),
                             must_avoid=("lantern",), max_words=180)
    require(not creative.compose(conflict).answered,
            "contradictory creative constraints did not abstain")
    require(creative.repair(conflict, remove_avoid="lantern").answered,
            "creative repair did not resolve the contradiction")

    cross = CrossDomain(translator)
    list_math = cross.run_list_math(
        "reverse then double", CodeProgram((CodeOp("reverse"),)), [1, 2, 3],
        math_op="double")
    require(list_math.answered and list_math.output == [6, 4, 2]
            and len(list_math.plan["steps"]) == 2,
            f"cross-domain list/math failed: {list_math}")
    translate_count = cross.run_translate_count(
        "translate then count", "the red house is in the small garden")
    require(translate_count.answered and translate_count.output == 8,
            f"cross-domain translate/count failed: {translate_count}")

    registry = RuleRegistry()
    translator = BoundedTranslator(registry=registry)
    records = register_all_domain_rules(registry, translator)
    require(len(records) >= 46 and all(record.state == "active"
                                       for record in records),
            "domain rules did not all activate")
    code = CodeDomain(registry=registry)
    require(code.solve("reverse the list", [1, 2, 3]).answered,
            "registered code operation is not executable")
    registry.retire("domain-code-op-reverse", reason="test")
    require(not code.solve("reverse the list", [1, 2, 3]).answered,
            "retired domain operation still runs")
    registry.rollback("domain-code-op-reverse")
    require(code.solve("reverse the list", [1, 2, 3]).answered,
            "domain operation rollback failed")


def main() -> None:
    module_contracts()
    report = evaluate()
    require(report["gate_passed"], f"Phase 6 gate failed: {report['gate']}")
    require(report["overall"]["tasks"] == 90
            and report["overall"]["correct"] == 90,
            f"unexpected Phase 6 total: {report['overall']}")
    require(report["overall"]["confident_errors"] == 0,
            "Phase 6 produced a confident wrong output")
    expected = {"math": 20, "coding": 20, "translation": 20,
                "creative": 20, "cross-domain": 10}
    for name, count in expected.items():
        row = report["slices"][name]
        require(row["correct"] == count and row["confident_errors"] == 0,
                f"{name} slice failed: {row}")
        require(row["negative_abstained"] == row["negative_total"],
                f"{name} negative control answered")
        require(row["repair_passed"], f"{name} repair was not demonstrated")
        require(row["provenance_present"] == row["correct"],
                f"{name} answer lacks provenance")
    require(report["registry"]["all_validated"]
            and report["registry"]["retired_abstained"]
            and report["registry"]["rollback_restored"],
            "domain registry lifecycle failed")
    print("math word problems, inequalities, and 2x2 systems: PASS")
    print("typed code IR, static checks, sandbox, and repair: PASS")
    print("translation agreement, register, roles, and repair: PASS")
    print("creative constraint planner, rubric, and repair: PASS")
    print("two-stage cross-domain plans through the task IR: PASS")
    print("90/90 held-out tasks, zero confident errors, provenance: PASS")
    print("domain rule registration, retirement, and rollback: PASS")
    print("Phase 6 gate: PASS")


if __name__ == "__main__":
    main()
