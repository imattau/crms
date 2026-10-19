"""Replay dialogue labels using question type inferred from transcript wording.

Open-question presence and task intent still come from provisional annotations.
The assistant's question type and slot, however, are inferred from its actual
preceding turn, matching the runtime rule rather than the coarser context label.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.v1_395_runtime_intent_oracle_context import evaluate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.labels, question_type_from_prompt=True)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
