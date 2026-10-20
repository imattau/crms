"""Measure request-syntax transfer for proof-checked procedure composition.

The accepted variants preserve the relation and learned operation wording;
only the list/request frame and an explicit ``and then`` connective vary.
Unlicensed operation paraphrases and unknown relation wording remain controls.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_491_one_turn_reasoning_filter_recombination import build_case
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    knowledge, procedures = build_case()
    variants = (
        "Filter 12, 4, 4, 9, and 7 to values Nia reaches; then remove duplicate "
        "values then reverse the list.",
        "Given 12, 4, 4, 9, and 7, keep the values Nia reaches, and then remove "
        "duplicate values then reverse the list.",
        "From [12, 4, 4, 9, 7], return the values Nia reaches, then remove "
        "duplicate values then reverse the list.",
        "From [12, 4, 4, 9, 7], return the values Nia reaches, then remove "
        "duplicate values and then reverse the list.",
    )
    for request in variants:
        result = compose_verified_filter(request, knowledge, procedures)
        require(result is not None and result.status == "answered"
                and result.output_values == (9, 4, 12)
                and result.excluded_negative == (7,)
                and len(result.inference_proofs) == 3,
                f"ordinary request frame did not preserve verified composition: "
                f"{request!r}: {result}")

    # The parser may normalize an explicit connective, but it must not invent
    # operation synonyms or broaden relation vocabulary without supervision.
    unlicensed_operation = compose_verified_filter(
        "From [12, 4, 4, 9, 7], return the values Nia reaches, then deduplicate "
        "and reverse the result.", knowledge, procedures)
    require(unlicensed_operation is not None
            and unlicensed_operation.status == "unsupported_procedure"
            and not unlicensed_operation.output_values,
            f"unlicensed operation paraphrase was executed: {unlicensed_operation}")
    unlicensed_relation = compose_verified_filter(
        "From [12, 4, 4, 9, 7], return the values Nia can reach, then remove "
        "duplicate values then reverse the list.", knowledge, procedures)
    require(unlicensed_relation is not None
            and unlicensed_relation.status == "unsupported"
            and not unlicensed_relation.output_values,
            f"unlicensed relation paraphrase was executed: {unlicensed_relation}")

    with tempfile.TemporaryDirectory(prefix="crms-compose-language-") as folder:
        root = Path(folder)
        knowledge.save(root / "knowledge.json")
        procedures.save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command,
            input="\n".join((*variants, "/quit", "")),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = chat.stdout + chat.stderr
        require(chat.returncode == 0 and "Traceback" not in output
                and output.count("[9, 4, 12]") == len(variants),
                f"fresh-process chat did not answer all licensed variants:\n{output}")

    print("three natural request frames compose through fresh-process chat: PASS")
    print("verified proof set and explicit-negative handling are preserved: PASS")
    print("unlicensed operation and relation paraphrases remain unsupported: PASS")
    print("scope: syntactic request variation; no synonym induction or broad planning")


if __name__ == "__main__":
    main()
