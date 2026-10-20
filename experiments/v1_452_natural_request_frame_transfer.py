"""Measure transfer from positional phrase roles to ordinary request syntax.

The model learns six labeled action/object/direction combinations and is then
asked five semantically positive requests with different syntax, plus an
unsupported descending request. This baseline tracks partial transfer and
safe abstention as the learner improves. The positive forms and expected
operation are Codex-authored labels.
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
    "sort the values in ascending order",
    "sort numbers in ascending order",
    "order the numbers in ascending order",
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

        transferred = model.predict(
            POSITIVE_REQUESTS[2], [3, 1, 2])
        require(transferred.status == "ok"
                and transferred.output == [1, 2, 3]
                and transferred.matched_templates
                and transferred.matched_templates[0].startswith("role_frame:")
                and "learned role frame" in (transferred.message or "")
                and set(transferred.evidence_phrases or ()) >= {
                    "arrange numbers upward", "arrange values increasing",
                    "order numbers ascending", "sort values ascending",
                },
                f"role transfer lost output or source phrases: {transferred}")
        artifact = generate_python(model, POSITIVE_REQUESTS[2])
        require(artifact is not None,
                "learned role frame did not generate code")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<natural-role-frame>", "exec"), namespace)
        for values in ([3, 1, 2], [7, -2, 7], [], [5]):
            require(namespace["transform"](values) == sorted(values),
                    f"role-frame code failed independent oracle on {values}")

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
        require(POSITIVE_REQUESTS[2] in generated,
                "learned role support did not transfer through the article and "
                "directional function words in 'arrange values in ascending order'")
        require(set(POSITIVE_REQUESTS[2:3] + POSITIVE_REQUESTS[5:8])
                <= set(generated),
                "a regression lost one of the three licensed function-word "
                "variants")
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
