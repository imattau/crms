"""Compose learned list sequences with exact learned elementwise math."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import (
    describe_generated_code, diagnose_list_then_math_support,
    generate_list_then_math_python, render, show_generated_code_evidence,
)
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex


INPUTS = ([3, 1, 2], [4, -1, 7], [0, 5, -2, 8], [-5, 9], [12], [])
CONTRAST = [0, 0]
COMPOUNDS = (
    ("sort the list then reverse the values", "sort", "reverse"),
    ("reverse the list then sort the values", "reverse", "sort"),
)
REQUEST = ("sort the list then reverse the list then apply x times x plus 3 "
           "to each value")
REQUEST_VARIANTS = (
    "sort the list then reverse the list and then apply x times x plus 3 to "
    "each value in the list",
    "After sort the list then reverse the list, map x times x plus 3 over "
    "each value",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def sequence(values: list[int], first: str, second: str) -> list[int]:
    def apply(items: list[int], operation: str) -> list[int]:
        if operation == "sort":
            return sorted(items)
        if operation == "reverse":
            return list(reversed(items))
        if operation == "unique":
            return list(dict.fromkeys(items))
        raise ValueError(f"unknown operation: {operation}")
    return apply(apply(values, first), second)


def trained_rules() -> CRMSModel:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    base = (("sort the list", "sort"), ("reverse the list", "reverse"),
            ("sort the values", "sort"), ("reverse the values", "reverse"),
            ("remove duplicate values", "unique"))
    for phrase, operation in base:
        if operation == "sort":
            outputs = [sorted(values) for values in (*INPUTS, CONTRAST)]
        elif operation == "reverse":
            outputs = [list(reversed(values)) for values in (*INPUTS, CONTRAST)]
        else:
            outputs = [list(dict.fromkeys(values))
                       for values in (*INPUTS, CONTRAST)]
        learned = model.teach(phrase, list(zip((*INPUTS, CONTRAST), outputs)))
        require(learned.status == "learned",
                f"base list operation failed to learn: {phrase}: {learned}")
    for phrase, first, second in COMPOUNDS:
        examples = [(list(values), sequence(list(values), first, second))
                    for values in INPUTS]
        result = model.teach(phrase, examples)
        require(result.status == "need_more_examples"
                and result.contrastive_input == list(CONTRAST),
                f"compound teaching did not request the contrast probe: {result}")
        result = model.teach(
            phrase, [(list(CONTRAST), sequence(list(CONTRAST), first, second))])
        require(result.status == "learned" and result.candidate_count == 1,
                f"contrast did not license one sequence rule: {result}")
    return model


def trained_math() -> CRMSMath:
    model = CRMSMath()
    for question, answer in (
            ("What is 2 times 3?", "6"),
            ("What is 4 times 7?", "28"),
            ("What is 2 plus 3?", "5"),
            ("What is 6 plus 8?", "14"),
            ("What is 2 divided by 2?", "1"),
            ("What is 4 divided by 2?", "2")):
        result = model.teach(question, answer)
        require(result.status in {"needs_more_examples", "licensed"},
                f"math operator failed to learn: {result}")
    return model


def main() -> None:
    rules, math = trained_rules(), trained_math()
    artifact = generate_list_then_math_python(rules, math, REQUEST)
    require(artifact is not None and artifact.domain == "list_math_map",
            "learned list and math stages did not compose")
    namespace: dict[str, object] = {}
    exec(compile(artifact.source, "<crms-cross-domain>", "exec"), namespace)
    require(namespace["transform"]([4, 1, 4, 2]) == [19, 19, 7, 4]
            and namespace["validate_examples"](),
            "standalone cross-domain artifact failed composed behavior checks")
    provenance = namespace["COMPOSITION_PROVENANCE"]
    require(provenance["stage_order"] == [
                "learned_list_procedure", "exact_math_map"]
            and provenance["list_artifact_id"]
                == namespace["LIST_PROVENANCE"]["artifact_id"]
            and provenance["math_map_artifact_id"]
                == namespace["MATH_MAP_PROVENANCE"]["artifact_id"]
            and artifact.validation_cases == 4,
            "composition provenance omitted component lineage or probes")
    repeated = generate_list_then_math_python(rules, math, REQUEST)
    require(repeated is not None
            and repeated.provenance_id == artifact.provenance_id,
            "composed artifact id changed for identical learned state")
    for variant in REQUEST_VARIANTS:
        variant_artifact = generate_list_then_math_python(rules, math, variant)
        require(variant_artifact is not None,
                f"common instruction wording did not resolve: {variant}")
        variant_namespace: dict[str, object] = {}
        exec(compile(variant_artifact.source, "<crms-cross-domain-variant>", "exec"),
             variant_namespace)
        require(variant_namespace["transform"]([4, 1, 4, 2])
                == [19, 19, 7, 4]
                and variant_namespace["validate_examples"](),
                f"wording variant changed supported task semantics: {variant}")
    rational_request = (
        "sort the list then reverse the list then apply x divided by 2 to "
        "each value")
    rational_artifact = generate_list_then_math_python(
        rules, math, rational_request)
    require(rational_artifact is not None,
            "the same learned list sequence did not compose with division")
    rational_namespace: dict[str, object] = {}
    exec(compile(rational_artifact.source, "<crms-cross-domain-rational>", "exec"),
         rational_namespace)
    from fractions import Fraction
    require(rational_namespace["transform"]([4, 1, 4, 2])
            == [Fraction(2), Fraction(2), Fraction(1), Fraction(1, 2)]
            and rational_namespace["validate_examples"]()
            and rational_namespace["COMPOSITION_PROVENANCE"]["math_map_provenance"]
                ["expression_artifact_id"]
                == rational_namespace["MATH_MAP_PROVENANCE"]["expression_artifact_id"],
            "division composition lost exact fractions or math lineage")
    unseen_pair_request = (
        "remove duplicate values then sort the list then apply x divided by 2 "
        "to each value")
    unseen_pair_artifact = generate_list_then_math_python(
        rules, math, unseen_pair_request)
    require(unseen_pair_artifact is not None,
            "learned connective did not compose a new list operation pair "
            "with the math stage")
    unseen_pair_namespace: dict[str, object] = {}
    exec(compile(unseen_pair_artifact.source,
                 "<crms-cross-domain-unseen-pair>", "exec"),
         unseen_pair_namespace)
    require(unseen_pair_namespace["transform"]([4, 1, 4, 2])
            == [Fraction(1, 2), Fraction(1), Fraction(2)]
            and unseen_pair_namespace["validate_examples"]()
            and "remove duplicate values"
                in unseen_pair_artifact.evidence_phrases,
            "unseen list-pair composition returned wrong output or lost evidence")
    unseen_triple_request = (
        "remove duplicate values then sort the list then reverse the list then "
        "apply x times x plus 3 to each value")
    unseen_triple_artifact = generate_list_then_math_python(
        rules, math, unseen_triple_request)
    require(unseen_triple_artifact is not None,
            "three learned list operations did not compose with exact math")
    unseen_triple_namespace: dict[str, object] = {}
    exec(compile(unseen_triple_artifact.source,
                 "<crms-cross-domain-unseen-triple>", "exec"),
         unseen_triple_namespace)
    triple_procedure = unseen_triple_namespace["LIST_PROVENANCE"]["procedure"]
    require(unseen_triple_namespace["transform"]([4, 1, 4, 2]) == [19, 7, 4]
            and unseen_triple_namespace["validate_examples"]()
            and [step["operation"] for step in triple_procedure]
                == ["stable_unique", "sort_ascending", "reverse"]
            and unseen_triple_artifact.validation_cases >= 4,
            "three-stage unseen composition has wrong output, order, or probes")
    unseen_triple_rational = generate_list_then_math_python(
        rules, math,
        "reverse the list then remove duplicate values then sort the list "
        "then apply x divided by 2 to each value")
    require(unseen_triple_rational is not None,
            "a different three-stage sequence did not compose with division")
    rational_triple_namespace: dict[str, object] = {}
    exec(compile(unseen_triple_rational.source,
                 "<crms-cross-domain-rational-triple>", "exec"),
         rational_triple_namespace)
    require(rational_triple_namespace["transform"]([4, 1, 4, 2])
            == [Fraction(1, 2), Fraction(1), Fraction(2)]
            and rational_triple_namespace["validate_examples"]()
            and len(rational_triple_namespace["LIST_PROVENANCE"]["procedure"])
                == 3,
            "three-stage fractional composition lost exact values or validation")
    evidence = show_generated_code_evidence(artifact)
    require("learned list procedure" in describe_generated_code(artifact)
            and "Generated composed Python" in render(artifact, REQUEST)
            and "sort the list then reverse the values" in evidence
            and "2 plus 3" in evidence and "2 times 3" in evidence,
            "explanation or evidence omitted one of the component stages")
    require(generate_list_then_math_python(
                CRMSModel(max_workers=1), math, REQUEST) is None
            and generate_list_then_math_python(
                rules, math, REQUEST.replace("x plus 3", "x zarg 3")) is None,
            "unsupported list or math component did not abstain")
    math_gap = diagnose_list_then_math_support(
        rules, math, REQUEST.replace("x plus 3", "x zarg 3"))
    list_gap = diagnose_list_then_math_support(
        rules, math,
        "rotate the list then apply x times x plus 3 to each value")
    middle_gap = diagnose_list_then_math_support(
        rules, math,
        "sort the list then rotate the list then reverse the list then "
        "apply x times x plus 3 to each value")
    require(math_gap is not None and "list step is supported" in math_gap
            and "math expression" in math_gap
            and list_gap is not None and "first list step" in list_gap
            and generate_list_then_math_python(
                rules, math,
                "sort the list then rotate the list then reverse the list "
                "then apply x times x plus 3 to each value") is None
            and middle_gap is not None and "list step 2" in middle_gap
            and "rotate the list" in middle_gap,
            "composition abstention did not identify its unsupported stage")

    with tempfile.TemporaryDirectory(prefix="crms-cross-domain-chat-") as folder:
        root = Path(folder)
        rules_path, math_path = root / "rules.json", root / "math.json"
        rules.save(rules_path)
        math.save(math_path)
        knowledge_path, index_path = root / "knowledge.json", root / "index.json"
        CRMSKnowledgeBase().save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        paths = {name: root / f"{name}.json" for name in (
            "dialogue", "rule-session", "candidate-session", "translations")}
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(index_path),
            "--dialogue-state", str(paths["dialogue"]),
            "--rules", str(rules_path), "--rule-session", str(paths["rule-session"]),
            "--candidate-session", str(paths["candidate-session"]),
            "--math", str(math_path), "--translations", str(paths["translations"]),
        ]
        run = subprocess.run(
            command,
            input=("Could you please write me a Python function that "
                   f"{REQUEST_VARIANTS[1]}?\nExplain that code\n"
                   "Show the examples for that code\n"
                   "Write Python code to remove duplicate values then sort "
                   "the list then reverse the list then apply x times x plus "
                   "3 to each value\nExplain that code\n"
                   "Write Python code to sort the list then apply x zarg 3 to "
                   "each value\nExplain that code\n"
                   "Write Python code to rotate the list then apply x times x "
                   "plus 3 to each value\n/quit\n"),
            text=True, capture_output=True, cwd=root, check=False, timeout=30)
        require(run.returncode == 0
                and "Generated composed Python" in run.stdout
                and "Both stages" in run.stdout
                and "stable_unique" in run.stdout
                and "reverse" in run.stdout
                and "Evidence for generated artifact crms-code-v1-" in run.stdout
                and "sort the list then reverse the values" in run.stdout
                and "plus" in run.stdout and "times" in run.stdout
                and "The list step is supported, but I couldn't resolve the "
                    "math expression" in run.stdout
                and "There is no recent generated code artifact to explain."
                    in run.stdout
                and "I couldn't resolve the first list step" in run.stdout,
                f"natural-language composed chat flow failed:\n"
                f"{run.stdout}\n{run.stderr}")

    print("cross-domain list→math composition: PASS")
    print("learned sequence transferred to exact math mapping; component and "
          "outer lineage retained: PASS")
    print("standalone output, composed probes, determinism, unsupported-stage "
          "abstention: PASS")
    print("same learned sequence recombined with a second formula; exact "
          "fractional output and lineage: PASS")
    print("learned connective transferred to a new list-operation pair before "
          "exact division: PASS")
    print("three unseen list operations compose in order with exact math and lineage: PASS")
    print("natural-language chat generation, explanation, and evidence: PASS")


if __name__ == "__main__":
    main()
