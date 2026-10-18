"""Learn a position-dependent value transformation from demonstrations."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel
from crms_research import CRMSResearchIndex


def main() -> None:
    model = CRMSModel(max_composition_depth=1,
                      enable_position_arithmetic=True)
    examples = [
        ([10, 20], [11, 22]),
        ([3, 7, 11], [4, 9, 14]),
    ]
    learned = model.teach("add each value by its position", examples)
    if (learned.status != "learned" or learned.candidate_count != 1
            or learned.procedure != [{"operation": "add_position", "parameters": {}}]):
        raise SystemExit(f"position-dependent primitive was not uniquely learned: {learned}")

    held_out = model.predict("add each value by its position", [8, -2, 5, 0])
    empty = model.predict("add each value by its position", [])
    singleton = model.predict("add each value by its position", [7])
    if (held_out.status != "ok" or held_out.output != [9, 0, 8, 4]
            or empty.status != "ok" or empty.output != []
            or singleton.status != "ok" or singleton.output != [8]):
        raise SystemExit(f"one-based position semantics failed on held-out/edge cases: {held_out}, {empty}, {singleton}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "memory.json"
        model.save(path)
        restored = CRMSModel(max_composition_depth=1, memory_path=str(path),
                             enable_position_arithmetic=True)
        prediction = restored.predict("add each value by its position", [2, 4, 6])
        if prediction.status != "ok" or prediction.output != [3, 6, 9]:
            raise SystemExit("position-dependent rule did not survive persistence")
        try:
            CRMSModel(max_composition_depth=1, memory_path=str(path))
        except ValueError as error:
            if "position-arithmetic setting differs" not in str(error):
                raise
        else:
            raise SystemExit("memory loaded without enabling its stored operation family")

        root = Path(directory)
        index_path = root / "index.json"
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--rules", str(root / "cli-rules.json"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rule-session", str(root / "rule-session.json"),
             "--rule-depth", "1", "--rule-enable-position-arithmetic"],
            input=("/teach-rule add each value by its position|10,20|11,22\n"
                   "/teach-rule add each value by its position|3,7,11|4,9,14\n"
                   "/apply-rule add each value by its position|8,-2,5,0\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if ("Rule learning status: learned." not in process.stdout
                or "CRMS> [9, 0, 8, 4]" not in process.stdout):
            raise SystemExit(f"CLI did not expose the opt-in operation:\n{process.stdout}")

    print("position-dependent rule discovery diagnostic: PASS")
    print("unique learning, held-out transfer, empty/singleton semantics, persistence, opt-in terminal teaching: PASS")


if __name__ == "__main__":
    main()
