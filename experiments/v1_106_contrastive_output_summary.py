"""Keep large version-space clarification prompts readable and informative."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import _format_candidate_outputs


def main() -> None:
    repeated = _format_candidate_outputs([[1], [1], [], [2, 3]])
    if "4 candidate procedures" not in repeated or "[1] × 2" not in repeated:
        raise SystemExit(f"small ambiguity summary lost counts: {repeated}")

    large = _format_candidate_outputs([[value] for value in range(1000)])
    if "1000 candidate procedures" not in large or "992 other output types" not in large:
        raise SystemExit(f"large ambiguity summary omitted its size: {large}")
    if len(large) > 320 or "[0]" not in large or "[7]" not in large:
        raise SystemExit(f"large ambiguity summary is not bounded/useful: {large}")

    print("contrastive output summary diagnostic: PASS")
    print("candidate counts, repeated predictions, bounded display: PASS")


if __name__ == "__main__":
    main()
