"""Check teacher-aligned same-language rewrite learning in grounded chat."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_translation import CRMSTranslation
from crms_package import inspect_model_database


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    source_template = (
        "We show that the cop number of {graph} is at most {number}.")
    target_template = (
        "You need no more than {number} cops to catch a robber on {graph}.")
    examples = [
        ("We show that the cop number of toroidal graphs is at most 3.",
         "You need no more than 3 cops to catch a robber on toroidal graphs."),
        ("We show that the cop number of planar graphs is at most 2.",
         "You need no more than 2 cops to catch a robber on planar graphs."),
    ]
    model = CRMSTranslation()
    try:
        model.teach("English", "English", "plain", source_template,
                    target_template, examples)
    except ValueError:
        pass
    else:
        raise SystemExit("cross-language teach unexpectedly accepted same-language pair")
    result = model.teach_rewrite(
        "English", "plain", source_template, target_template, examples)
    require(result.status == "licensed", "aligned same-language frame was not licensed")
    novel = model.rewrite(
        "We show that the cop number of hyperbolic graphs is at most 4.")
    require(novel is not None and novel.status == "translated"
            and novel.output == (
                "You need no more than 4 cops to catch a robber on hyperbolic graphs."),
            f"frame did not generalize its copied slots: {novel}")

    mapped = CRMSTranslation()
    mapped.teach_rewrite(
        "English", "plain", "The word {word} means {definition}.",
        "The word {word} means {definition}.", [
            ("The word ameliorate means make better.",
             "The word improve means make better."),
            ("The word commence means start.", "The word begin means start."),
        ])
    known_mapping = mapped.rewrite("The word ameliorate means make better.")
    unknown_mapping = mapped.rewrite("The word alleviate means make better.")
    require(known_mapping is not None and known_mapping.output
            == "The word improve means make better."
            and unknown_mapping is not None and unknown_mapping.status == "unknown"
            and "{word}" in str(unknown_mapping.request),
            "unseen mapped vocabulary did not abstain")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        memory = root / "roundtrip-translations.json"
        model.save(memory)
        restored = CRMSTranslation.load(memory)
        require(restored.rewrite(examples[0][0]) is not None,
                "same-language rewrite was not restored from disk")

        portable_model = root / "model.sqlite"
        shutil.copy2(PROJECT / "data" / "crms_project_model_academic.sqlite",
                     portable_model)

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(portable_model),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math-session", str(root / "math-session.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        teaching = (
            'Teach a rewrite frame from English to English in plain register: '
            f'"{source_template}" => "{target_template}"; '
            f'"{examples[0][0]}" -> "{examples[0][1]}"; '
            f'"{examples[1][0]}" -> "{examples[1][1]}"')
        run = subprocess.run(
            command,
            input=(teaching + "\n"
                   "What is the main result of On the cop number of toroidal graphs?\n"
                   "Can you explain the result in simpler terms?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        require("Rewrite frame licensed for English (plain register)" in run.stdout
                and "You need no more than 3 cops to catch a robber on toroidal graphs."
                in run.stdout
                and "arxiv.org/abs/1904.07946v3" in run.stdout
                and "I don't have a verified language rule" not in run.stdout,
                f"learned rewrite did not answer from the cited paper: {run.stdout}")
        stored = CRMSTranslation.load(
            root / "model.sqlite.memories" / "translations.json")
        portable_rewrite = stored.rewrite(examples[0][0])
        require(portable_rewrite is not None
                and portable_rewrite.output == examples[0][1],
                "learned rewrite was not reintegrated into the portable model")
        packaged = inspect_model_database(portable_model)
        require("translations" in packaged,
                "portable SQLite database does not embed the rewrite memory")

    print("grounded same-language plain rewrite and chat integration: PASS")


if __name__ == "__main__":
    main()
