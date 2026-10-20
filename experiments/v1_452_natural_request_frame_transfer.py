"""Measure transfer from positional phrase roles to ordinary request syntax.

The model learns six labeled action/object/direction combinations and is then
asked five semantically positive requests with different syntax, plus an
unsupported descending request. This baseline reports the current gap: safe
abstention is preserved, but the positive paraphrases are not yet understood.
The positive forms and expected operation are Codex-authored labels.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import generate_python
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


SEEDS = (
    "sort values ascending",
    "sort items upward",
    "order items increasing",
    "order numbers ascending",
    "arrange numbers upward",
    "arrange values increasing",
)
EXAMPLES = (
    ([5, 2, 3, 1, 4], [1, 2, 3, 4, 5]),
    ([1, -1, 1], [-1, 1, 1]),
    ([0, 1, -1], [-1, 0, 1]),
)
POSITIVE_REQUESTS = (
    "put items in increasing order",
    "sort numbers from low to high",
    "arrange values in ascending order",
    "order the numbers ascendingly",
    "make the values go from smallest to largest",
)
NEGATIVE_REQUESTS = ("sort items descending",)
LABELER = "codex:natural-request-frame-baseline-v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-natural-request-frame-") as folder:
        root = Path(folder)
        model_path = root / "rules.json"
        model = CRMSModel(model_path, max_composition_depth=1, max_workers=1)
        for phrase in SEEDS:
            learned = model.teach(
                phrase, EXAMPLES,
                labeler_ids=[LABELER] * len(EXAMPLES))
            require(learned.status == "learned",
                    f"seed procedure failed to learn for {phrase!r}: {learned}")

        for path, save in (
                (root / "knowledge.json", CRMSKnowledgeBase().save),
                (root / "math.json", CRMSMath().save),
                (root / "index.json", CRMSResearchIndex().save),
                (root / "translations.json", CRMSTranslation().save)):
            save(path)

        requests = (*POSITIVE_REQUESTS, *NEGATIVE_REQUESTS)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(model_path),
            "--knowledge", str(root / "knowledge.json"),
            "--math", str(root / "math.json"),
            "--index", str(root / "index.json"),
            "--translations", str(root / "translations.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command,
            input="\n".join(
                f"Write Python code to {request}" for request in requests)
                + "\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = chat.stdout + chat.stderr
        require(chat.returncode == 0 and "Traceback" not in output,
                f"fresh chat failed: {output[-2500:]}")

        generated = [request for request in requests
                     if f"Generated Python for '{request}'" in output]
        missed_positive = [request for request in POSITIVE_REQUESTS
                           if request not in generated]
        false_positive = [request for request in NEGATIVE_REQUESTS
                          if request in generated]
        require(not false_positive,
                f"unsupported direction received generated code: {false_positive}")
        lowered_output = output.casefold()
        for request in missed_positive:
            require(f"could not resolve '{request}'" in lowered_output,
                    f"missed positive request did not abstain clearly: {request!r}")

        print("fresh chat preserved six learned role combinations: PASS")
        print("positive syntactic paraphrase coverage: "
              f"{len(POSITIVE_REQUESTS) - len(missed_positive)}/"
              f"{len(POSITIVE_REQUESTS)}")
        print(f"unsupported descending requests generated: {len(false_positive)}")
        print("scope: Codex-labeled natural wording; not an independent language benchmark")


if __name__ == "__main__":
    main()
