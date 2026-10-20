"""Governed lifecycle for learned request frames.

Request frames live in a learned sidecar store. This module mirrors each
licensed frame into the rule registry so frames share the same proposal,
validation, activation, use-count, retirement, and rollback controls as learned
procedures. The frame store remains the source of matching evidence; the
registry decides whether a licensed frame is governed and executable.
"""
from __future__ import annotations

from typing import Any

from crms_request_frames import (
    GOALS, FrameSlot, RequestFrame, RequestFrameStore, _frame_id,
    parse_marked_example,
)
from crms_rule_registry import RuleRecord, RuleRegistry

FRAME_FAMILY = "request-frame"
FRAME_ORACLE = "stored-template-replay"
FRAME_ORIGIN = "crms_request_frames"


def frame_rule_id(frame_id: str) -> str:
    return "request-frame-" + frame_id.removeprefix("frame-")


def _parts_payload(frame: RequestFrame) -> list[dict[str, str]]:
    parts: list[dict[str, str]] = []
    for part in frame.parts:
        if isinstance(part, FrameSlot):
            parts.append(part.to_dict())
        else:
            parts.append({"kind": "literal", "text": part})
    return parts


def _frame_payload(frame: RequestFrame) -> dict[str, Any]:
    return {
        "origin": FRAME_ORIGIN,
        "frame_id": frame.frame_id,
        "goal": frame.goal,
        "template": frame.template_text(),
        "parts": _parts_payload(frame),
        "fixed_procedure": frame.fixed_procedure,
        "examples": [example.to_dict() for example in frame.examples],
        "example_count": len(frame.examples),
    }


def _frame_provenance(frame: RequestFrame) -> list[dict[str, Any]]:
    return [
        {
            "kind": "request-frame-example",
            "index": index,
            "goal": example.goal,
            "source_id": example.source_id,
            "utterance": example.text,
            "fixed_procedure": example.fixed_procedure,
        }
        for index, example in enumerate(frame.examples)
    ]


def replay_request_frame(frame: RequestFrame) -> tuple[bool, str, int, int]:
    """Re-derive the frame from its marked examples and check exact parity."""
    examples = frame.examples
    if len(examples) < 2:
        return False, "a frame needs at least two examples", len(examples), 0
    if frame.goal not in GOALS:
        return False, "the frame goal is not supported", len(examples), 0
    if frame.frame_id != _frame_id(
            frame.goal, frame.parts, frame.fixed_procedure):
        return False, "the frame id does not match its template", len(examples), 0
    parsed = []
    try:
        for example in examples:
            example.validate()
            parsed.append(parse_marked_example(example.text))
    except Exception as error:  # noqa: BLE001 - malformed stored evidence
        return False, f"an example is malformed: {error}", len(examples), 0
    for example, item in zip(examples, parsed):
        if example.goal != frame.goal:
            return False, "an example uses a different goal", len(examples), 0
        if example.fixed_procedure != frame.fixed_procedure:
            return False, "an example uses a different fixed procedure", len(examples), 0
        if item.parts != frame.parts:
            return False, "an example does not replay to the stored template", len(examples), 0
    if len({example.text.strip() for example in examples}) < 2:
        return False, "the examples do not contain two distinct utterances", len(examples), 0
    slot_names = [part.name for part in frame.parts
                  if isinstance(part, FrameSlot)]
    varied = False
    for name in slot_names:
        if len({item.bindings.get(name, "") for item in parsed}) >= 2:
            varied = True
            break
    if not varied:
        return (False, "no slot has two distinct example fillers",
                len(examples), 0)
    sources = {example.source_id for example in examples
               if example.source_id.strip()}
    if len(sources) != len({example.source_id for example in examples}):
        return False, "an example is missing a source id", len(examples), len(sources)
    detail = (f"{len(examples)} marked examples replay to the same literal/slot "
              f"template; {len(sources)} independent source(s)")
    return True, detail, len(examples), len(sources)


