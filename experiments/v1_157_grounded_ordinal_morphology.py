"""Check evidence-gated ordinal spelling discovery through the terminal UI."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def csv(values: list[int]) -> str:
    return ",".join(str(value) for value in values)


def common_args(folder: Path, rules: Path) -> list[str]:
    return [sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(rules),
            "--knowledge", str(folder / "knowledge.json"),
            "--index", str(folder / "research.json"),
            "--dialogue-state", str(folder / "dialogue.json"),
            "--rule-depth", "1", "--rule-max-repeat", "7",
            "--rule-max-position-stride", "7"]


def main() -> None:
    cardinal_examples = {
        4: [([1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
             [value for value in range(1, 11) for _ in range(4)]),
            ([2, 5], [2, 2, 2, 2, 5, 5, 5, 5])],
        6: [([1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
             [value for value in range(1, 11) for _ in range(6)]),
            ([2, 5], [2, 2, 2, 2, 2, 2, 5, 5, 5, 5, 5, 5])],
        7: [([1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
             [value for value in range(1, 11) for _ in range(7)]),
            ([2, 5], [2, 2, 2, 2, 2, 2, 2, 5, 5, 5, 5, 5, 5, 5])],
    }
    ordinal_examples = {}
    for value in (4, 6):
        ordinal_examples[value] = [
            ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
             list(range(value, 11, value))),
            ([10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
             list(range(10 - value + 1, 0, -value))),
        ]

    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        rules = folder / "rules.json"
        commands = []
        for value, word in ((4, "four"), (6, "six"), (7, "seven")):
            for phrase in (f"repeat each value {value} times",
                           f"repeat each value {word} times"):
                commands.extend(
                    f"/teach-rule {phrase}|{csv(inputs)}|{csv(outputs)}"
                    for inputs, outputs in cardinal_examples[value])
        for value, word in ((4, "fourth"), (6, "sixth")):
            for phrase in (f"select every {value}th item",
                           f"select every {word} item"):
                commands.extend(
                    f"/teach-rule {phrase}|{csv(inputs)}|{csv(outputs)}"
                    for inputs, outputs in ordinal_examples[value])
        query_values = list(range(1, 31))
        commands.extend((
            f"/explain-rule select every seventh item|{csv(query_values)}",
            f"/apply-rule select every seventh item|{csv(query_values)}",
            "/quit",
        ))
        result = subprocess.run(
            common_args(folder, rules), input="\n".join(commands) + "\n",
            text=True, capture_output=True, check=True, timeout=30)
        output = result.stdout
        required = (
            "Rule explanation status: ok.",
            "Output: [7, 14, 21, 28]",
            "Grounding phrases:",
            "select every 4th item",
            "select every 6th item",
            "repeat each value seven times",
            "CRMS> [7, 14, 21, 28]",
        )
        missing = [phrase for phrase in required if phrase not in output]
        if missing:
            raise SystemExit(f"CLI omitted {missing}:\n{output}")
        if not rules.exists():
            raise SystemExit("CLI did not persist the grounded examples")

        # A separate store has one ordinal correspondence, which is not enough
        # to infer a productive suffix rule for a new cardinal word.
        control_rules = folder / "control-rules.json"
        control_commands = []
        for phrase in ("repeat each value 7 times",
                       "repeat each value seven times"):
            control_commands.extend(
                f"/teach-rule {phrase}|{csv(inputs)}|{csv(outputs)}"
                for inputs, outputs in cardinal_examples[7])
        for phrase in ("select every 4th item", "select every fourth item"):
            examples = [([1, 2, 3, 4, 5, 6, 7, 8], [4, 8]),
                        ([8, 7, 6, 5, 4, 3, 2, 1], [5, 1])]
            control_commands.extend(
                f"/teach-rule {phrase}|{csv(inputs)}|{csv(outputs)}"
                for inputs, outputs in examples)
        control_commands.extend((
            f"/explain-rule select every seventh item|{csv(query_values)}",
            "/quit",
        ))
        control = subprocess.run(
            common_args(folder, control_rules),
            input="\n".join(control_commands) + "\n", text=True,
            capture_output=True, check=True, timeout=30)
        if "Rule explanation status: ok." in control.stdout:
            raise SystemExit("CLI generalized from only one ordinal correspondence")

    print("grounded ordinal morphology CLI diagnostic: PASS")
    print("two-pair suffix induction, cross-template transfer, explanation lineage, "
          "persistence, and one-pair abstention: PASS")


if __name__ == "__main__":
    main()
