"""Ensure embedded uncertainty cannot be presented as an asserted claim."""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def candidate(sentence: str):
    digest = hashlib.sha256(sentence.encode("utf-8")).hexdigest()
    citation = f"control#sha256={digest}&chars=0:{len(sentence)}"
    results = propose_procedure_phrase_candidates(
        sentence, source_citation=citation)
    require(len(results) == 1,
            f"expected one review-only phrase candidate: {sentence!r}: {results!r}")
    return results[0]


def main() -> None:
    cases = (
        ("In this case, it is not well defined which sample will be chosen.",
         "uncertain"),
        ("The documentation is written as though values will be scalars.",
         "uncertain"),
        ("The output is described as if values will be vectors.",
         "uncertain"),
        ("It is unclear whether the function will sort the values.",
         "uncertain"),
        ("The documentation does not guarantee that all values will be sorted.",
         "denied"),
        ("The function will sort the values.", "asserted"),
    )
    for sentence, expected in cases:
        result = candidate(sentence)
        require(result.assertion_status == expected,
                f"wrong assertion status for {sentence!r}: {result!r}")
        require(result.status == "needs_review",
                "uncertain or denied claims must remain review-only")
    check_chat_uncertainty()
    print("PASS: non-well-defined and hypothetical clauses are marked uncertain")
    print("PASS: explicit denial and ordinary assertion remain distinct")
    print("PASS: chat labels uncertain source wording and does not teach a rule")


def check_chat_uncertainty() -> None:
    project = Path(__file__).resolve().parents[1]
    sentence = (
        "In this case, it is not well defined which sample will be chosen.")
    with tempfile.TemporaryDirectory(prefix="crms-v1-488-") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        index.add_document("uncertainty", "Sample policy", sentence,
                           "fixture:sample-policy")
        index.save(root / "index.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSMath().save(root / "math.json")
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSTranslation().save(root / "translations.json")
        command = [
            sys.executable, str(project / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--math", str(root / "math.json"),
            "--rules", str(root / "rules.json"),
            "--translations", str(root / "translations.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--rule-session", str(root / "rule-session.json"),
        ]
        process = subprocess.run(
            command,
            input="/suggest-procedure-phrases sample chosen\n/rules\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        require("embedding claim uncertain; not positive rule evidence"
                in process.stdout
                and "No transformation rules are committed yet." in process.stdout,
                f"chat treated uncertainty as asserted or changed the rule store:\n"
                f"{process.stdout}")


if __name__ == "__main__":
    main()
