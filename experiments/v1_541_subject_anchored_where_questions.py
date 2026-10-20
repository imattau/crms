"""Test subject- and predicate-anchored locative questions in chat.

Run with: python3 experiments/v1_541_subject_anchored_where_questions.py
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (  # noqa: E402
    _explicit_subject_locative_evidence,
    _natural_where_action_lookup,
)
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_index(path: Path, rows: tuple[tuple[str, str], ...]
               ) -> CRMSSQLiteResearchIndex:
    index = CRMSSQLiteResearchIndex(path)
    for document_id, text in rows:
        index.add_document(
            document_id, document_id.replace("-", " ").title(), text,
            f"fixture://{document_id}")
    return index


def main() -> None:
    question = "Where does the Serein River 0133 flow?"
    require(_natural_where_action_lookup(question)
            == ("Serein River 0133", "flow"),
            "where-action frame did not retain its subject and predicate")
    require(_natural_where_action_lookup(
                "Where does it flow?") is None,
            "raw pronoun was accepted as an entity key")

    scratch = Path(tempfile.mkdtemp(prefix="crms-where-action-", dir="/tmp"))
    try:
        index_path = scratch / "research.sqlite"
        index = make_index(index_path, (
            ("serein", "The Serein River 0133 flows through Nacre City 0133."),
            ("decoy", "Nacre City 0133 is crossed by Serein River 0133."),
        ))
        try:
            entity, predicate = _natural_where_action_lookup(question)
            evidence = _explicit_subject_locative_evidence(
                index, entity, predicate)
            require(evidence is not None
                    and evidence["text"]
                        == "The Serein River 0133 flows through Nacre City 0133."
                    and evidence["locative_phrase"] == "through Nacre City 0133"
                    and index.resolve_citation(evidence["citation"])
                        == evidence["text"],
                    f"grounded locative evidence was not cited: {evidence!r}")
            require(_explicit_subject_locative_evidence(
                        index, "Serein River 0134", "flow") is None,
                    "wrong numbered subject matched a nearby location")
            require(_explicit_subject_locative_evidence(
                        index, "Serein River 0133", "run") is None,
                    "an unlicensed predicate synonym was assumed")
            require(_explicit_subject_locative_evidence(
                        index, "Nacre City 0133", "flow") is None,
                    "an entity in object position was promoted to subject")
        finally:
            index.close()

        ambiguous = make_index(scratch / "ambiguous.sqlite", (
            ("serein-a", "The Serein River 0133 flows through Nacre City 0133."),
            ("serein-b", "The Serein River 0133 flows through Lumen City 0133."),
        ))
        try:
            alternatives = _explicit_subject_locative_evidence(
                ambiguous, "Serein River 0133", "flow")
            require(alternatives is not None
                    and alternatives.get("ambiguous") is True
                    and {item["locative_phrase"]
                         for item in alternatives["alternatives"]}
                        == {"through Nacre City 0133",
                            "through Lumen City 0133"},
                    f"distinct locations were not preserved: {alternatives!r}")
        finally:
            ambiguous.close()

        docs = scratch / "docs"
        docs.mkdir()
        (docs / "rivers.txt").write_text(
            "The Serein River 0133 flows through Nacre City 0133.\n"
            "Nacre City 0133 is crossed by Serein River 0133.\n",
            encoding="utf-8")
        options: list[str] = []
        for name in ("knowledge", "math", "rules", "dialogue-state",
                     "rule-session", "candidate-session", "math-session",
                     "translations", "translation-session"):
            options.extend(("--" + name, str(scratch / f"{name}.json")))
        command = [sys.executable, str(PROJECT / "crms_chat.py"), *options,
                   "--index", str(scratch / "chat.sqlite")]
        turns = "\n".join((
            f"/source-dir {docs}",
            question,
            "Where does the Serein River 0134 flow?",
            "Where does the Serein River 0133 run?",
            "/quit", ""))
        run = subprocess.run(
            command, input=turns, text=True, capture_output=True,
            timeout=120, check=False, env=os.environ.copy())
        require(run.returncode == 0,
                f"chat exited {run.returncode}: {run.stderr}\n{run.stdout}")
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in run.stdout.splitlines() if "CRMS>" in line]
        require(len(replies) == 3,
                f"expected three replies, got {len(replies)}: {run.stdout}")
        require("The Serein River 0133 flows through Nacre City 0133." in replies[0]
                and "[Source: rivers.txt; quoted evidence, not an accepted fact]"
                in replies[0],
                f"normal chat did not answer and cite the locative fact: {replies[0]!r}")
        require("Nacre City 0133" not in replies[1]
                and ("couldn't find" in replies[1].casefold()
                     or "won't guess" in replies[1].casefold()),
                f"wrong numbered entity did not abstain: {replies[1]!r}")
        require("Nacre City 0133" not in replies[2]
                and ("couldn't find" in replies[2].casefold()
                     or "won't guess" in replies[2].casefold()),
                f"unlicensed run/flow synonym did not abstain: {replies[2]!r}")

        multi_docs = scratch / "multi-location-docs"
        multi_docs.mkdir()
        (multi_docs / "routes.txt").write_text(
            "The Serein River 0133 flows through Nacre City 0133.\n"
            "The Serein River 0133 flows through Lumen City 0133.\n",
            encoding="utf-8")
        multi_options: list[str] = []
        for name in ("knowledge", "math", "rules", "dialogue-state",
                     "rule-session", "candidate-session", "math-session",
                     "translations", "translation-session"):
            multi_options.extend(("--" + name,
                                  str(scratch / f"multi-{name}.json")))
        multi_options.extend(("--index", str(scratch / "multi-chat.sqlite")))
        multi_command = [sys.executable, str(PROJECT / "crms_chat.py"),
                         *multi_options]
        multi_run = subprocess.run(
            multi_command,
            input=f"/source-dir {multi_docs}\n{question}\n/quit\n",
            text=True, capture_output=True, timeout=120, check=False,
            env=os.environ.copy())
        require(multi_run.returncode == 0,
                f"multi-location chat exited {multi_run.returncode}: "
                f"{multi_run.stderr}\n{multi_run.stdout}")
        multi_replies = [line.split("CRMS>", 1)[1].strip()
                         for line in multi_run.stdout.splitlines()
                         if "CRMS>" in line]
        require(len(multi_replies) == 1
                and "multiple source statements" in multi_replies[0].casefold()
                and "Nacre City 0133" in multi_replies[0]
                and "Lumen City 0133" in multi_replies[0]
                and multi_replies[0].count("[Source: routes.txt") == 2,
                f"chat did not report both cited locations: {multi_replies!r}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print("exact subject, inflected predicate, and explicit locative phrase: PASS")
    print("wrong entity, wrong verb, object-role, and multi-location controls: PASS")
    print("fresh chat answer is cited and remains unaccepted knowledge: PASS")


if __name__ == "__main__":
    main()
