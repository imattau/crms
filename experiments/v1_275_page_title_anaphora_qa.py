"""Check exact-title pronoun resolution, review, and open ambiguity handling."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import _natural_who_evidence
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def chat_command(project: Path, index: Path, state: Path) -> list[str]:
    return [
        sys.executable, str(project / "crms_chat.py"),
        "--index", str(index),
        "--knowledge", str(state / "knowledge.json"),
        "--rules", str(state / "rules.json"),
        "--math", str(state / "math.json"),
        "--translations", str(state / "translations.json"),
        "--dialogue-state", str(state / "dialogue.json"),
        "--rule-session", str(state / "rule-session.json"),
        "--candidate-session", str(state / "candidate-session.json"),
    ]


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="crms-title-anaphora-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "python-language", "Python (programming language)",
            "It was made by a Dutch programmer named Guido van Rossum in 1991.",
            "wiki/python-language")
        index.add_document(
            "monty-film", "Monty Python and the Holy Grail",
            "Monty Python and the Holy Grail is the second movie made by Monty Python.",
            "wiki/monty-film")
        index.add_document(
            "ruby-language", "Ruby (programming language)",
            "It was made by a programmer named Yukihiro Matsumoto.",
            "wiki/ruby-language")
        evidence = _natural_who_evidence(index, "Who made Python?")
        require(evidence is not None
                and evidence.get("title") == "Python (programming language)"
                and evidence.get("realized_answer", {}).get("text")
                    == "Guido van Rossum made Python.",
                f"page-title antecedent did not beat lexical decoy: {evidence}")
        require(evidence["text"] in index.resolve_citation(evidence["citation"]),
                "realized answer lost its exact source citation")
        require(not CRMSKnowledgeBase().facts(),
                "page-title realization changed the knowledge store before review")
        index.close()

        state = root / "state"
        state.mkdir()
        CRMSKnowledgeBase().save(state / "knowledge.json")
        run = subprocess.run(
            chat_command(project, index_path, state),
            input=("Who made Python?\n"
                   "accept candidate 1\n"
                   "Who made Ruby?\n"
                   "accept candidate 1\n"
                   "Who made Python?\n/quit\n"),
            text=True, capture_output=True, timeout=60, check=False)
        require(run.returncode == 0,
                f"chat exited {run.returncode}: {run.stderr}")
        require("Guido van Rossum made Python." in run.stdout
                and "source claim available for review" in run.stdout
                and "Accepted positive fact: Guido van Rossum — made → Python."
                    in run.stdout
                and "Yukihiro Matsumoto made Ruby." in run.stdout
                and "Accepted positive fact: Yukihiro Matsumoto — made → Ruby."
                    in run.stdout,
                f"source-backed review lifecycle failed: {run.stdout}")
        learned = CRMSKnowledgeBase.load(state / "knowledge.json")
        answer = learned.ask("Who made Python?")
        require(answer.status == "answered"
                and answer.answer == "Guido van Rossum",
                f"accepted question example did not answer: {answer}")
        learned.add_fact("Tess Morrow", "made", "Amber", "heldout-language-check")
        transferred = learned.ask("Who made Amber?")
        require(transferred.status == "answered"
                and transferred.answer == "Tess Morrow",
                f"two reviewed page examples did not license frame transfer: {transferred}")
        unlicensed = learned.ask("Who created Amber?")
        require(unlicensed.status == "unknown",
                f"unlearned relation wording transferred unexpectedly: {unlicensed}")

        ambiguous_path = root / "ambiguous.sqlite"
        ambiguous = CRMSSQLiteResearchIndex(ambiguous_path)
        ambiguous.add_document(
            "python-language", "Python (programming language)",
            "It was made by a Dutch programmer named Guido van Rossum.",
            "wiki/python-language")
        ambiguous.add_document(
            "python-myth", "Python (mythology)",
            "It was made by Hephaestus.", "wiki/python-mythology")
        found = _natural_who_evidence(ambiguous, "Who made Python?")
        require(found is not None and found.get("ambiguous_pages")
                and len(found["ambiguous_pages"]) == 2,
                f"conflicting title-grounded answers were not kept ambiguous: {found}")
        ambiguous.close()
        ambiguous_state = root / "ambiguous-state"
        ambiguous_state.mkdir()
        CRMSKnowledgeBase().save(ambiguous_state / "knowledge.json")
        ambiguous_run = subprocess.run(
            chat_command(project, ambiguous_path, ambiguous_state),
            input="Who made Python?\n/quit\n",
            text=True, capture_output=True, timeout=60, check=False)
        require(ambiguous_run.returncode == 0
                and "Which page do you mean?" in ambiguous_run.stdout
                and "Monty Python and the Holy Grail" not in ambiguous_run.stdout,
                f"ambiguous page intent was not clarified: {ambiguous_run.stdout}")

    print("page-title anaphora diagnostic: PASS")
    print("exact-title evidence, source citation, lexical decoy, review-before-storage, varied-entity frame transfer, relation-wording boundary, and ambiguous-page abstention: PASS")


if __name__ == "__main__":
    main()
