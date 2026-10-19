"""Check WHERE evidence roles across direct and bounded inverted clauses."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_nl_gate import gate_quoted_evidence


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    positives = [
        ("Where is Mount Everest located?",
         "Mount Everest is located in the Himalayas."),
        ("Where does Alan Turing work?",
         "Alan Turing worked at Bletchley Park."),
        ("Where is Mount Everest?",
         "In the Himalayas lies Mount Everest."),
        ("Where did Alan Turing work?",
         "Bletchley Park is where Alan Turing worked."),
    ]
    negatives = [
        ("Where is Italy?",
         "The Colosseum is an amphitheatre in Rome, Italy."),
        ("Where is Italy?",
         "Italy is where the Colosseum stands."),
        ("Where does Alan Turing work?",
         "Alan Turing designed the Turing machine."),
    ]
    for question, sentence in positives:
        result = gate_quoted_evidence(question, [{"text": sentence}])
        require(result["status"] == "accepted",
                f"valid WHERE wording was rejected: {question!r} / {sentence!r}: {result!r}")
    for question, sentence in negatives:
        result = gate_quoted_evidence(question, [{"text": sentence}])
        require(result["status"] == "rejected",
                f"wrong-role or unrelated WHERE evidence was accepted: {question!r} / "
                f"{sentence!r}: {result!r}")
    print("subject-first, locative inversion, and where-clause evidence: PASS")
    print("destination-only and non-location sentences are rejected: PASS")


if __name__ == "__main__":
    main()
