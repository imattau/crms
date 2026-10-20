"""Check explicit arithmetic words and relative-difference question frames.

Operands are taken from a CC BY PMC source record to anchor the probe. The
experiment tests exact math on user-supplied operands; it does not claim that
CRMS extracts or links those operands to the source automatically.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_math import CRMSMath, render
from crms_research import CRMSSQLiteResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = (PROJECT / "data" /
             "crms_project_model_academic_expanded_pmc.sqlite.memories" /
             "research.sqlite")
REPORT = PROJECT / "experiments" / "reports" / "v1_531_standard_math_operator_phrases.json"
SOURCE_DOCUMENT = "pmc:PMC13675955.v1.rb496c301cb6ab27e"
SOURCE_CLAIM = (
    "In women, the fraction of non-reference chrX genotypes that were "
    "heterozygous was 0.605 on GRCh38 and 0.644 on T2T."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(SOURCE_DB.is_file(), f"missing read-only source index: {SOURCE_DB}")
    source = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)
    document = source.document(SOURCE_DOCUMENT)
    require(SOURCE_CLAIM in document.text,
            "the source record no longer contains the numeric comparison")
    require("Redistribution license: CC BY" in document.text[:1000],
            "the source record no longer exposes its redistribution license")

    examples = [
        ("What is 0.644 minus 0.605?", Fraction(39, 1000)),
        ("How much higher is 0.644 than 0.605?", Fraction(39, 1000)),
        ("How much lower is 0.605 than 0.644?", Fraction(39, 1000)),
        ("How much higher is 0.605 than 0.644?", Fraction(-39, 1000)),
        ("What is 2 plus 3 times 4?", Fraction(14)),
        ("What is (2 plus 3) times 4?", Fraction(20)),
        ("What is 8 multiplied by 3?", Fraction(24)),
        ("What is 9 divided by 4?", Fraction(9, 4)),
        ("What is 10 modulo 3?", Fraction(1)),
        ("What is 10 mod 3?", Fraction(1)),
    ]
    math = CRMSMath()
    first_plus_example = math.teach("What is 2 plus 3?", "5")
    second_plus_example = math.teach("What is 4 plus 1?", "5")
    require(first_plus_example.status == "needs_more_examples"
            and second_plus_example.status == "licensed",
            "consistent teaching for a standard operator no longer licenses")
    outputs = []
    for question, expected in examples:
        result = math.ask(question)
        require(result is not None and result.status == "answered"
                and result.value == expected,
                f"exact arithmetic failed for {question!r}: {result!r}")
        outputs.append({"question": question, "answer": render(result)})

    require(math.ask("How much higher is the tower than the museum?") is None,
            "relative-difference frame accepted nonnumeric operands")
    require(math.ask("What is 4 divided by 0?").status == "unknown",
            "division by zero did not abstain")
    try:
        math.teach("What is 2 minus 1?", "3")
    except ValueError as error:
        require("fixed standard arithmetic meaning" in str(error),
                f"fixed operator rejection had the wrong reason: {error}")
    else:
        raise SystemExit("a standard operator meaning was mutable by teaching")

    with tempfile.TemporaryDirectory(prefix="crms-v1-531-") as temp:
        root = Path(temp)
        math_path = root / "math.json"
        math.save(math_path)
        restored = CRMSMath.load(math_path)
        for question, expected in examples:
            result = restored.ask(question)
            require(result is not None and result.value == expected,
                    f"standard math meaning changed after reload: {question}")
        tampered = json.loads(math_path.read_text(encoding="utf-8"))
        plus_record = next(record for record in tampered["examples"]
                           if record["phrase"] == ["plus"])
        plus_record["rows"][0]["answer"] = "6"
        tampered_path = root / "tampered-math.json"
        tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            CRMSMath.load(tampered_path)
        except ValueError as error:
            require("conflicts with standard arithmetic" in str(error),
                    f"tampered store rejected for the wrong reason: {error}")
        else:
            raise SystemExit("tampered standard operator meaning loaded")

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--index", str(SOURCE_DB), "--index-read-only",
            "--dialogue-state", str(root / "dialogue.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        result = subprocess.run(
            command,
            input=("What is 0.644 minus 0.605?\n"
                   "How much higher is 0.644 than 0.605?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=90, check=False)
        output = result.stdout + result.stderr
        require(result.returncode == 0 and "Traceback" not in output,
                f"fresh CLI failed: {output[-2500:]}")
        answer_lines = [line for line in output.splitlines() if "CRMS>" in line]
        require(len(answer_lines) >= 2
                and all("39/1000" in line for line in answer_lines[:2])
                and all("standard operator 'minus'" in line
                        for line in answer_lines[:2]),
                f"full chat did not use exact natural-language math: {output}")

    report = {
        "experiment": "v1_531_standard_math_operator_phrases",
        "source": {
            "document_id": SOURCE_DOCUMENT,
            "title": document.title,
            "license": "CC BY, as recorded in the local PMC snapshot",
            "numeric_claim": SOURCE_CLAIM,
        },
        "method": "exact math API plus fresh CLI against read-only PMC source index",
        "metrics": {
            "exact_natural_language_cases": len(examples),
            "exact_cases_passed": len(examples),
            "save_reload_cases_passed": len(examples),
            "full_cli_cases_passed": 2,
            "unsupported_operands": "abstained",
            "division_by_zero": "abstained",
            "consistent_standard_operator_examples": "licensed",
            "conflicting_override_of_standard_operator": "rejected",
            "tampered_standard_operator_store": "rejected",
        },
        "operator_scope": {
            "fixed": ["plus", "minus", "times", "multiplied by",
                      "divided by", "mod", "modulo"],
            "learned_phrases_remain_example_gated": True,
        },
        "limitations": [
            "The two article values were supplied explicitly in the math question; automatic source-value extraction and provenance linking are not tested.",
            "The source comparison is one scientific article, not a cross-publisher evaluation set.",
            "This covers exact arithmetic wording, not broad mathematical reasoning or theorem proving.",
            "CRMS reports the fraction difference 39/1000; it does not yet phrase the result as 3.9 percentage points.",
        ],
        "cases": outputs,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")

    print("standard arithmetic phrases and comparison frames: PASS")
    print("exact decimal arithmetic, order/precedence, save/reload: PASS")
    print("unsupported operands and division by zero abstain: PASS")
    print("consistent teaching is accepted; conflicting operator meaning rejected: PASS")
    print("fresh CLI with read-only PMC index: PASS")
    print("source-to-operand extraction is covered separately by v1_532/v1_533")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
