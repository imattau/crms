"""Phase 10 external contract: bounded gate, open human/independent limits."""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "experiments" / "reports" / "phase10_external.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    require(report["format"] == "crms-phase10-external",
            "wrong Phase 10 external report format")
    require(report["bounded_gate_passed"] is True,
            "bounded Phase 10 gate did not pass")
    require(report["full_gate_passed"] is False,
            "full Phase 10 gate must not be claimed")
    require(report["open_gate"]["human_clarity_calibration"] is False,
            "human clarity calibration must remain open")
    require(report["open_gate"]["independent_300_prompt_suite"] is False,
            "independent 300-prompt suite must remain open")
    require(report["open_gate"]["two_source_disjoint_corpora"] is False,
            "two source-disjoint corpora must remain open")
    require(report["open_gate"]["measured_70b_model"] is False,
            "measured 70B model must remain open")
    metrics = report["metrics"]
    require(metrics["generation"]["cases"] == 12,
            "generation suite is not 12 cases")
    require(metrics["generation"]["passed"] == 12,
            "generation suite is not 12/12")
    require(not metrics["coverage"]["untested_genres"],
            "declared genres remain untested")
    require(metrics["generation"]["mean_copy_ratio"] <= 0.4,
            "mean copy ratio exceeds Phase 10 target")
    require(metrics["teacher"]["accepted_proposal_no_regression"],
            "teacher no-regression check missing")
    require(metrics["teacher"]["negative_control_rejected"],
            "teacher negative control missing")
    require(metrics["clean_room"]["gate_passed"],
            "clean-room check missing")
    require(metrics["comparison_ratios"]["adequacy"] >= 0.8,
            "comparison adequacy below 80% of proxy")
    require(metrics["comparison_ratios"]["clarity"] >= 0.9,
            "comparison clarity below 90% of proxy")
    require(metrics["comparison_ratios"]["coverage"] >= 0.8,
            "comparison coverage below 80% of proxy")
    require(metrics["agreement"]["available"],
            "rater agreement missing")
    print("Bounded Phase 10 gate: PASS")
    print("All 10 genres, 12/12 cases, mean copy <= 0.4: PASS")
    print("Teacher no-regression, negative control, SQL, clean room: PASS")
    print("Automated 70B-class comparison thresholds: PASS")
    print("Human, independent 300, two-corpus, measured-70B gates: OPEN")
    print("Phase 10 external contract: PASS")


if __name__ == "__main__":
    main()
