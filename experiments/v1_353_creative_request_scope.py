"""Check concise scope handling for explicit original-writing requests."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_creative_request, _natural_story_request
from crms_research import CRMSSQLiteResearchIndex
from crms_story import generate_short_story


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    positive = {
        "Write a short story about Python.": "story",
        "Compose a poem about Ada Lovelace.": "poem",
        "Tell me a joke.": "joke",
        "Make me a song about Linux": "song",
        "Write a haiku": "haiku",
        "Write lyrics about computing": "lyrics",
    }
    for prompt, expected in positive.items():
        require(_natural_creative_request(prompt) == expected,
                f"creative request was not recognized: {prompt!r}")

    story_prompts = {
        "Write a short story about Python.": ("Python", "adventure"),
        "Tell me a funny story about a paper airplane.":
            ("a paper airplane", "funny"),
        "Compose a story": (None, "adventure"),
    }
    for prompt, expected in story_prompts.items():
        require(_natural_story_request(prompt) == expected,
                f"story request was not parsed: {prompt!r}")
    artifact = generate_short_story("Python", tone="adventure")
    require(artifact == generate_short_story("Python", tone="adventure")
            and artifact.as_dict()["kind"] == "fictional_story"
            and [role for role, _sentence in artifact.beats]
                == ["discovery", "problem", "attempt", "resolution", "change"]
            and "Python" in artifact.text
            and "invented details" in artifact.render(),
            "story artifact lost determinism, its narrative arc, or fiction label")
    funny = generate_short_story("a paper airplane", tone="funny")
    require(funny.template_id == "comic-council-v1"
            and "a paper airplane" in funny.text,
            "funny story request did not select the comic story grammar")
    for invalid_topic in ("", "x" * 121, "line\nbreak"):
        try:
            generate_short_story(invalid_topic)
        except ValueError:
            pass
        else:
            raise SystemExit(f"invalid story topic was accepted: {invalid_topic!r}")

    negative = (
        "Who created Python?",
        "What is the capital of France?",
        "Who wrote the poem that inspired Python?",
        "Write Python code to reverse a list.",
        "What is a short story?",
        "Can you explain Python?",
    )
    for prompt in negative:
        require(_natural_creative_request(prompt) is None,
                f"in-scope or non-imperative input was misrouted: {prompt!r}")

    with tempfile.TemporaryDirectory(prefix="crms-creative-scope-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        try:
            index.add_document(
                "computing", "Computing facts",
                "Guido van Rossum created Python. Paris is the capital of France.",
                "fixture://computing")
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
        ]
        result = subprocess.run(
            command,
            input=("Write a short story about Python.\n"
                   "Compose a short story\n"
                   "a paper airplane\n"
                   "Tell me a funny story about a paper airplane.\n"
                   "Compose a short story\n"
                   "Who created Python?\n"
                   "Compose a story\n"
                   "/cancel-story\n"
                   "Write a story about Python based on sources.\n"
                   "Compose a poem about Ada Lovelace.\n"
                   "Tell me a joke.\n"
                   "Who created Python?\n"
                   "What is the capital of France?\n"
                   "/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(result.returncode == 0,
                f"chat failed ({result.returncode}): {result.stderr}\n"
                f"{result.stdout}")
        scope_reply = "Poems, songs, jokes, and other original writing requests aren't supported yet."
        require(result.stdout.count(scope_reply) == 2,
                f"creative requests did not receive the scope reply: {result.stdout}")
        require(result.stdout.count(
                    "I can write a short fictional story from a topic, but this "
                    "story grammar can't use source facts") == 1
                and "Cancelled the story request." in result.stdout,
                f"unsupported source grounding or cancellation was unclear: "
                f"{result.stdout}")
        require(result.stdout.count(
                    "Fictional short story (invented details; no factual claims):")
                == 3
                and "Story structure: discovery → problem → attempt → resolution → change."
                    in result.stdout
                and "Template: comic-council-v1." in result.stdout
                and result.stdout.count("What should the story be about?") == 3,
                f"story generation or topic clarification failed: {result.stdout}")
        require(result.stdout.count("Guido van Rossum created Python.") == 2
                and "Paris is the capital of France." in result.stdout,
                f"factual requests did not retain their normal routes: "
                f"{result.stdout}")

    print("bounded story generation, topic clarification, source-constraint "
          "refusal, and factual routing: PASS")


if __name__ == "__main__":
    main()
