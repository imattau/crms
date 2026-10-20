"""Grounded realization for subject-gap questions over explicit source clauses.

Run with: python3 experiments/v1_539_natural_subject_gap_realization.py
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

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def source(text: str, *, context: str = "assertion", name: str = "record"):
    return {
        "text": text,
        "context_kind": context,
        "title": name,
        "citation": f"{name}#sentence",
        "document_id": name,
    }


def main() -> None:
    question = "What body of water crosses Nacre City 0133?"
    passive = source(
        "Nacre City 0133 is crossed by Serein River 0133.")
    realized = CRMSKnowledgeBase._realize_question_from_passive_source(
        question, [passive], [])
    require(realized is not None and realized["text"] ==
            "Serein River 0133 crosses Nacre City 0133."
            and realized["citation"] == passive["citation"]
            and realized["stored_as_fact"] is False,
            f"passive subject-gap realization failed: {realized!r}")

    active = source("Serein River 0133 crosses Nacre City 0133.")
    active_result = CRMSKnowledgeBase._realize_question_from_passive_source(
        question, [active], [])
    require(active_result is not None and active_result["text"] ==
            "Serein River 0133 crosses Nacre City 0133.",
            f"active subject-gap realization failed: {active_result!r}")

    for bad_question, evidence in (
            ("What body of water crosses Nacre City 0134?", [passive]),
            ("What body of water flows through Nacre City 0133?", [passive]),
            (question, [source(
                "Nacre City 0133 is not crossed by Serein River 0133.")]),
            (question, [source(
                "Nacre City 0133 is crossed by Serein River 0133, not Lumen River.")]),
            (question, [source(
                "Nacre City 0133 is crossed by Serein River 0133.",
                context="example")]),
    ):
        rejected = CRMSKnowledgeBase._realize_question_from_passive_source(
            bad_question, evidence, [])
        require(rejected is None,
                f"unsafe subject-gap answer was realized for {bad_question!r}: "
                f"{rejected!r}")

    ambiguous = CRMSKnowledgeBase._realize_question_from_passive_source(
        question,
        [passive, source(
            "Nacre City 0133 is crossed by Lumen River 0133.",
            name="second-record")], [])
    require(ambiguous is None,
            f"conflicting explicit agents were resolved by order: {ambiguous!r}")

    scratch = Path(tempfile.mkdtemp(prefix="crms-subject-gap-", dir="/tmp"))
    try:
        docs = scratch / "docs"
        docs.mkdir()
        (docs / "crossing.txt").write_text(
            "Nacre City 0133 is crossed by Serein River 0133.\n",
            encoding="utf-8")
        options: list[str] = []
        for name in ("knowledge", "math", "rules", "dialogue-state",
                     "rule-session", "candidate-session", "math-session",
                     "translations", "translation-session"):
            options.extend(("--" + name, str(scratch / f"{name}.json")))
        command = [sys.executable, str(PROJECT / "crms_chat.py"), *options,
                   "--index", str(scratch / "research.sqlite")]
        turns = (f"/source-dir {docs}\n"
                 + question + "\n"
                 + "What body of water crosses Nacre City 0134?\n"
                 + "/quit\n")
        result = subprocess.run(
            command, input=turns, text=True, capture_output=True,
            timeout=120, check=False, env=os.environ.copy())
        require(result.returncode == 0,
                f"chat exited {result.returncode}: {result.stderr}\n"
                f"{result.stdout}")
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in result.stdout.splitlines() if "CRMS>" in line]
        require(len(replies) == 2,
                f"expected two chat replies, got {len(replies)}: {result.stdout}")
        require("Serein River 0133 crosses Nacre City 0133." in replies[0]
                and "[Source: crossing.txt; quoted evidence, not an accepted fact]"
                in replies[0],
                f"fresh chat did not realize and cite the subject-gap answer: "
                f"{replies[0]!r}")
        require("Serein River 0133 crosses Nacre City 0133." not in replies[1]
                and ("won't guess" in replies[1].casefold()
                     or "does not support a grounded answer" in replies[1].casefold()),
                f"wrong numbered entity did not abstain: {replies[1]!r}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print("active and passive subject-gap realization with exact citations: PASS")
    print("wrong entity, predicate, polarity, example, and conflict controls: PASS")
    print("fresh chat answers and cites without accepting a fact: PASS")


if __name__ == "__main__":
    main()
