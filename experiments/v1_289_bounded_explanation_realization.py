"""Keep explanation replies short and tied to the asked-about clause."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-explanation-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "plant-page", "Plant food",
            "Plant food\nPlants are producers that make their food from "
            "photosynthesis.\nConsumers eat plants and other animals.\n"
            "Food chains connect organisms in an ecosystem.\nReferences",
            "plant-page.txt")
        index.add_document(
            "newton-page", "Newton's laws",
            "Newton's laws\nIsaac Newton developed three laws of motion.\n"
            "First law: an object remains at rest or in uniform motion until "
            "acted upon by a net force.\nFrom the statement, Newton's first "
            "law defines force and inertia.\nSecond law: force equals mass "
            "times acceleration.\nWe can express Newton's second law in "
            "terms of momentum.",
            "newton-page.txt")
        index.close()

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--math", str(root / "math.json"),
            "--math-session", str(root / "math-session.json"),
            "--translations", str(root / "translations.json"),
            "--translation-session", str(root / "translation-session.json"),
            "--dialogue-state", str(root / "dialogue.json"),
        ]
        result = subprocess.run(
            command,
            input=("How do plants make food?\n"
                   "Explain Newton's first law in simple terms.\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=45)
        if result.returncode:
            raise SystemExit(f"chat failed: {result.stderr}")
        chunks = result.stdout.split("you> ")[1:]
        if len(chunks) != 3:
            raise SystemExit(f"unexpected chat turns: {result.stdout}")
        plant, newton = (chunk.strip() for chunk in chunks[:2])
        if ("Plants are producers that make their food from photosynthesis."
                not in plant
                or "Consumers eat plants" in plant
                or "References" in plant or len(plant) > 500):
            raise SystemExit(f"plant answer was not sentence-bounded: {plant}")
        if ("Newton's first law defines force and inertia." not in newton
                or "second law" in newton.casefold()
                or len(newton) > 500):
            raise SystemExit(f"ordinal-specific explanation was noisy: {newton}")

    print("bounded explanation realization: PASS")
    print("wiki-like single-newline pages produce short cited extracts; an "
          "ordinal question stays on the requested law")


if __name__ == "__main__":
    main()
