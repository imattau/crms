"""Keep source-only follow-up pronouns grounded across paragraph boundaries.

The fixture is derived from a user-reported wrong-answer sequence. It protects
the topic-switch behavior with a fresh CLI process, including the negative case
where the cited pronoun sentence has no paragraph-local named antecedent.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(index_path: Path, state_path: Path, questions: str) -> str:
    memory_path = state_path.with_suffix(".knowledge.json")
    result = subprocess.run(
        [sys.executable, str(PROJECT / "crms_chat.py"),
         "--knowledge", str(memory_path),
         "--index", str(index_path), "--index-read-only",
         "--dialogue-state", str(state_path),
         "--dialogue-model", str(state_path.with_suffix(".intent.json")),
         "--rules", str(state_path.with_suffix(".rules.json")),
         "--math", str(state_path.with_suffix(".math.json")),
         "--translations", str(state_path.with_suffix(".translations.json")),
         "--feedback-db", str(state_path.with_suffix(".feedback.sqlite"))],
        input=questions + "/quit\n", text=True, capture_output=True,
        check=False, timeout=30)
    require(result.returncode == 0,
            f"fresh chat exited {result.returncode}: {result.stderr}")
    return result.stdout


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-paragraph-pronoun-") as folder:
        root = Path(folder)
        source = root / "places.txt"
        source.write_text(
            "The Eiffel Tower was completed in 1889.\n\n"
            "The Colosseum is an amphitheatre in Rome. "
            "It was completed in 1980.\n",
            encoding="utf-8")
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_file(source)
        index.close()

        transcript = run_chat(
            index_path, root / "grounded-state.json",
            "When was the Eiffel Tower completed?\n"
            "What about the Colosseum?\n"
            "When was it completed?\n")
        final_reply = transcript.rsplit("CRMS>", 1)[-1]
        require("1980" in final_reply and "1889" not in final_reply,
            "topic switch answered the follow-up with the older Eiffel date:\n"
            + transcript)
        require("The Colosseum" in transcript,
                "fresh chat did not cite the Colosseum source sentence")

        # A pronoun sentence in the next paragraph cannot inherit a nearby
        # named entity merely because it is in the same document.
        source.write_text(
            "The Eiffel Tower was completed in 1889.\n\n"
            "The Colosseum is an amphitheatre in Rome.\n\n"
            "It was completed in 1980.\n",
            encoding="utf-8")
        index_path = root / "unanchored.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_file(source)
        index.close()
        unanchored = run_chat(
            index_path, root / "unanchored-state.json",
            "When was the Colosseum completed?\n")
        require("I won't guess" in unanchored
                and "quoted evidence, not an accepted fact" not in unanchored,
                "pronoun-only paragraph was attributed to a named entity:\n"
                + unanchored)

    print("cross-paragraph topic switch keeps the answer on the Colosseum: PASS")
    print("pronoun-only paragraph without local anchor does not answer: PASS")
    print("both cases exercised in fresh chat processes: PASS")


if __name__ == "__main__":
    main()
