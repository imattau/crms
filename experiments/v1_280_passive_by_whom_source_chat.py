"""Exercise passive `by whom` question realization in the terminal chat."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-passive-by-whom-") as temp:
        root = Path(temp)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        try:
            index.add_document(
                "python-history", "Python history",
                "Python was created by Guido van Rossum.",
                "fixture://python-history")
            index.add_document(
                "seine", "Seine",
                "The Seine rises near Dijon in eastern central France, and "
                "flows through Paris and into the English Channel. "
                "The Seine is a river in France.",
                "fixture://seine")
            index.add_document(
                "river-cole", "River Cole",
                "The River Cole may mean the River Cole in Birmingham or the "
                "River Cole in Wiltshire.",
                "fixture://river-cole")
        finally:
            index.close()

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(root / "knowledge.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--math-session", str(root / "math-session.json"),
            "--translations", str(root / "translations.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        result = subprocess.run(
            command,
            input=("Python was created by whom?\n"
                   "Which river flows through Paris?\n"
                   "What river flows through Paris?\n"
                   "Which river flows through Nacre City?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(result.returncode == 0,
                f"chat failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        require("Guido van Rossum created Python." in result.stdout,
                f"passive question did not get a controlled answer: {result.stdout}")
        require("[Source: Python history; quoted evidence, not an accepted fact]"
                in result.stdout,
                f"realized answer lost its source label: {result.stdout}")
        require("1 source claim available for review" in result.stdout,
                f"source-derived claim was not left for review: {result.stdout}")
        require("The Seine fits" in result.stdout
                and result.stdout.count("The Seine fits") == 2
                and "flows through Paris" in result.stdout
                and ("identify it as a river" in result.stdout
                     or "classifies it as a river" in result.stdout)
                and "Sources: Seine" in result.stdout
                and "The River Cole fits" not in result.stdout,
                f"typed relation answer used a lexical decoy or lacked type evidence: {result.stdout}")
        require("I couldn't find source sentences that support a river flows "
                "through Nacre City" in result.stdout,
                f"typed relation query without exact evidence did not abstain: {result.stdout}")
        require(result.stdout.count("Review candidate ") == 2,
                f"review details were duplicated or hidden unexpectedly: {result.stdout}")

        accepted_root = root / "accepted"
        accepted_root.mkdir()
        accepted_command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(accepted_root / "knowledge.json"),
            "--dialogue-state", str(accepted_root / "dialogue.json"),
            "--candidate-session", str(accepted_root / "candidates.json"),
            "--rule-session", str(accepted_root / "rules.json"),
            "--math", str(accepted_root / "math.json"),
            "--translations", str(accepted_root / "translations.json"),
        ]
        review = subprocess.run(
            accepted_command,
            input=("Which river flows through Paris?\n"
                   "Which river flows through Nacre City?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(review.returncode == 0,
                f"candidate proposal chat failed: {review.stderr}\n{review.stdout}")
        require(review.stdout.count("Review candidate ") == 2,
                f"typed source claims were not queued for review: {review.stdout}")
        require("I couldn't find source sentences that support a river flows "
                "through Nacre City" in review.stdout,
                f"unrelated abstention changed the answer: {review.stdout}")
        accepted = subprocess.run(
            accepted_command,
            input=("accept candidate 1\naccept candidate 1\n"
                   "Which river flows through Paris?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(accepted.returncode == 0,
                f"candidate acceptance chat failed: {accepted.stderr}\n{accepted.stdout}")
        require(accepted.stdout.count("Accepted positive fact:") == 2,
                f"review did not store both cited relation and type facts: {accepted.stdout}")
        require("River Cole may mean" not in accepted.stdout,
                f"accepting a claim replaced the reviewed answer with a lexical decoy: {accepted.stdout}")
        require("supported by accepted facts" in accepted.stdout
                and "Review candidate" not in accepted.stdout,
                f"accepted claims were not used on the repeat question: {accepted.stdout}")
        from crms_knowledge import CRMSKnowledgeBase
        stored = CRMSKnowledgeBase.load(accepted_root / "knowledge.json")
        try:
            facts = {(fact.subject, fact.relation, fact.object)
                     for fact in stored.facts()}
            require(("The Seine", "flows through", "Paris") in facts
                    and ("The Seine", "is-a", "river") in facts,
                    f"accepted review claims were not reintegrated: {facts}")
            relation_examples = [
                (key, examples) for key, examples
                in stored._fact_pattern_examples.items()
                if key[1] == ("flows", "through")]
            require(len(relation_examples) == 1,
                    "accepted source wording did not become a fact-pattern example")
            frame_examples = [
                key for key in stored._question_examples
                if tuple(json.loads(key[0])) == ("flows", "through")]
            require(len(frame_examples) == 1,
                    "accepted typed query did not become an observed question frame")
            require(not stored._fact_pattern_is_licensed(
                        relation_examples[0][0], relation_examples[0][1]),
                    "one source example licensed unsupported relation transfer")
        finally:
            stored.close()

    print("source-grounded natural-language chat: PASS")


if __name__ == "__main__":
    main()
