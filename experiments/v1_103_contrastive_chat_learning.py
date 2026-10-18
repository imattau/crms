"""Check that chat answers are recorded for retrieval's contrastive probes."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel


TRAINING = (
    ("please reverse list", [([1, 2, 3], [3, 2, 1]),
                              ([3, 1, 4], [4, 1, 3])]),
    ("please sort array", [([3, -1, 5], [-1, 3, 5]),
                            ([5, -2, 4, 0], [-2, 0, 4, 5])]),
)


def main() -> None:
    reference = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase, demonstrations in TRAINING:
        if reference.teach(phrase, demonstrations).status != "learned":
            raise SystemExit(f"failed to ground reference examples for {phrase}")

    current = reference.predict("please", [1, 2, 3])
    if (current.status != "need_examples" or current.contrastive_input is None
            or current.candidate_outputs is None
            or len({tuple(output) for output in current.candidate_outputs}) < 2):
        raise SystemExit(f"reference query did not produce a separating probe: {current}")

    answers: list[tuple[list[int], list[int]]] = []
    instruction_model = reference
    for _ in range(8):
        values = current.contrastive_input
        expected = list(reversed(values))
        answers.append((values, expected))
        learned = instruction_model.teach("please", [(values, expected)])
        if learned.status == "learned":
            break
        if learned.contrastive_input is None:
            raise SystemExit(f"learner stopped requesting a discriminating example: {learned}")
        current = learned
    else:
        raise SystemExit("reference learner needed too many examples")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        setup_inputs = []
        for phrase, demonstrations in TRAINING:
            setup_inputs.extend(
                f"/teach-rule {phrase}|{','.join(map(str, xs))}|{','.join(map(str, ys))}"
                for xs, ys in demonstrations)
        command = [sys.executable,
                   str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
                   "--rules", str(root / "rules.json"),
                   "--knowledge", str(root / "knowledge.json"),
                   "--index", str(root / "index.json"),
                   "--dialogue-state", str(root / "dialogue.json"),
                   "--rule-session", str(root / "session.json"),
                   "--rule-depth", "1"]
        first = subprocess.run(
            command, input="\n".join(setup_inputs + ["please [1,2,3]", "/quit"]) + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        if "Please provide the intended output for input" not in first.stdout:
            raise SystemExit(f"chat did not ask the contrastive question:\n{first.stdout}")
        session = root / "session.json"
        pending = json.loads(session.read_text(encoding="utf-8"))
        if pending.get("instruction") != "please" or pending.get("input") != answers[0][0]:
            raise SystemExit(f"chat did not persist the unknown phrase probe: {pending}")

        feedback_inputs = [
            f"The output is [{','.join(map(str, ys))}]" for _xs, ys in answers
        ] + ["/apply-rule please|3,1,4", "/quit"]
        resumed = subprocess.run(
            command, input="\n".join(feedback_inputs) + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        if "Rule learning status: learned." not in resumed.stdout:
            raise SystemExit(f"chat did not commit the resolved rule after restart:\n{resumed.stdout}")
        if "CRMS> [4, 1, 3]" not in resumed.stdout:
            raise SystemExit(f"chat did not apply the learned rule:\n{resumed.stdout}")

    # The explicit /apply-rule path must preserve the same pending probe as a
    # natural-language request, so a following natural answer teaches the
    # correct instruction instead of becoming an unrelated chat turn.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        command = [sys.executable,
                   str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
                   "--rules", str(root / "rules.json"),
                   "--knowledge", str(root / "knowledge.json"),
                   "--index", str(root / "index.json"),
                   "--dialogue-state", str(root / "dialogue.json"),
                   "--rule-session", str(root / "session.json"),
                   "--rule-depth", "1"]
        setup_inputs = [
            f"/teach-rule {phrase}|{','.join(map(str, xs))}|"
            f"{','.join(map(str, ys))}"
            for phrase, demonstrations in TRAINING
            for xs, ys in demonstrations
        ]
        first = subprocess.run(
            command,
            input="\n".join(setup_inputs +
                            ["/apply-rule please|1,2,3", "/quit"]) + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        if "Please provide the intended output for input" not in first.stdout:
            raise SystemExit(f"/apply-rule did not ask its contrastive question:\n{first.stdout}")
        pending = json.loads((root / "session.json").read_text(encoding="utf-8"))
        if pending.get("instruction") != "please" or pending.get("input") != answers[0][0]:
            raise SystemExit(f"/apply-rule did not persist the exact pending probe: {pending}")
        feedback_inputs = [
            f"The output is [{','.join(map(str, ys))}]" for _xs, ys in answers
        ] + ["/apply-rule please|3,1,4", "/quit"]
        resumed = subprocess.run(
            command, input="\n".join(feedback_inputs) + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        if ("Rule learning status: learned." not in resumed.stdout
                or "CRMS> [4, 1, 3]" not in resumed.stdout):
            raise SystemExit(f"/apply-rule feedback did not teach the pending rule:\n{resumed.stdout}")

    print("contrastive chat learning diagnostic: PASS")
    print("natural and explicit rule requests, pending probe persistence, teacher feedback, learned phrase, held-out CLI application: PASS")


if __name__ == "__main__":
    main()
