"""Prefer compact, informative probes for ambiguous composed rules.

Objective: keep active-learning questions practical when a version space has
many behaviorally distinct procedures.
Setup: compare candidate rotations that coincide on short lists with three
endpoint/order procedures that separate on short lists.
Metrics: suggested input length and number of distinct predicted outputs.
Failure modes: an unnecessarily long probe or one that does not separate
candidate outputs.
Definition of success: select an input of at most three values that divides
the candidates into at least two output groups.

Run from the project root with:
    python3 experiments/v1_295_compact_contrastive_rule_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import Step, _contrastive_probe


def main() -> None:
    # Fifteen rotations coincide on short lists. Three endpoint/order rules
    # split off a minority of those cases. The old 80% cutoff kept searching;
    # 90% treats the short probe as useful because it divides candidates 15/3.
    candidates = [
        (Step("rotate_left_k", {"k": 6 * multiple}),)
        for multiple in range(1, 16)
    ] + [(Step("first", {}),), (Step("last", {}),),
         (Step("reverse", {}),)]
    probe, outputs = _contrastive_probe(candidates)
    if probe is None or outputs is None:
        raise SystemExit("no separating probe was found")
    if len(probe) > 3:
        raise SystemExit(
            f"learner preferred a long probe over a useful short split: {probe}")
    if len(set(map(tuple, outputs))) < 2:
        raise SystemExit("suggested input does not separate candidate outputs")

    print("compact contrastive rule probe diagnostic: PASS")
    print(f"candidates={len(candidates)} probe_length={len(probe)} "
          f"distinct_outputs={len(set(map(tuple, outputs)))}")


if __name__ == "__main__":
    main()
