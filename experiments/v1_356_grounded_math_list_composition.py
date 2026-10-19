"""Compose exact learned math with list code generation through natural chat."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import (
    describe_generated_code, generate_mapped_math_python, generate_math_python,
    render, show_generated_code_evidence,
)
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def trained_math() -> CRMSMath:
    model = CRMSMath()
    for question, answer in (
            ("What is 2 times 3?", "6"),
            ("What is 4 times 7?", "28"),
            ("What is 2 plus 3?", "5"),
            ("What is 6 plus 8?", "14")):
        result = model.teach(question, answer)
        require(result.status in {"needs_more_examples", "licensed"},
                f"math operator learning failed: {question}: {result}")
    return model


def main() -> None:
    model = trained_math()
    request = "apply x times x plus 3 to each value in the list"
    artifact = generate_mapped_math_python(model, request)
    require(artifact is not None and artifact.domain == "math_map",
            "known exact expression did not produce a mapped-math artifact")
    namespace: dict[str, object] = {}
    exec(compile(artifact.source, "<crms-math-list-composition>", "exec"),
         namespace)
    transform = namespace["transform"]
    require(transform([4, 4, 2]) == [19, 19, 7]
            and namespace["validate_examples"](),
            "composed artifact failed held-out or embedded validation")
    scalar = generate_math_python(model, "x times x plus 3")
    require(scalar is not None
            and artifact.evidence_phrases == ("plus", "times")
            and artifact.evidence_examples == 4
            and artifact.validation_cases == 4
            and namespace["CRMS_PROVENANCE"]["schema"]
            == "crms-math-map-code-provenance-v1"
            and namespace["CRMS_PROVENANCE"]["expression_artifact_id"]
            == scalar.provenance_id
            and namespace["CRMS_PROVENANCE"]["scalar_artifact_provenance"]
            ["artifact_id"] == scalar.provenance_id,
            "composition provenance omitted the scalar artifact or learned operators")
    repeated = generate_mapped_math_python(model, request)
    require(repeated is not None
            and repeated.provenance_id == artifact.provenance_id,
            "same learned math composition did not produce a stable artifact ID")
    evidence_text = show_generated_code_evidence(artifact)
    require("learned exact math expression" in describe_generated_code(artifact)
            and "Generated exact-arithmetic list-mapping Python" in
            render(artifact, request)
            and "2 plus 3" in evidence_text
            and "2 times 3" in evidence_text,
            "artifact explanation or evidence follow-up omitted its exact basis")

    rational_artifact = generate_mapped_math_python(
        model, "map x / 2 over each value")
    require(rational_artifact is not None,
            "standard exact division did not compose with list mapping")
    rational_namespace: dict[str, object] = {}
    exec(compile(rational_artifact.source, "<crms-rational-list-map>", "exec"),
         rational_namespace)
    require(rational_namespace["transform"]([1, -3, 4])
            == [Fraction(1, 2), Fraction(-3, 2), Fraction(2, 1)]
            and rational_namespace["validate_examples"](),
            "mapped math lost exact rational outputs")

    for unsupported in (
            "apply x zarg 3 to each value in the list",
            "apply x plus y to each value in the list",
            "apply x plus 3 metres to each value in the list",
            "apply 3 plus 4 to each value in the list"):
        require(generate_mapped_math_python(model, unsupported) is None,
                f"unsupported map expression produced code: {unsupported}")
    try:
        transform([1, True])
    except TypeError:
        pass
    else:
        raise SystemExit("mapped math function accepted bool as an integer")
    try:
        transform([1] * 10_001)
    except TypeError:
        pass
    else:
        raise SystemExit("mapped math function exceeded its list-size bound")

    with tempfile.TemporaryDirectory(prefix="crms-math-map-chat-") as folder:
        root = Path(folder)
        rules_path = root / "rules.json"
        CRMSModel(max_workers=1).save(rules_path)
        math_path = root / "math.json"
        model.save(math_path)
        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        CRMSResearchIndex().save(root / "index.json")
        paths = {name: root / f"{name}.json" for name in (
            "dialogue", "rule-session", "candidate-session", "translations",
        )}
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(paths["dialogue"]),
            "--rules", str(rules_path),
            "--rule-session", str(paths["rule-session"]),
            "--candidate-session", str(paths["candidate-session"]),
            "--math", str(math_path),
            "--translations", str(paths["translations"]),
        ]
        terminal = subprocess.run(
            command,
            input=("Write Python code to apply x times x plus 3 to each value "
                   "in the list\nExplain that code\n"
                   "Show the examples for that code\n/quit\n"),
            text=True, capture_output=True, cwd=root, check=False, timeout=30)
        require(terminal.returncode == 0
                and "Generated exact-arithmetic list-mapping Python" in
                    terminal.stdout
                and "def transform(values: list[int])" in terminal.stdout
                and "Evidence for generated artifact crms-code-v1-" in
                    terminal.stdout
                and "'plus'" in terminal.stdout and "'times'" in terminal.stdout,
                f"natural math-to-code CLI flow failed:\n"
                f"{terminal.stdout}\n{terminal.stderr}")

    print("grounded math-to-list-code composition: PASS")
    print("learned multiply/add and exact rational division mapped over integer "
          "lists; parity and deterministic provenance: PASS")
    print("unsupported operators, extra variables, units, scalar-only requests, "
          "bools, and oversized lists refused: PASS")
    print("terminal code request, explanation, and evidence follow-up: PASS")


if __name__ == "__main__":
    main()
