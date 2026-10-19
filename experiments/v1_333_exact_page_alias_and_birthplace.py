"""Exercise exact-title surname aliases and structured birthplace evidence."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-333-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "alan-turing", "Alan Turing",
            "Infobox scientist\n"
            "birth_place = Maida Vale, London\n\n"
            "Alan Turing was an English mathematician and computer scientist. "
            "During World War II, Turing worked at Bletchley Park. "
            "Turing did not work at Cambridge.",
            "wiki/simplewiki/Alan Turing")
        index.add_document(
            "marie-curie", "Marie Curie",
            "Infobox scientist\n"
            "birth_place = Warsaw, Congress Poland, Russian Empire\n\n"
            "Marie Curie was a physicist and chemist.",
            "wiki/simplewiki/Marie Curie")
        index.close()

        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        state = root / "state"
        state.mkdir()
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(index_path), "--index-read-only",
            "--dialogue-state", str(state / "dialogue.json"),
            "--rules", str(state / "rules.json"),
            "--rule-session", str(state / "rule-session.json"),
            "--candidate-session", str(state / "candidates.json"),
            "--math", str(state / "math.json"),
            "--translations", str(state / "translations.json"),
        ]
        run = subprocess.run(
            command,
            input=("Did Alan Turing work at Bletchley Park?\n"
                   "Did Alan Turing work at Oxford?\n"
                   "Did Alan Turing work at Cambridge?\n"
                   "Where was Marie Curie born?\n/quit\n"),
            text=True, capture_output=True, cwd=state, timeout=60)
        require(run.returncode == 0,
                f"chat failed: {run.stderr}\n{run.stdout}")
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in run.stdout.splitlines() if "CRMS>" in line]
        require(len(replies) == 4, f"unexpected chat replies: {replies}")
        require("source states yes" in replies[0].casefold()
                and "Turing worked at Bletchley Park." in replies[0],
                f"title-local surname evidence was not recognized: {replies[0]}")
        require("can't answer yes or no" in replies[1].casefold(),
                f"unattested object received a polar answer: {replies[1]}")
        require("source states no" in replies[2].casefold()
                and "Turing did not work at Cambridge." in replies[2],
                f"explicit negative evidence was not recognized: {replies[2]}")
        require("birthplace as Warsaw, Congress Poland, Russian Empire"
                in replies[3],
                f"exact-title birthplace field was not realized: {replies[3]}")
        require("quoted evidence" in replies[3].casefold()
                and "not an accepted fact" in replies[3].casefold(),
                f"structured metadata lost its evidence status: {replies[3]}")

    print("exact-title local surname alias: PASS")
    print("wrong-object polar abstention: PASS")
    print("explicit negative polarity: PASS")
    print("structured birthplace field with citation: PASS")


if __name__ == "__main__":
    main()
