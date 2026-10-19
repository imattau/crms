"""Check exact-title definitions, counted noun phrases, and superlatives."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import (
    _exact_title_definition,
    _natural_count_evidence,
    _natural_superlative_evidence,
)
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-332-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "photosynthesis", "Photosynthesis",
            "Photosynthesis is a process by which plants use sunlight to make food. "
            "Photosynthesis is the process by which light becomes chemical energy. "
            "Photosynthesis is not an accident.", "photosynthesis.txt")
        index.add_document(
            "mars", "Mars",
            "Mars has two small moons, called Phobos and Deimos.", "mars.txt")
        index.add_document(
            "mars-moons", "Moons of Mars",
            "Mars has two little moons called Phobos and Deimos.", "mars-moons.txt")
        index.add_document(
            "co-orbitals", "3753 Cruithne",
            "Mars has four known co-orbital asteroids, and Jupiter has many "
            "(more than 1000 known objects); there are also small co-orbital "
            "moons in the Saturnian system.", "co-orbitals.txt")
        index.add_document(
            "jupiter", "Jupiter",
            "Jupiter is the largest planet in the Solar System.", "jupiter.txt")
        index.add_document(
            "iron-planet", "Iron planet",
            "Mercury is the largest celestial body to be an iron-rich planet.",
            "iron-planet.txt")
        index.add_document(
            "planet-smoothie", "Planet Smoothie",
            "Planet Smoothie is the third largest American chain of smoothie stores.",
            "planet-smoothie.txt")

        definition = _exact_title_definition(index, "photosynthesis")
        require(definition is not None
                and definition["text"].startswith("Photosynthesis is a process")
                and "not an accident" not in definition["text"],
                f"exact-title lead definition was not selected: {definition}")

        count = _natural_count_evidence(
            index, "How many moons does Mars have?")
        require(count is not None and count.get("quantity") == "two"
                and count["text"] in {
                    "Mars has two small moons, called Phobos and Deimos.",
                    "Mars has two little moons called Phobos and Deimos.",
                }, f"count parser lost a number before a modifier: {count}")
        require("1000" not in count["text"],
                "unrelated later count leaked into the Mars moon answer")

        superlative = _natural_superlative_evidence(
            index, "Which planet is largest?")
        require(superlative is not None
                and superlative["title"] == "Jupiter"
                and superlative["text"]
                    == "Jupiter is the largest planet in the Solar System.",
                f"title-led category superlative was not grounded: {superlative}")
        require(_natural_superlative_evidence(
            index, "Which planet is smallest?") is None,
            "missing superlative evidence did not abstain")
        index.close()

        knowledge = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge)
        state = root / "state"
        state.mkdir()
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge), "--index", str(index_path),
            "--dialogue-state", str(state / "dialogue.json"),
            "--rules", str(state / "rules.json"),
            "--rule-session", str(state / "rule-session.json"),
            "--candidate-session", str(state / "candidates.json"),
            "--math", str(state / "math.json"),
            "--translations", str(state / "translations.json"),
        ]
        run = subprocess.run(
            command,
            input=("What is photosynthesis?\n"
                   "How many moons does Mars have?\n"
                   "Which planet is largest?\n/quit\n"),
            text=True, capture_output=True, cwd=state, timeout=30)
        require(run.returncode == 0, f"chat failed: {run.stderr}\n{run.stdout}")
        for expected in (
                "Photosynthesis is a process by which plants use sunlight to make food.",
                "Jupiter is the largest planet in the Solar System."):
            require(expected in run.stdout,
                    f"chat did not return grounded answer {expected!r}:\n{run.stdout}")
        require(("Mars has two little moons called Phobos and Deimos." in run.stdout
                 or "Mars has two small moons, called Phobos and Deimos." in run.stdout),
                f"chat did not return either corroborating count sentence:\n{run.stdout}")
        require("multiple equally supported" not in run.stdout.casefold(),
                f"grounded specialist answer was overwritten by a lexical tie:\n{run.stdout}")

    print("title-led definition, noun-phrase count, and category superlative: PASS")
    print("near-miss rejection, exact-source citation, and standard chat path: PASS")


if __name__ == "__main__":
    main()
