"""Check that independent retrieval routes cannot silently override one another.

Run with: python3 experiments/v1_184_conflicting_retrieval_routes.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        memory = Path(temporary) / "rules.json"
        model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        _seed_fixture(model)
        _check_fixture(model)

        query = "add 5 to every value"
        reference = CRMSModel(max_composition_depth=1, max_workers=1)
        _seed_fixture(reference)
        pending = reference.predict(query, [1, 2, 3])
        answers: list[tuple[list[int], list[int]]] = []
        for _ in range(8):
            if pending.contrastive_input is None:
                raise SystemExit(f"teacher-feedback path lost its probe: {pending}")
            values = pending.contrastive_input
            output = list(reversed(values))
            answers.append((values, output))
            learned = reference.teach(query, [(values, output)])
            if learned.status == "learned":
                break
            pending = learned
        else:
            raise SystemExit("contrastive teacher answers did not resolve the rule")

        root = Path(temporary)
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--rules", str(memory),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "session.json"),
            "--rule-depth", "1",
        ]
        first = subprocess.run(
            command,
            input=f"/apply-rule {query}|1,2,3\n/quit\n",
            text=True, capture_output=True, check=True, timeout=90)
        if "Grounded retrieval routes support competing rules" not in first.stdout:
            raise SystemExit(f"chat did not expose the route conflict:\n{first.stdout}")
        session = json.loads((root / "session.json").read_text(encoding="utf-8"))
        if (session.get("instruction") != query
                or session.get("input") != answers[0][0]):
            raise SystemExit(f"chat did not persist the conflict probe: {session}")

        feedback = [
            f"The output is [{','.join(map(str, output))}]"
            for _values, output in answers
        ]
        feedback.extend([f"/apply-rule {query}|3,1,4", "/quit"])
        resumed = subprocess.run(
            command, input="\n".join(feedback) + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        if "Rule learning status: learned." not in resumed.stdout:
            raise SystemExit(f"teacher feedback did not learn the rule:\n{resumed.stdout}")
        if "CRMS> [4, 1, 3]" not in resumed.stdout:
            raise SystemExit(f"learned route choice failed on held-out input:\n{resumed.stdout}")

    print("conflicting numeric/aligned retrieval routes request a contrastive example: PASS")
    print("uncontested numeric retrieval remains available: PASS")
    print("chat probe persistence, teacher feedback, route resolution, and held-out use: PASS")


def _check_fixture(model: CRMSModel) -> None:

    query = "add 5 to every value"
    numeric, numeric_conflict, *_ = model._retrieve_parameterized_procedure(query)
    aligned, aligned_conflict, *_ = model._retrieve_aligned_phrase(query)
    if (numeric is None or aligned is None or numeric_conflict or aligned_conflict
            or numeric[0].operation != "add_k"
            or aligned[0].operation != "reverse"):
        raise SystemExit("fixture did not create distinct grounded route candidates")

    result = model.predict(query, [1, 2, 3])
    if (result.status != "need_examples" or result.output is not None
            or result.contrastive_input is None
            or result.candidate_outputs is None
            or {tuple(output) for output in result.candidate_outputs}
            != {(0,), (5,)}):
        raise SystemExit(f"conflicting routes were not surfaced for clarification: {result}")

    numeric_only = model.predict("add 6 to every value", [1, 2, 3])
    if numeric_only.status != "ok" or numeric_only.output != [7, 8, 9]:
        raise SystemExit(f"uncontested numeric route failed: {numeric_only}")

    composed_conflict = model.predict(
        "add 5 to every value, then add 5 for every number", [1, 2, 3])
    if composed_conflict.status == "ok" or composed_conflict.output is not None:
        raise SystemExit(
            f"a conflicted composition component was silently selected: {composed_conflict}")

    composed_clear = model.predict(
        "add 6 to every value, then add 5 to every number", [1, 2, 3])
    if composed_clear.status != "ok" or composed_clear.output != [9, 8, 7]:
        raise SystemExit(f"uncontested composed routes failed: {composed_clear}")


def _seed_fixture(model: CRMSModel) -> None:
    for amount in (2, 4):
        rows = [([1, 2, 3], [value + amount for value in [1, 2, 3]]),
                ([-3, 0, 4], [value + amount for value in [-3, 0, 4]])]
        if model.teach(f"add {amount} to every value", rows).status != "learned":
            raise SystemExit("numeric parameter fixture failed to learn")

    reverse_rows = [
        ([1, 2, 3], [3, 2, 1]),
        ([2, 8, 1], [1, 8, 2]),
        ([4, 0, -3, 9], [9, -3, 0, 4]),
    ]
    for phrase in (
            "add 5 to every number",
            "add 5 for every value",
            "add 5 for every number"):
        if model.teach(phrase, reverse_rows).status != "learned":
            raise SystemExit(f"aligned phrase fixture failed to learn: {phrase}")

if __name__ == "__main__":
    main()
