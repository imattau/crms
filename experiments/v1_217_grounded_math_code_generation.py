"""Check standalone code generation from CRMS's learned exact math grammar."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import hashlib
import json
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_codegen import (
    generate_math_python, generate_unit_conversion_python,
)
from crms_math import CRMSMath

PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    math = CRMSMath()
    math.teach("What is 2 glorp 3?", "5")
    licensed = math.teach("What is 5 glorp 3?", "8")
    require(licensed.status == "licensed",
            "two exact examples did not license the operator phrase")

    generated = generate_math_python(math, "x glorp y")
    require(generated is not None and generated.domain == "math",
            "learned math expression did not generate a typed code artifact")
    namespace: dict[str, object] = {}
    exec(compile(generated.source, "<crms-generated-math>", "exec"), namespace)
    compute = namespace["compute"]
    require(compute(-2, 3) == 1 and compute(8, -5) == 3,
            "generated function disagreed with the learned exact operator")
    require(namespace["validate_examples"](),
            "generated math artifact failed its scalar parity checks")
    for operands, expected in (
            ((1 << 4096, 1), "input"),
            ((1 << 4095, 1 << 4095), "result")):
        try:
            compute(*operands)
        except OverflowError:
            pass
        else:
            raise SystemExit(f"generated math function did not bound its {expected}")
    provenance = namespace["CRMS_PROVENANCE"]
    require(provenance["learned_phrases"] == ["glorp"]
            and len(provenance["operator_examples"]) == 2
            and provenance["expression_tree"]["operation"] == "add",
            "generated math provenance omitted learned phrase or aligned examples")
    require("import crms_math" not in generated.source
            and "def compute(x, y)" in generated.source,
            "generated math artifact is not standalone or has the wrong contract")
    require(generate_math_python(math, "x blarg y") is None,
            "code was generated for an unlearned operator phrase")

    symbolic = generate_math_python(CRMSMath(), "x + y")
    require(symbolic is not None,
            "standard exact math notation was rejected by code generation")
    symbolic_namespace: dict[str, object] = {}
    exec(compile(symbolic.source, "<crms-generated-symbolic-math>", "exec"),
         symbolic_namespace)
    symbolic_provenance = symbolic_namespace["CRMS_PROVENANCE"]
    require(symbolic_namespace["compute"](7, -2) == 5
            and symbolic_namespace["validate_examples"]()
            and symbolic_provenance["learned_phrases"] == []
            and symbolic_provenance["standard_operators"] == [
                {"notation": "+", "operation": "add"}],
            "symbolic math code lost exact behavior or misreported provenance")

    implicit = generate_math_python(CRMSMath(), "2x")
    require(implicit is not None,
            "implicit algebraic multiplication was rejected by code generation")
    implicit_namespace: dict[str, object] = {}
    exec(compile(implicit.source, "<crms-generated-implicit-math>", "exec"),
         implicit_namespace)
    require(implicit_namespace["compute"](9) == 18
            and implicit_namespace["validate_examples"]()
            and implicit_namespace["CRMS_PROVENANCE"][
                "uses_implicit_multiplication"],
            "implicit multiplication code lost behavior or provenance")

    decimal_code = generate_math_python(CRMSMath(), "x * 0.1")
    require(decimal_code is not None,
            "an exact decimal literal was rejected by math code generation")
    decimal_namespace: dict[str, object] = {}
    exec(compile(decimal_code.source, "<crms-generated-decimal-math>", "exec"),
         decimal_namespace)
    decimal_literal = decimal_namespace["CRMS_PROVENANCE"]["expression_tree"]["right"]
    require(decimal_namespace["compute"](3) == Fraction(3, 10)
            and decimal_namespace["validate_examples"]()
            and decimal_literal == {"kind": "literal", "numerator": 1,
                                    "denominator": 10},
            "decimal code was not exact or its rational provenance was lost")

    composed = CRMSMath()
    composed.teach("What is 2 glorp 3?", "5")
    composed.teach("What is 5 glorp 3?", "8")
    composed.teach("What is 2 flarn 3?", "6")
    composed.teach("What is 4 flarn 3?", "12")
    composed_code = generate_math_python(composed, "x glorp y flarn z")
    require(composed_code is not None,
            "composed learned operators did not produce code")
    composed_namespace: dict[str, object] = {}
    exec(compile(composed_code.source, "<crms-generated-composition>", "exec"),
         composed_namespace)
    require(composed_namespace["compute"](2, 3, 4) == 14
            and composed_namespace["validate_examples"](),
            "generated code did not preserve learned math precedence")
    mixed = generate_math_python(composed, "x + y glorp z")
    require(mixed is not None,
            "standard symbols and learned operators did not combine in codegen")
    mixed_namespace: dict[str, object] = {}
    exec(compile(mixed.source, "<crms-generated-mixed-math>", "exec"),
         mixed_namespace)
    mixed_provenance = mixed_namespace["CRMS_PROVENANCE"]
    require(mixed_namespace["compute"](1, 2, 3) == 6
            and mixed_namespace["validate_examples"]()
            and mixed_provenance["learned_phrases"] == ["glorp"]
            and mixed_provenance["standard_operators"] == [
                {"notation": "+", "operation": "add"}]
            and len(mixed_provenance["operator_examples"]) == 2,
            "mixed notation code lost behavior or conflated operator provenance")

    division = CRMSMath()
    division.teach("What is 6 over 2?", "3")
    division.teach("What is 5 over 2?", "5/2")
    exact = generate_math_python(division, "x over y")
    require(exact is not None,
            "licensed rational division did not generate standalone code")
    exact_namespace: dict[str, object] = {}
    exec(compile(exact.source, "<crms-generated-division>", "exec"),
         exact_namespace)
    require(exact_namespace["compute"](5, 2) == Fraction(5, 2)
            and exact_namespace["compute"](9, 3) == 3,
            "generated division did not preserve exact rational results")

    remainder = CRMSMath()
    remainder.teach("What is 17 remainder 5?", "2")
    licensed_remainder = remainder.teach("What is 13 remainder 5?", "3")
    require(licensed_remainder.status == "licensed"
            and licensed_remainder.operation == "modulo",
            "remainder examples did not license the exact modulo operation")
    learned_remainder = generate_math_python(remainder, "x remainder y")
    standard_remainder = generate_math_python(CRMSMath(), "x % y")
    require(learned_remainder is not None and standard_remainder is not None,
            "learned or standard modulo expression did not generate code")
    for artifact, source in ((learned_remainder, "learned"),
                             (standard_remainder, "standard")):
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, f"<crms-{source}-remainder>", "exec"),
             namespace)
        compute = namespace["compute"]
        require(compute(-7, 3) == 2 and compute(7, -3) == -2
                and namespace["validate_examples"](),
                f"{source} remainder code lost exact negative-operand semantics")
        try:
            compute(7, 0)
        except ZeroDivisionError:
            pass
        else:
            raise SystemExit(f"{source} remainder code hid its zero divisor")
    units = CRMSMath()
    units.teach_unit_equivalence("2 meters|200 centimeters")
    licensed_units = units.teach_unit_equivalence("5 meters|500 centimeters")
    require(licensed_units.status == "licensed",
            "two aligned quantities did not license the conversion ratio")
    conversion = generate_unit_conversion_python(
        units, "convert x meters to centimeters")
    require(conversion is not None and conversion.domain == "unit",
            "learned unit ratio did not produce a code artifact")
    conversion_namespace: dict[str, object] = {}
    exec(compile(conversion.source, "<crms-generated-unit>", "exec"),
         conversion_namespace)
    require(conversion_namespace["convert_amount"](3) == 300
            and conversion_namespace["convert_amount"](-2) == -200
            and conversion_namespace["validate_examples"](),
            "generated unit function disagreed with its exact learned ratio")
    provenance = conversion_namespace["CRMS_PROVENANCE"]
    recorded_id = provenance.pop("artifact_id")
    recomputed_id = "crms-code-v1-" + hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    require(recorded_id == conversion.provenance_id == recomputed_id
            and len(provenance["aligned_examples"]) == 2
            and provenance["evidence_path"] == ["meter", "centimeter"]
            and "import crms_math" not in conversion.source,
            "unit code provenance id, evidence lineage, or standalone contract failed")
    general_conversion = generate_unit_conversion_python(
        units, "convert the quantity from meters into centimeters")
    require(general_conversion is not None
            and general_conversion.procedure[0]["variable"] == "amount",
            "natural amount-from/to unit wording was not resolved")
    try:
        conversion_namespace["convert_amount"](1 << 4096)
    except OverflowError:
        pass
    else:
        raise SystemExit("generated conversion did not enforce CRMS's arithmetic bound")
    try:
        conversion_namespace["convert_amount"](1 << 4095)
    except OverflowError:
        pass
    else:
        raise SystemExit("generated conversion did not bound its exact output")
    require(generate_unit_conversion_python(
        units, "convert x meters to seconds") is None,
        "code was generated for units without a learned conversion path")

    chained_units = CRMSMath()
    for example in ("2 meters|200 centimeters", "5 meters|500 centimeters",
                    "1 centimeter|10 millimeters",
                    "3 centimeters|30 millimeters"):
        chained_units.teach_unit_equivalence(example)
    chained = generate_unit_conversion_python(
        chained_units, "convert x meters to millimeters")
    require(chained is not None,
            "transitive learned unit path did not produce code")
    chained_namespace: dict[str, object] = {}
    exec(compile(chained.source, "<crms-generated-unit-chain>", "exec"),
         chained_namespace)
    chained_provenance = chained_namespace["CRMS_PROVENANCE"]
    require(chained_namespace["convert_amount"](2) == 2000
            and chained_namespace["validate_examples"]()
            and chained_provenance["evidence_path"]
            == ["meter", "centimeter", "millimeter"]
            and len(chained_provenance["aligned_examples"]) == 4,
            "transitive conversion lost exact scale or edge provenance")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        math.teach_unit_equivalence("2 meters|200 centimeters")
        math.teach_unit_equivalence("5 meters|500 centimeters")
        math.save(root / "math.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--math", str(root / "math.json"),
            "--rules", str(root / "rules.json"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
        ]
        response = subprocess.run(
            command,
            input=("Write Python code to compute x glorp y\n"
                   "Explain that code\n"
                   "Show the examples for that code\n"
                   "Write Python code to convert x meters to centimeters\n"
                   "Write Python code to convert the amount from meters into centimeters\n"
                   "What examples support that code?\n"
                   "What does it do?\n"
                   "Write Python code to compute x + y\n"
                   "/quit\n"),
            text=True, capture_output=True, check=True, timeout=30).stdout
        require("Generated exact-arithmetic Python" in response
                and "def compute(x, y)" in response
                and "Generated exact Python conversion" in response
                and "def convert_amount(amount: int)" in response
                and "learned phrase 'glorp'" in response
                and "'2 glorp 3' -> 5" in response
                and "2 meters|200 centimeters" in response
                and "learned exact ratio 100/1" in response
                and "standard arithmetic notation without learned word operators" in response
                and "glorp" in response,
                f"ordinary-language code request missed learned math: {response}")

        conversational_math_path = root / "conversational-math.json"
        conversational_command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--math", str(conversational_math_path),
            "--rules", str(root / "conversation-rules.json"),
            "--knowledge", str(root / "conversation-knowledge.json"),
            "--index", str(root / "conversation-index.json"),
            "--dialogue-state", str(root / "conversation-dialogue.json"),
        ]
        conversational_response = subprocess.run(
            conversational_command,
            input=("Teach unit conversions from examples: "
                   '"2 meters" -> "200 centimeters"; '
                   '"5 meters" -> "500 centimeters"\n'
                   "Write Python code to convert x meters to centimeters\n"
                   "Convert 3 meters to centimeters.\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30).stdout
        require("Unit conversion batch stored; licensed ratio(s):" in conversational_response
                and "Generated exact Python conversion" in conversational_response
                and "300" in conversational_response,
                "natural-language unit teaching did not feed conversion and code routes: "
                f"{conversational_response}")
        conversational_restored = CRMSMath.load(conversational_math_path)
        conversational_answer = conversational_restored.convert_unit(
            "Convert 3 meters to centimeters.")
        require(conversational_answer is not None
                and conversational_answer.status == "answered"
                and conversational_answer.value == 300,
                "conversational unit teaching did not persist a usable exact ratio")

        rejected_path = root / "rejected-unit-batch.json"
        rejected_command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--math", str(rejected_path),
            "--rules", str(root / "rejected-rules.json"),
            "--knowledge", str(root / "rejected-knowledge.json"),
            "--index", str(root / "rejected-index.json"),
            "--dialogue-state", str(root / "rejected-dialogue.json"),
        ]
        rejected_response = subprocess.run(
            rejected_command,
            input=("Teach unit conversions from examples: "
                   '"2 meters" -> "200 centimeters"; '
                   '"5 meters" -> "400 centimeters"\n/quit\n'),
            text=True, capture_output=True, check=True, timeout=30).stdout
        require("Could not teach unit conversion examples" in rejected_response
                and not rejected_path.exists(),
                "a conflicting conversational batch partially committed")

    print("grounded math code-generation diagnostic: PASS")
    print("learned-operator code rendering, exact rational division, "
          "direct and transitive unit conversion, arithmetic bounds, "
          "standalone provenance, "
          "unsupported-operation abstention, and evidence-based code follow-up: PASS")


if __name__ == "__main__":
    main()
