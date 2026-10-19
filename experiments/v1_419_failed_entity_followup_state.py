"""A failed entity switch must not leave a stale answer for "why?"."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-failed-followup-") as folder:
        root = Path(folder)
        docs = root / "docs"
        docs.mkdir()
        (docs / "travel.txt").write_text(
            "The Eiffel Tower is an iron tower in Paris, France.\n\n"
            "The Colosseum is an amphitheatre in Rome, Italy.\n",
            encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(docs)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        first = dialogue.turn("What is the Eiffel Tower?",
                              research_index=index)
        require(first.status == "sources_found" and "Eiffel Tower" in first.text,
                f"initial Eiffel answer was not grounded: {first!r}")
        switched = dialogue.turn("And the Colosseum?", research_index=index)
        require(switched.status == "sources_found" and "amphitheatre" in switched.text,
                f"named topic switch did not return Colosseum evidence: {switched!r}")
        failed = dialogue.turn("And Italy?", research_index=index)
        require(failed.status == "unknown",
                f"unsupported follow-up should be explicit: {failed!r}")
        require(dialogue.topic_entity == "Colosseum",
                "failed follow-up should retain the last cited topic for repair")
        require(dialogue.last_question is None,
                "failed entity substitution left a stale answer explainable")

        explanation = dialogue.turn("Why?", research_index=index)
        require(explanation.status == "unknown"
                and "no previous grounded answer" in explanation.text.casefold()
                and "amphitheatre" not in explanation.text
                and "iron tower" not in explanation.text,
                f"why? explained a stale answer after failed follow-up: {explanation!r}")

        # Exercise the same sequence through the user-facing CLI with every
        # mutable file and the research index confined to this scratch folder.
        options: list[str] = []
        for name in ("knowledge", "math", "rules", "dialogue-state",
                     "rule-session", "candidate-session", "math-session",
                     "translations", "translation-session"):
            options.extend(("--" + name, str(root / f"{name}.json")))
        command = [sys.executable, str(Path(__file__).resolve().parents[1]
                                        / "crms_chat.py"), *options,
                   "--feedback-db", str(root / "feedback.sqlite3"),
                   "--index", str(root / "chat-research.sqlite")]
        run = subprocess.run(
            command,
            input=(f"/source-dir {docs}\nWhat is the Eiffel Tower?\n"
                   "And the Colosseum?\nAnd Italy?\nWhy?\n/quit\n"),
            text=True, capture_output=True, timeout=120,
            env=os.environ.copy(), check=False)
        require(run.returncode == 0,
                f"scratch chat failed ({run.returncode}): {run.stderr}\n{run.stdout}")
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in run.stdout.splitlines() if "CRMS>" in line]
        require(len(replies) == 4,
                f"expected four CLI replies, got {len(replies)}:\n{run.stdout}")
        require("amphitheatre" in replies[1],
                f"CLI topic switch missed the Colosseum: {replies[1]!r}")
        require("could not verify" in replies[2].casefold(),
                f"CLI did not disclose the failed Italy follow-up: {replies[2]!r}")
        require("no previous grounded answer" in replies[3].casefold()
                and "amphitheatre" not in replies[3]
                and "iron tower" not in replies[3],
                f"CLI why? replayed evidence for an earlier entity: {replies[3]!r}")

    print("failed entity follow-up preserves topic but clears stale answer: PASS")
    print("why? does not replay the prior entity's answer: PASS")
    print("full CLI topic-switch and failed-follow-up sequence: PASS")


if __name__ == "__main__":
    main()
