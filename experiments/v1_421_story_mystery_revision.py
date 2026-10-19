"""Exercise the bounded mystery genre through the interactive story route."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_story_request, _natural_story_revision
from crms_research import CRMSSQLiteResearchIndex
from crms_story import generate_short_story


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for prompt, topic in (
            ("Write a mystery story about the moon archive.",
             "the moon archive"),
            ("Compose a short mysterious story of a clockmaker.",
             "a clockmaker")):
        require(_natural_story_request(prompt) == (topic, "mystery"),
                f"mystery story request was not parsed: {prompt!r}")
    require(_natural_story_revision("Make it more mysterious") == "mystery"
            and _natural_story_revision("Change the tone to mystery") == "mystery",
            "mystery follow-up revision was not recognized")

    story = generate_short_story("the moon archive", tone="mystery")
    mystery_templates = {
        generate_short_story(f"topic {index}", tone="mystery").template_id
        for index in range(100)
    }
    require(story == generate_short_story("the moon archive", tone="mystery")
            and story.template_id.startswith("mystery-")
            and len(mystery_templates) == 2
            and "the moon archive" in story.text
            and [role for role, _sentence in story.beats]
                == ["discovery", "problem", "attempt", "resolution", "change"]
            and "invented details" in story.render(),
            "mystery story lost determinism, topic, narrative arc, or fiction label")

    with tempfile.TemporaryDirectory(prefix="crms-story-mystery-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        try:
            index.add_document(
                "computing", "Computing facts",
                "Guido van Rossum created Python.", "fixture://computing")
        finally:
            index.close()
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(root / "knowledge.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        result = subprocess.run(
            command,
            input=("Write a mystery story about the moon archive.\n"
                   "Make it funnier.\nMake it more mysterious.\n"
                   "Who created Python?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(result.returncode == 0,
                f"chat failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        require(result.stdout.count(
                    "Fictional short story (invented details; no factual claims):")
                == 3
                and "Template: mystery-" in result.stdout
                and "Revised the story in a funny tone." in result.stdout
                and "Revised the story in a mystery tone." in result.stdout
                and "Guido van Rossum created Python." in result.stdout,
                f"story genre revision or factual-route isolation failed: {result.stdout}")

    print("user-requested mystery grammar and tone revision: PASS")
    print("story topic, five-beat form, and fiction label retained: PASS")
    print("CLI revisions stay separate from the factual source route: PASS")


if __name__ == "__main__":
    main()
