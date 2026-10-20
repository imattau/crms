"""Check natural yes/no questions over exact stored relations without teaching frames."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Paris", "capital of", "France", "source:capital-positive")
    kb.add_negative_fact("Sydney", "capital of", "Australia",
                         "source:capital-negative")
    kb.add_fact("Guido van Rossum", "create", "Python", "source:create-python")
    kb.add_negative_fact("Guido van Rossum", "create", "Linux",
                         "source:not-create-linux")

    expectations = {
        "Is Paris the capital of France?": ("answered", "Yes", True),
        "Is Sydney the capital of Australia?": ("answered", "No", False),
        "Did Guido van Rossum create Python?": ("answered", "Yes", True),
        "Did Guido van Rossum create Linux?": ("answered", "No", False),
        # Open-world absence and unobserved paraphrases must not become No/Yes.
        "Is Sydney the capital of France?": ("unknown", None, None),
        "Did Guido van Rossum create Rust?": ("unknown", None, None),
        "Did Guido van Rossum invent Python?": ("unknown", None, None),
    }
    for question, (status, answer, truth) in expectations.items():
        result = kb.ask(question)
        if (result.status != status or result.answer != answer
                or result.truth is not truth):
            raise SystemExit(f"unexpected result for {question!r}: {result}")
        if status == "answered" and not result.evidence:
            raise SystemExit(f"truth answer omitted its fact evidence: {question}")
        if status == "answered":
            expected_prefix = "Yes." if truth else "No."
            if not kb.render_brief(result).startswith(expected_prefix):
                raise SystemExit(
                    f"polar answer was not realized as {expected_prefix!r}: "
                    f"{kb.render_brief(result)}")
        if status == "unknown" and result.answer is not None:
            raise SystemExit(f"unknown proposition was answered: {question}")

    with tempfile.TemporaryDirectory(prefix="crms-polar-chat-") as folder:
        root = Path(folder)
        knowledge = root / "knowledge.json"
        kb.save(knowledge)
        paths = {name: root / name for name in (
            "index.json", "dialogue.json", "rules.json", "rule-session.json",
            "math.json", "math-session.json", "translations.json",
            "translation-session.json")}
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge), "--index", str(paths["index.json"]),
            "--dialogue-state", str(paths["dialogue.json"]),
            "--rules", str(paths["rules.json"]),
            "--rule-session", str(paths["rule-session.json"]),
            "--math", str(paths["math.json"]),
            "--math-session", str(paths["math-session.json"]),
            "--translations", str(paths["translations.json"]),
            "--translation-session", str(paths["translation-session.json"]),
        ]
        turns = [
            "Is Paris the capital of France?",
            "Is Sydney the capital of Australia?",
            "Is Sydney the capital of France?",
            "Did Guido van Rossum create Python?",
            "Did Guido van Rossum create Rust?",
            "Did Guido van Rossum invent Python?",
            "/quit",
        ]
        run = subprocess.run(
            command, input="\n".join(turns) + "\n", text=True,
            capture_output=True, cwd=root, timeout=30, check=False)
        if run.returncode != 0:
            raise SystemExit(f"chat exited {run.returncode}:\n{run.stdout}\n{run.stderr}")
        for expected in (
                "CRMS> Yes.", "CRMS> No.",
                "I don't have a direct source statement for this exact "
                "proposition",
                "I can't answer yes or no from the sources I have."):
            if expected not in run.stdout:
                raise SystemExit(
                    f"chat output omitted {expected!r}:\n{run.stdout}")

    print("unframed polar-question diagnostic: PASS")
    print("exact stored-relation parsing, explicit positive/negative evidence, open-world abstention, unseen-synonym abstention, CLI runtime: PASS")


if __name__ == "__main__":
    main()
