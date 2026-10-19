"""Check a natural-language author question against passive source wording."""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_who_evidence
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-290-") as directory:
        index = CRMSSQLiteResearchIndex(Path(directory) / "research.sqlite")
        index.add_document(
            "fixture:frankenstein", "Frankenstein",
            "Frankenstein; or, The Modern Prometheus is a gothic novel "
            "written by Mary Shelley.", "fixture://Frankenstein")
        index.add_document(
            "fixture:mona-lisa", "Mona Lisa",
            "The Mona Lisa (also known as La Gioconda or La Joconde) is a "
            "16th-century portrait, painted in oil by Leonardo da Vinci "
            "during the Renaissance in Florence, Italy.",
            "fixture://Mona-Lisa")
        index.add_document(
            "fixture:hamlet", "Hamlet",
            "Hamlet was written by William Shakespeare.",
            "fixture://Hamlet")
        knowledge = CRMSKnowledgeBase()
        cases = (
            ("Who wrote Frankenstein?", "Mary Shelley wrote Frankenstein.",
             "written by Mary Shelley."),
            ("Who painted the Mona Lisa?", "Leonardo da Vinci painted Mona Lisa.",
             "painted in oil by Leonardo da Vinci"),
        )
        for question, expected, source_phrase in cases:
            result = knowledge.research(question, index)
            evidence = _natural_who_evidence(
                index, question, result.query_expansions or [])
            assert evidence is not None
            realized = evidence["realized_answer"]
            assert realized["text"] == expected
            assert source_phrase in evidence["text"]
            assert realized["citation"]
            assert not realized["stored_as_fact"]

        unknown = knowledge.research("Who wrote The Lost Archive?", index)
        unknown_evidence = _natural_who_evidence(
            index, "Who wrote The Lost Archive?",
            unknown.query_expansions or [])
        assert unknown_evidence is None
        index.close()

        state = Path(directory) / "state"
        state.mkdir()
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(Path(directory) / "research.sqlite"),
            "--knowledge", str(state / "knowledge.json"),
            "--dialogue-state", str(state / "dialogue.json"),
            "--candidate-session", str(state / "candidates.json"),
            "--rule-session", str(state / "rules.json"),
            "--math", str(state / "math.json"),
            "--math-session", str(state / "math-session.json"),
            "--translations", str(state / "translations.json"),
            "--translation-session", str(state / "translation-session.json"),
        ]
        chat = subprocess.run(
            command,
            input=("Who wrote Frankenstein?\n"
                   "Who wrote Hamlet?\n"
                   "Who painted the Mona Lisa?\n"
                   "/pending-candidates\n/quit\n"),
            text=True, capture_output=True, timeout=30, check=False)
        assert chat.returncode == 0, chat.stderr + chat.stdout
        assert ("Mary Shelley wrote Frankenstein." in chat.stdout
                or "written by Mary Shelley" in chat.stdout), chat.stdout
        assert ("William Shakespeare wrote Hamlet." in chat.stdout
                or "Hamlet was written by William Shakespeare." in chat.stdout), chat.stdout
        assert ("Leonardo da Vinci painted Mona Lisa." in chat.stdout
                or "painted in oil by Leonardo da Vinci" in chat.stdout), chat.stdout
        assert "couldn't identify one paper" not in chat.stdout
        review_notices = (
            chat.stdout.count("source claim available for review")
            + chat.stdout.count("source claims available for review"))
        assert review_notices == 3, chat.stdout
        assert "Review candidate 1:" not in chat.stdout
        assert "1. Mary Shelley — written → Frankenstein" in chat.stdout
        assert "2. William Shakespeare — written → Hamlet" in chat.stdout
        assert "3. Leonardo da Vinci — painted → Mona Lisa" in chat.stdout
        print("PASS: irregular and reduced-passive writer questions use cited "
              "source evidence, not accepted facts")
        print("PASS: absent title abstains; generic book title does not enter "
              "the paper-only author route")
        print("PASS: chat keeps the direct answer concise while review details "
              "remain available on request")


if __name__ == "__main__":
    main()
