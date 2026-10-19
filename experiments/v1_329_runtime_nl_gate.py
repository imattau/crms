"""Runtime regression checks for the quoted-evidence natural-language gate.

Run with: python3 experiments/v1_329_runtime_nl_gate.py
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

from crms_nl_gate import gate_quoted_evidence  # noqa: E402


def main() -> None:
    candidates = [
        {"text": "Albert Einstein won the Nobel Prize in Physics in 1921.",
         "title": "Einstein"},
        {"text": "Marie Curie won two Nobel Prizes.", "title": "Curie"},
    ]
    decision = gate_quoted_evidence(
        "How many Nobel Prizes did Marie Curie win?", candidates)
    assert decision["status"] == "accepted"
    assert decision["evidence"]["title"] == "Curie"

    decision = gate_quoted_evidence(
        "How tall is Mount Everest?",
        [{"text": "Mount Everest is located in the Himalayas."}])
    assert decision["status"] == "rejected"
    decision = gate_quoted_evidence(
        "Where is Kilimanjaro?",
        [{"text": "Mount Kilimanjaro is 5895 metres tall."}])
    assert decision["status"] == "rejected"
    decision = gate_quoted_evidence(
        "Who is the parent of Dan?",
        [{"text": "Dan is a parent of Eve."}])
    assert decision["status"] == "rejected"
    decision = gate_quoted_evidence(
        "Who is the parent of Dan?",
        [{"text": "Ann is a parent of Dan."}])
    assert decision["status"] == "accepted"

    created_sentence = [{"text": "Guido van Rossum created Python."}]
    assert gate_quoted_evidence("Who made Python?", created_sentence)[
        "status"] == "rejected"
    licenses = [
        {"kind": "licensed_predicate", "text": "made",
         "evidence": "created", "sources": ["frame-example-1", "frame-example-2"]},
        {"kind": "licensed_predicate", "text": "created",
         "evidence": "created", "sources": ["frame-example-1", "frame-example-2"]},
    ]
    assert gate_quoted_evidence(
        "Who made Python?", created_sentence,
        licensed_predicates=licenses)["status"] == "accepted"
    assert gate_quoted_evidence(
        "Who crafted Python?", created_sentence,
        licensed_predicates=licenses)["status"] == "rejected"

    institute_question = (
        "At which institute did researchers study quartz field 0266?")
    institute_evidence = [
        {"text": "Researchers at the Meridian Institute 0266 studied quartz field 0266."},
        {"text": "Researcher 0303 studied quartz field 0266 in 2046."},
    ]
    decision = gate_quoted_evidence(institute_question, institute_evidence)
    assert decision["status"] == "accepted", decision
    assert "Meridian Institute 0266" in decision["evidence"]["text"]
    numbered_distractors = [
        {"text": "Researchers at the Meridian Institute 0266 studied quartz field 0266."},
        *({"text": f"Researchers at the Meridian Institute 000{i} studied quartz field 000{i}."}
          for i in range(10)),
        {"text": "Researcher 0266 studied quartz field 0229 in 2049."},
    ]
    decision = gate_quoted_evidence(institute_question, numbered_distractors)
    assert decision["status"] == "accepted", decision
    assert "Meridian Institute 0266" in decision["evidence"]["text"]

    scratch = Path(tempfile.mkdtemp(prefix="crms-nl-gate-", dir="/tmp"))
    try:
        docs = scratch / "docs"
        docs.mkdir()
        (docs / "facts.txt").write_text(
            "Marie Curie won two Nobel Prizes.\n"
            "Albert Einstein won the Nobel Prize in Physics in 1921.\n"
            "Mount Everest is located in the Himalayas.\n"
            "Mount Everest is 8849 metres tall.\n"
            "Guido van Rossum created Python.\n"
            "The Thames flows through London.\n"
            "The Amazon River flows through Brazil.\n"
            "Researchers at the Meridian Institute 0266 studied quartz field 0266.\n"
            "Researcher 0303 studied quartz field 0266 in 2046.\n",
            encoding="utf-8")
        options = []
        for name in ("knowledge", "math", "rules", "dialogue-state",
                     "rule-session", "candidate-session", "math-session",
                     "translations", "translation-session"):
            options.extend(("--" + name, str(scratch / f"state-{name}.json")))
        command = [sys.executable, str(PROJECT / "crms_chat.py"), *options,
                   "--index", str(scratch / "research.sqlite")]
        questions = (
            "How many Nobel Prizes did Marie Curie win?",
            "How tall is Mount Everest?",
            "Where is Everest located?",
            "Where is Everest?",
            "Who created Python?",
            "How tall is Marie Curie?",
            "Does the Thames flow through London?",
            "Does the Amazon River flow through Peru?",
            "Who made Python?",
            institute_question,
        )
        result = subprocess.run(
            command,
            input=f"/source-dir {docs}\n" + "\n".join(questions)
            + "\n/quit\n",
            text=True, capture_output=True, timeout=120,
            env=os.environ.copy(), check=False)
        assert result.returncode == 0, result.stderr
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in result.stdout.splitlines() if "CRMS>" in line]
        assert len(replies) == len(questions), replies
        assert "Marie Curie won two Nobel Prizes." in replies[0], replies[0]
        assert "Albert Einstein" not in replies[0], replies[0]
        assert "8849 metres tall" in replies[1], replies[1]
        assert "Mount Everest is located in the Himalayas." in replies[2], replies[2]
        assert "Mount Everest is located in the Himalayas." in replies[3], replies[3]
        assert "Guido van Rossum created Python." in replies[4], replies[4]
        assert "won't guess" in replies[5], replies[5]
        assert "source states yes" in replies[6].casefold(), replies[6]
        assert "can't answer yes or no" in replies[7].casefold(), replies[7]
        assert "can't answer with 'made' yet" in replies[8].casefold(), replies[8]
        assert "created → Python" in replies[8], replies[8]
        assert "Meridian Institute 0266" in replies[9], replies[9]
        assert "multiple equally supported" not in replies[9], replies[9]
        # A rejected near match is useful context, but must remain visibly
        # labelled as non-answer evidence and must not alter later answers.
        assert "Closest source sentence:" in result.stdout
        assert "may not answer your question" in result.stdout
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("OK: runtime gate selects grounded matches and abstains on mismatches")


if __name__ == "__main__":
    main()