def register_request_frame_rule(
        frame: RequestFrame, registry: RuleRegistry, *,
        allow_successor: bool = False) -> RuleRecord:
    """Propose, validate, and activate the rule for one licensed frame."""
    payload = _frame_payload(frame)
    provenance = _frame_provenance(frame)
    passed, detail, cases, independent_sources = replay_request_frame(frame)
    statement = f"request frame for goal {frame.goal}: {frame.template_text()}"
    scope = f"chat composition; goal {frame.goal}"

    base_id = frame_rule_id(frame.frame_id)
    existing = registry.get(base_id) if base_id in registry else None
    rule_id = base_id
    if existing is not None and existing.state == "retired":
        if not allow_successor:
            return existing
        version = 2
        while f"{base_id}-v{version}" in registry:
            version += 1
        rule_id = f"{base_id}-v{version}"
        existing = None

    if existing is None:
        registry.propose(
            rule_id=rule_id,
            family=FRAME_FAMILY,
            statement=statement,
            scope=scope,
            payload=payload,
            provenance=provenance,
            trust="taught",
        )
    else:
        current_validation = existing.validation or {}
        unchanged = (
            existing.payload == payload
            and existing.provenance == provenance
            and bool(current_validation.get("passed")) == passed
            and int(current_validation.get("cases", -1)) == cases
            and int(current_validation.get("independent_sources", -1))
            == independent_sources
        )
        if unchanged and existing.state == "active":
            return existing
        if existing.state == "contested":
            # A manual contest is a review hold. Refresh the evidence but do
            # not clear the hold or reactivate on startup.
            if (existing.payload != payload
                    or existing.provenance != provenance):
                registry.revise(
                    rule_id,
                    statement=statement,
                    payload=payload,
                    provenance=provenance,
                )
            return registry.get(rule_id)
        registry.revise(
            rule_id,
            statement=statement,
            payload=payload,
            provenance=provenance,
        )

    registry.validate(
        rule_id,
        oracle=FRAME_ORACLE,
        passed=passed,
        cases=cases,
        independent_sources=independent_sources,
        detail=detail,
    )
    record = registry.get(rule_id)
    if passed and record.state in {"proposed", "validated"}:
        registry.activate(rule_id, mode="review", authoriser="teacher")
    return registry.get(rule_id)


def sync_request_frame_registry(
        store: RequestFrameStore, registry: RuleRegistry) -> None:
    """Mirror licensed frames into the registry and retire stale rule records."""
    licensed = {frame.frame_id: frame for frame in store.frames()}
    for frame in licensed.values():
        register_request_frame_rule(frame, registry, allow_successor=False)
    for record in registry.records(family=FRAME_FAMILY):
        if record.state == "retired":
            continue
        if record.payload.get("origin") != FRAME_ORIGIN:
            continue
        if record.payload.get("frame_id") not in licensed:
            registry.retire(
                record.id, reason="request frame is no longer licensed")


def governed_frame_ids(
        store: RequestFrameStore, registry: RuleRegistry | None) -> set[str]:
    """Return licensed frames whose registry rule is currently active."""
    licensed = {frame.frame_id for frame in store.frames()}
    if registry is None:
        return licensed
    active = {
        str(record.payload.get("frame_id"))
        for record in registry.records(family=FRAME_FAMILY, state="active")
        if record.payload.get("origin") == FRAME_ORIGIN
    }
    return licensed & active


def frame_rule_for(registry: RuleRegistry,
                   frame_id: str) -> RuleRecord | None:
    rows = [
        record for record in registry.records(family=FRAME_FAMILY)
        if record.payload.get("frame_id") == frame_id
    ]
    if not rows:
        return None
    active = [record for record in rows if record.state == "active"]
    return max(active or rows, key=lambda record: record.version)


def record_request_frame_use(
        registry: RuleRegistry, frame_id: str,
        *, success: bool = True) -> RuleRecord | None:
    rows = [
        record for record in registry.records(family=FRAME_FAMILY, state="active")
        if record.payload.get("frame_id") == frame_id
    ]
    if not rows:
        return None
    return registry.record_use(rows[0].id, success=success)
