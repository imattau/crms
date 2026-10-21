"""Phase 10 teacher contract: rule proposal, no-regression gate, SQL audit."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_composition_memory import GenerationRuleStore, seed_store  # noqa: E402
from crms_examiner import evaluate_proposal, load_proposal, record_proposal  # noqa: E402
from crms_generation_rules import DEFAULT_RULES_PATH, load_rules  # noqa: E402

ACCEPT = PROJECT / "corpus" / "phase10_eval" / "teacher_proposal.json"
REJECT = PROJECT / "corpus" / "phase10_eval" / "teacher_proposal_rejected.json"
REPORT = PROJECT / "experiments" / "reports" / "phase10_teacher.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    payload = json.loads(DEFAULT_RULES_PATH.read_text(encoding="utf-8"))
    accepted = evaluate_proposal(load_proposal(ACCEPT), rules=load_rules())
    rejected = evaluate_proposal(load_proposal(REJECT), rules=load_rules())
    require(accepted["accepted"], "teacher clarity proposal was not accepted")
    require(not rejected["accepted"], "negative control was not rejected")
    require(accepted["after"]["all_pass"], "accepted proposal regressed a case")
    require(accepted["after"]["mean_score"] + 1e-9
            >= accepted["before"]["mean_score"],
            "accepted proposal lowered mean quality")
    require(rejected["after"]["all_pass"] is False,
            "negative control did not fail the suite")
    require(len(accepted["proposal"]["prompt_sha256"]) == 64,
            "teacher prompt digest missing")
    require(accepted["proposal"]["model"].startswith("opencode-go/"),
            "teacher model id missing")

    with tempfile.TemporaryDirectory(prefix="crms-phase10-teacher-") as temporary:
        path = Path(temporary) / "composition.sqlite"
        with GenerationRuleStore(path) as store:
            seed_store(store, payload)
            seed = store.active_snapshot()
            require(seed is not None, "seed snapshot missing")
            accepted_id = record_proposal(store, accepted)
            require(store.active_snapshot()["snapshot_id"] == accepted_id,
                    "accepted proposal is not active")
            rejected_id = record_proposal(store, rejected)
            require(store.active_snapshot()["snapshot_id"] == accepted_id,
                    "rejected proposal became active")
            require(rejected_id != accepted_id, "rejected snapshot id collided")
            stats = store.stats()
            require(stats["snapshots"] == 3, "teacher snapshot history wrong")
            require(stats["judgments"] == 2, "teacher judgments missing")
            store.rollback(seed["snapshot_id"], rationale="test rollback")
            require(store.load_rules().digest == seed["digest"],
                    "teacher rollback failed")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    require(report["gate_passed"], "teacher report gate did not pass")
    require(report["gate"]["accepted_proposal_no_regression"],
            "teacher report lost no-regression result")
    require(report["gate"]["negative_control_rejected"],
            "teacher report lost negative control")
    require(report["gate"]["human_review"] is False,
            "teacher report falsely claims human review")

    print("Teacher prompt digest, model id, and proposal schema: PASS")
    print("Accepted clarity rule, no-regression gate: PASS")
    print("Negative control rejection: PASS")
    print("SQL snapshots, judgments, active selection, rollback: PASS")
    print("Phase 10 teacher contract: PASS")


if __name__ == "__main__":
    main()
