"""Check learned categorical word-slot mappings across grounded phrases."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel


TRAINING = (
    ("remove the first item", "drop_first"),
    ("remove the last item", "drop_last"),
    ("delete the first element", "drop_first"),
    ("delete the last element", "drop_last"),
)
PROJECT = Path(__file__).resolve().parents[1]


def examples_for(operation: str) -> list[tuple[list[int], list[int]]]:
    return [
        ([3, 9, 1, 7], [9, 1, 7] if operation == "drop_first" else [3, 9, 1]),
        ([-4, 2, 8], [2, 8] if operation == "drop_first" else [-4, 2]),
        ([1, 3, 1, 2], [3, 1, 2] if operation == "drop_first" else [1, 3, 1]),
        ([1, 2, 1, 3, 2],
         [2, 1, 3, 2] if operation == "drop_first" else [1, 2, 1, 3]),
    ]


def teach(model: CRMSModel, phrase: str, operation: str) -> None:
    result = model.teach(phrase, examples_for(operation))
    if result.status != "learned":
        raise SystemExit(f"could not ground {phrase!r}: {result}")


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "rules.json"
        model = CRMSModel(path, max_composition_depth=1, max_workers=1)
        for phrase, operation in TRAINING:
            teach(model, phrase, operation)

        cases = (
            ("remove the first element", "drop_first", [9, 1, 7]),
            ("delete the last item", "drop_last", [3, 9, 1]),
        )
        for query, operation, expected in cases:
            result = model.predict(query, [3, 9, 1, 7])
            if (result.status != "ok" or result.output != expected
                    or not result.matched_templates
                    or not result.matched_templates[0].startswith("contrastive_slot:")):
                raise SystemExit(f"grounded slot transfer failed for {query!r}: {result}")
            expected_sources = ({"remove the first item", "delete the first element"}
                                if operation == "drop_first" else
                                {"remove the last item", "delete the last element"})
            if not expected_sources.issubset(result.evidence_phrases or []):
                raise SystemExit(f"slot result lost its teaching evidence: {result}")

        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        after_load = restored.predict("remove the first element", [8, 2, 5])
        if after_load.status != "ok" or after_load.output != [2, 5]:
            raise SystemExit(f"contrastive slot transfer did not persist: {after_load}")

    unknown = model.predict("discard the first element", [3, 9, 1, 7])
    if unknown.status == "ok":
        raise SystemExit(f"unsupported verb received a guessed rule: {unknown}")

    conflicted = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase, operation in TRAINING:
        teach(conflicted, phrase, operation)
    teach(conflicted, "remove the first object", "drop_last")
    ambiguous = conflicted.predict("delete the first object", [3, 9, 1, 7])
    if ambiguous.status == "ok":
        raise SystemExit(f"conflicting role evidence was silently resolved: {ambiguous}")

    cli_lines = []
    for phrase, operation in TRAINING:
        for inputs, outputs in examples_for(operation):
            cli_lines.append(
                f"{phrase} [{','.join(map(str, inputs))}] -> "
                f"[{','.join(map(str, outputs))}]")
    cli_lines.extend(["remove the first element [3,9,1,7]", "/quit"])
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        names = ("knowledge.json", "index.json", "dialogue.json",
                 "rules.json", "rule-session.json")
        paths = [root / name for name in names]
        command = [sys.executable, str(PROJECT / "crms_chat.py"),
                   "--knowledge", str(paths[0]), "--index", str(paths[1]),
                   "--dialogue-state", str(paths[2]), "--rules", str(paths[3]),
                   "--rule-session", str(paths[4]), "--rule-depth", "1"]
        completed = subprocess.run(
            command, input="\n".join(cli_lines) + "\n", text=True,
            capture_output=True, check=True, timeout=90)
        if "CRMS> [9, 1, 7]" not in completed.stdout:
            raise SystemExit(f"terminal did not transfer the learned slot:\n{completed.stdout}")

    print("contrastive instruction-slot diagnostic: PASS")
    print("cross-phrase slot recombination, evidence, persistence, CLI, unknown-word abstention, conflicting-slot abstention: PASS")


if __name__ == "__main__":
    main()
