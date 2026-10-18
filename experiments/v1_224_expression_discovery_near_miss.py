"""Check that expression discovery rejects cross-phrase near misses."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_model import CRMSModel
from v1_178_failure_cluster_expression_discovery import fixture_model


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    # Positive control: retain a genuine expression supported by three phrase
    # clusters and an unrelated no-fit distractor.
    with tempfile.TemporaryDirectory(prefix="crms-expression-positive-") as tmp:
        positive = fixture_model(Path(tmp) / "positive.json")
        expression_proposals = [
            item for item in positive.propose_primitive_candidates()
            if item["descriptor"].get("operation") == "map_window_expression"
        ]
        require(any(item["descriptor"].get("expression") == "(+ (* x x) y)"
                    or item["descriptor"].get("expression") == "(+ y (* x x))"
                    for item in expression_proposals),
                "positive control failed to recover its supported expression")

    # The two targets agree on the first two zero-right training lists but
    # differ over a varied held-out list. Neither expression may be promoted
    # merely because the training portion underdetermines the sign of y.
    near_miss = CRMSModel(max_composition_depth=1, max_workers=1,
                          max_search_expansions=20_000)
    inputs = ([2, 0], [5, 0], [0, 1, -2, 3, -4, 5, -6, 7, -8, 9])
    targets = (
        ("square left and add right", lambda x, y: x * x + y),
        ("square left and subtract right", lambda x, y: x * x - y),
    )
    for phrase, operation in targets:
        examples = [
            (list(row), [operation(left, right)
                         for left, right in zip(row, row[1:])])
            for row in inputs
        ]
        learned = near_miss.teach(phrase, examples)
        require(learned.status == "no_fit" and learned.search_complete,
                f"near-miss fixture did not produce complete no-fit evidence: {learned}")

    expression_proposals = [
        item for item in near_miss.propose_primitive_candidates()
        if item["descriptor"].get("operation") == "map_window_expression"
    ]
    require(not expression_proposals,
            f"opposing held-out formulas produced a shared proposal: {expression_proposals}")
    print("window-expression discovery near-miss diagnostic: PASS")
    print("supported positive recovery retained; opposite formulas rejected by held-out evidence: PASS")


if __name__ == "__main__":
    main()
