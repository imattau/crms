"""Plain-result follow-ups distinguish an explanation from a source quote."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex
from crms_translation import CRMSTranslation

TITLE = "On the cop number of toroidal graphs"
ABSTRACT = (
    "We show that the cop number of toroidal graphs is at most 3. "
    "This resolves a conjecture by Schroeder from 2001 which is implicit "
    "in a question by Andreae from 1986.")
QUESTION = f"What is the main result of {TITLE}?"
FOLLOWUP = "Can you explain the result in simpler terms?"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(root: Path, index_path: Path, suffix: str) -> str:
    translations = CRMSTranslation()
    if suffix == "learned":
        translations.teach_rewrite(
            "English", "plain",
            "We show that the cop number of {graph} is at most {number}.",
            "The paper proves that the cop number of {graph} is {number} or less.",
            [
                ("We show that the cop number of toroidal graphs is at most 3.",
                 "The paper proves that the cop number of toroidal graphs is 3 or less."),
                ("We show that the cop number of planar graphs is at most 2.",
                 "The paper proves that the cop number of planar graphs is 2 or less."),
            ])
    translations_path = root / f"{suffix}-translations.json"
    translations.save(translations_path)
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / f"{suffix}-knowledge.json"),
        "--index", str(index_path), "--index-read-only",
        "--translations", str(translations_path),
        "--dialogue-state", str(root / f"{suffix}-dialogue.json"),
        "--candidate-session", str(root / f"{suffix}-candidates.json"),
        "--rule-session", str(root / f"{suffix}-rules.json"),
        "--math", str(root / f"{suffix}-math.json"),
    ]
    result = subprocess.run(
        command, input=f"{QUESTION}\n{FOLLOWUP}\n/quit\n", text=True,
        capture_output=True, cwd=root, check=False, timeout=45)
    require(result.returncode == 0 and "Traceback" not in
            result.stdout + result.stderr,
            f"chat failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-plain-result-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "toroidal-cops", TITLE,
            f"Source: arXiv metadata API\nTitle: {TITLE}\n"
            f"Abstract: {ABSTRACT}\nPublished: 2019-04-16\n",
            "https://arxiv.org/abs/1904.07946v3")
        index.close()

        unlicensed = run_chat(root, index_path, "unlicensed")
        require("I don't have a verified plain-language rewrite for this result yet"
                in unlicensed
                and "The source says: “We show that the cop number of toroidal graphs is at most 3."
                in unlicensed
                and "two aligned source and simpler-sentence examples" in unlicensed,
                f"missing rewrite was presented as an explanation: {unlicensed}")
        require("I used this quoted source sentence as evidence" not in unlicensed,
                "the no-rewrite response used the generic evidence label")

        licensed = run_chat(root, index_path, "learned")
        require("The paper proves that the cop number of toroidal graphs is 3 or less."
                in licensed
                and "Using a learned plain-register frame" in licensed
                and "arxiv.org/abs/1904.07946v3" in licensed,
                f"a learned plain rewrite failed or lost source attribution: {licensed}")

    print("unlicensed plain-language request is identified honestly: PASS")
    print("a learned rewrite still answers with source attribution: PASS")
    print("scope: learned rewrite from Codex-aligned examples; not autonomous explanation")


if __name__ == "__main__":
    main()
