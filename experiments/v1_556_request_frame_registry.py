"""Governed-lifecycle tests for learned request frames.

Request frames must share the rule registry's proposal, validation, activation,
use-count, contest, retirement, rollback, successor, and persistence controls.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_frame_registry import (  # noqa: E402
    FRAME_FAMILY, frame_rule_for, frame_rule_id, governed_frame_ids,
    record_request_frame_use, register_request_frame_rule,
    sync_request_frame_registry,
)
from crms_request_frames import RequestFrame, RequestFrameStore  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402


SEED = PROJECT / "crms_request_frames_seed.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    store = RequestFrameStore()
    store.add_seed_file(SEED)
    licensed = {frame.frame_id: frame for frame in store.frames()}
    require(len(licensed) == 29,
            f"expected 29 licensed seed frames, got {len(licensed)}")

    registry = RuleRegistry()
    sync_request_frame_registry(store, registry)
    records = registry.records(family=FRAME_FAMILY)
    require(len(records) == len(licensed),
            f"expected one registry rule per frame, got {len(records)}")
    require(all(record.state == "active" for record in records),
            "a licensed frame rule was not active after sync")
    require(all((record.validation or {}).get("passed") for record in records),
            "an active frame rule has no passing validation")
    require(all(int((record.validation or {}).get("cases", 0)) >= 2
                for record in records),
            "a frame rule was validated with fewer than two examples")
    require(all(record.payload.get("origin") == "crms_request_frames"
                for record in records),
            "a frame rule lost its origin marker")
    require(governed_frame_ids(store, registry) == set(licensed),
            "governed ids differ from licensed frames after sync")
    require(governed_frame_ids(store, None) == set(licensed),
            "registry-free governed view lost licensed frames")

    frame = next(frame for frame in store.frames()
                 if "which values" in frame.template_text())
    rule = frame_rule_for(registry, frame.frame_id)
    require(rule is not None and rule.state == "active",
            f"could not resolve the active rule for {frame.frame_id}")
    used = record_request_frame_use(registry, frame.frame_id, success=True)
    require(used is not None and used.utility["applications"] == 1
            and used.utility["successes"] == 1,
            f"frame use was not counted: {used}")

    with tempfile.TemporaryDirectory(prefix="crms-frame-registry-") as folder:
        path = Path(folder) / "registry.sqlite"
        registry.save(path)
        loaded = RuleRegistry.load(path)
        reloaded = frame_rule_for(loaded, frame.frame_id)
        require(reloaded is not None and reloaded.utility["applications"] == 1
                and reloaded.state == "active",
                "frame rule did not survive registry persistence")

    # A contest excludes the frame until it is rolled back to active.
    registry.contest(rule.id, reason="independent review")
    require(frame.frame_id not in governed_frame_ids(store, registry),
            "a contested frame is still executable")
    registry.rollback(rule.id)
    require(rule.state == "active"
            and frame.frame_id in governed_frame_ids(store, registry),
            "rollback did not restore the contested frame")

    # Retirement excludes it; rollback restores the prior active state.
    registry.retire(rule.id, reason="test retirement")
    require(frame.frame_id not in governed_frame_ids(store, registry)
            and record_request_frame_use(
                registry, frame.frame_id, success=True) is None,
            "a retired frame is still executable or counted")
    registry.rollback(rule.id)
    require(rule.state == "active"
            and frame.frame_id in governed_frame_ids(store, registry),
            "rollback did not restore the retired frame")

    # Dropping evidence retires the rule; re-teaching creates a successor
    # instead of silently reviving the retired rule on startup.
    partial = RequestFrameStore([frame.examples[0]])
    registry2 = RuleRegistry()
    sync_request_frame_registry(store, registry2)
    base_id = frame_rule_id(frame.frame_id)
    sync_request_frame_registry(partial, registry2)
    base = registry2.get(base_id)
    require(base.state == "retired",
            "a frame whose examples no longer license it was not retired")
    partial.examples.append(frame.examples[1])
    refreshed = next(item for item in partial.frames()
                     if item.frame_id == frame.frame_id)
    sync_request_frame_registry(partial, registry2)
    require(registry2.get(base_id).state == "retired",
            "startup silently revived a retired frame rule")
    require(frame.frame_id not in governed_frame_ids(partial, registry2),
            "a retired frame matched after a non-successor sync")
    successor = register_request_frame_rule(
        refreshed, registry2, allow_successor=True)
    require(successor.id == f"{base_id}-v2"
            and successor.state == "active"
            and successor.payload.get("frame_id") == frame.frame_id,
            f"explicit re-teaching did not create an active successor: {successor}")
    require(frame.frame_id in governed_frame_ids(partial, registry2),
            "the successor frame is not executable")

    # A frame whose stored examples do not replay to its template is proposed
    # but never activated.
    malformed = RequestFrame(
        frame_id="frame-invalid0000000",
        goal=frame.goal,
        parts=("literal",),
        fixed_procedure=None,
        examples=frame.examples[:2],
    )
    bad = register_request_frame_rule(malformed, RuleRegistry())
    require(bad.state == "proposed"
            and not (bad.validation or {}).get("passed", False),
            f"a frame with non-replaying evidence activated: {bad.state}")

    print("licensed frames mirror to active validated rules: PASS")
    print("use counts and registry persistence: PASS")
    print("contest, retirement, rollback, and governed filtering: PASS")
    print("evidence loss retires; explicit teaching creates a successor: PASS")
    print("non-replaying frame evidence cannot activate: PASS")


if __name__ == "__main__":
    main()
