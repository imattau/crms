"""Check bounded, uncommitted proposals just beyond search depth."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def main() -> None:
    target = (Step("add_k", {"k": 1}), Step("keep_evens", {}),
              Step("first", {}))
    inputs = [
        [1, 9, 3, 6, 4, 12, 2],
        [-8, 2, -3, 11, 0, -1, 7, -5],
        [2, -4, 5, 0, 3],
    ]
    examples = [(values, _apply_procedure(target, values)) for values in inputs]
    bounded = CRMSModel(max_composition_depth=2, max_workers=1)
    result = bounded.teach("shift odd values and keep first", examples)
    if result.status != "no_fit" or not result.proposed_procedures:
        raise SystemExit(f"deeper exact rule was not proposed: {result}")
    target_key = _semantic_key(target)
    matching = [proposal for proposal in result.proposed_procedures
                if _semantic_key(tuple(
                    Step(item["operation"], item["parameters"])
                    for item in proposal)) == target_key]
    if not matching:
        raise SystemExit(f"proposal omitted the exact deeper behavior: {result}")
    if bounded.max_composition_depth != 2:
        raise SystemExit("proposal search changed configured depth")
    if "shift odd values and keep first" in bounded._procedures:
        raise SystemExit("advisory proposal was committed")

    held_out = [[], [11, 2, -7], [8, -3, 0, 5]]
    if any(_apply_procedure(tuple(
            Step(item["operation"], item["parameters"])
            for item in matching[0]), values)
           != _apply_procedure(target, values) for values in held_out):
        raise SystemExit("proposed procedure failed held-out checks")

    # The configured-depth search completes, but the additional search does
    # not; incomplete deeper exploration must not leak partial proposals.
    limited = CRMSModel(max_composition_depth=1, max_workers=1,
                        max_search_expansions=80)
    limited_result = limited.teach("shift odd values and keep first", examples)
    if (limited_result.status != "no_fit"
            or limited_result.proposed_procedures
            or limited_result.search_complete is not True):
        raise SystemExit(f"incomplete next-depth search leaked proposals: {limited_result}")

    deep = CRMSModel(max_composition_depth=3, max_workers=1)
    learned = deep.teach("shift odd values and keep first", examples)
    if (learned.status != "learned"
            or _semantic_key(tuple(Step(item["operation"], item["parameters"])
                                   for item in learned.procedure or []))
            != target_key):
        raise SystemExit(f"increased configured depth did not learn the proposal: {learned}")

    # Exercise the complete terminal path, including widening the same memory.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rules_path = root / "rules.json"
        common = [sys.executable, str(Path(__file__).resolve().parents[1]
                                      / "crms_chat.py"),
                  "--knowledge", str(root / "knowledge.json"),
                  "--index", str(root / "index.json"),
                  "--dialogue-state", str(root / "dialogue.json"),
                  "--rule-session", str(root / "session.json"),
                  "--rules", str(rules_path)]
        cli_inputs = "".join(
            "/teach-rule shift odd values and keep first|"
            + ",".join(map(str, values)) + "|"
            + ",".join(map(str, outputs)) + "\n"
            for values, outputs in examples)
        shallow = subprocess.run(
            [*common, "--rule-depth", "2"], input=cli_inputs + "/quit\n",
            text=True, capture_output=True, check=True)
        if ("Advisory procedure 1 (not learned):" not in shallow.stdout
                or "Rule learning status: no_fit." not in shallow.stdout):
            raise SystemExit(f"CLI hid or misreported the proposal:\n{shallow.stdout}")
        deep_cli = subprocess.run(
            [*common, "--rule-depth", "3"],
            input=("/teach-rule shift odd values and keep first|1,9,3,6,4,12,2|"
                   "2\n/apply-rule shift odd values and keep first|11,2,-7\n/quit\n"),
            text=True, capture_output=True, check=True)
        if ("Rule learning status: learned." not in deep_cli.stdout
                or "CRMS> [12]" not in deep_cli.stdout):
            raise SystemExit(f"CLI did not learn and apply the deeper rule:\n{deep_cli.stdout}")

    print("next-depth proposal diagnostic: PASS")
    print("exact deeper suggestion, held-out outputs, no auto-commit, config restoration, incomplete-search suppression, CLI retry at greater depth: PASS")


if __name__ == "__main__":
    main()
