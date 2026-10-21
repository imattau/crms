"""Phase 10 composition memory: snapshots, judgments, rollback, reload."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_composition_memory import GenerationRuleStore, seed_store  # noqa: E402
from crms_generation_rules import load_rules  # noqa: E402
from crms_rule_registry import FAMILIES  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    rules_path = PROJECT / "crms_generation_rules.json"
    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    source_rules = load_rules(rules_path)
    require("composition" in FAMILIES, "composition rule family missing")

    with tempfile.TemporaryDirectory(prefix="crms-phase10-sql-") as temporary:
        path = Path(temporary) / "composition.sqlite"
        with GenerationRuleStore(path) as store:
            seed_id = seed_store(store, payload)
            active = store.active_snapshot()
            require(active is not None, "seed snapshot not active")
            require(active["snapshot_id"] == seed_id, "unexpected seed id")
            seed_digest = active["digest"]
            loaded = store.load_rules()
            require(loaded.digest == seed_digest,
                    "SQL reload changed the rule digest")
            require(len(loaded.genres) == 10, "SQL reload lost genres")

            changed = json.loads(json.dumps(payload))
            changed["transitions"]["example"] = "For instance"
            changed_id = store.put_snapshot(
                changed, origin="teacher", rationale="prefer 'for instance'",
                accepted=True, reference="teacher-proposal-1")
            require(store.load_rules().digest != seed_digest,
                    "accepted teacher snapshot did not become active")
            store.record_judgment(
                snapshot_id=changed_id, source="automated", score=0.91,
                faithfulness=1.0, clarity=0.9, coverage=1.0,
                model="local-evaluator", note="fixture panel")
            store.record_frame_stat("explanation.mechanism", success=True)
            store.record_frame_stat("explanation.mechanism", success=False)

            rollback_id = store.rollback(seed_id, rationale="teacher regression")
            require(rollback_id != seed_id, "rollback did not create a snapshot")
            require(store.load_rules().digest == seed_digest,
                    "rollback did not restore the seed digest")
            stats = store.stats()
            require(stats["snapshots"] == 3, "snapshot history is wrong")
            require(stats["changes"] >= 3, "change audit is incomplete")
            require(stats["judgments"] == 1, "judgment was not recorded")
            require(stats["frame_stats"] == 1, "frame stats were not recorded")

        with GenerationRuleStore(path) as reopened:
            require(reopened.active_snapshot() is not None,
                    "store did not reopen")
            require(len(reopened.load_rules().genres) == 10,
                    "reopened store lost genres")

    print("SQL snapshot seed, active load, and digest: PASS")
    print("Teacher snapshot, judgment, frame stats, rollback: PASS")
    print("Reopen and composition rule family: PASS")
    print("Phase 10 composition memory contract: PASS")


if __name__ == "__main__":
    main()
