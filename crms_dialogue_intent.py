"""Validation helpers for portable, contextual dialogue-intent memory.

Dialogue memory separates built-in interaction policy from corpus-induced
frames. It is data only; a frame cannot update factual knowledge or authorize
an external action.
"""

from __future__ import annotations

import re
from typing import Any


FORMAT = "crms-dialogue-intent-memory"
VERSION = 1
_ROOT_KEYS = {"format", "version", "builtin_policy", "learned_frames"}
_CONTEXT_PREDICATES = {
    "conversation_opening", "current_topic_available",
    "previous_grounded_answer", "pending_candidate_choice",
    "open_dialogue_slot", "pending_assistant_question",
    "awaiting_user_detail", "awaiting_confirmation",
    "awaiting_yes_no_answer",
    "awaiting_slot_detail", "awaiting_slot_topic", "awaiting_slot_entity",
    "awaiting_slot_location", "awaiting_slot_restaurant_type",
    "awaiting_slot_party_size",
    "awaiting_slot_date_time", "awaiting_slot_seating", "awaiting_slot_cuisine",
    "awaiting_slot_restaurant_choice", "awaiting_slot_confirmation",
    "awaiting_slot_yes_no",
    "has_session_slot_location", "has_session_slot_party_size",
    "has_session_slot_date_time", "has_session_slot_seating",
    "has_session_slot_cuisine", "has_session_slot_restaurant_choice",
    "task_in_progress", "task_complete", "correction_target_available",
    "active_task_check_availability", "active_task_make_reservation",
    "active_task_change_reservation", "active_task_cancel_reservation",
    "active_task_correct_prior_result", "active_task_correct_result",
    "active_task_seek_information", "active_task_provide_information",
    "active_task_other_task",
}
_DIALOGUE_ACTS = {
    "question", "request-action", "provide-information", "answer-clarification",
    "confirmation", "confirm", "acknowledgement", "correction", "reject",
    "greeting", "thanks", "farewell", "continuation-request", "social",
    "other", "uncertain",
}
_TASK_INTENTS = {
    "check-availability", "make-reservation", "change-reservation",
    "cancel-reservation", "provide-constraint", "seek-information",
    "provide-information", "continue-current-task", "resolve-ambiguity",
    "correct-prior-result", "correct-result", "social-contact",
    "end-interaction", "other-task", "uncertain",
}
_PREDECESSOR_ACTS = {
    "question", "clarification-request", "answer", "confirmation-request",
    "greeting", "action-result", "close", "other", "uncertain",
}
_FRAME_STATUSES = {"candidate", "train-only", "heldout-validated", "rejected"}
_RUNTIME_ROUTES = {"greeting", "farewell", "thanks", "acknowledgement",
                   "reaction", "elaboration"}
_ROUTE_ACTS = {
    "greeting": "greeting", "farewell": "farewell", "thanks": "thanks",
    "acknowledgement": "acknowledgement", "reaction": "social",
    "elaboration": "continuation-request",
}
_ROUTE_INTENTS = {
    "greeting": "social-contact", "farewell": "end-interaction",
    "thanks": "social-contact", "acknowledgement": "continue-current-task",
    "reaction": "social-contact", "elaboration": "continue-current-task",
}


def empty_dialogue_intent_memory() -> dict[str, Any]:
    return {"format": FORMAT, "version": VERSION,
            "builtin_policy": [], "learned_frames": []}


def _strings(value: Any, name: str, *, maximum: int,
             nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"dialogue memory {name} must be a bounded list")
    if nonempty and not value:
        raise ValueError(f"dialogue memory {name} must not be empty")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 512
           for item in value):
        raise ValueError(f"dialogue memory {name} contains an invalid value")
    return value


def validate_dialogue_intent_memory(payload: Any) -> dict[str, Any]:
    """Validate and return a canonical portable dialogue-memory payload."""
    if not isinstance(payload, dict) or set(payload) != _ROOT_KEYS:
        raise ValueError("dialogue intent memory has an invalid root shape")
    if payload.get("format") != FORMAT or payload.get("version") != VERSION:
        raise ValueError("unsupported dialogue intent memory format")
    builtin = payload.get("builtin_policy")
    learned = payload.get("learned_frames")
    if (not isinstance(builtin, list) or len(builtin) > 10_000
            or not isinstance(learned, list) or len(learned) > 100_000):
        raise ValueError("dialogue intent frames must be bounded lists")
    seen_ids: set[str] = set()
    normalized_builtin = []
    for frame in builtin:
        required = {"policy_id", "dialogue_act", "task_intent",
                    "surface_patterns", "context_predicates", "predecessor_act",
                    "runtime_route"}
        if not isinstance(frame, dict) or set(frame) != required:
            raise ValueError("built-in dialogue policy frame has an invalid shape")
        frame_id = frame["policy_id"]
        if (not isinstance(frame_id, str) or not frame_id.strip()
                or len(frame_id) > 120 or frame_id in seen_ids):
            raise ValueError("dialogue policy IDs must be unique non-empty strings")
        seen_ids.add(frame_id)
        _validate_frame_values(frame, frame_id)
        normalized_builtin.append(dict(frame))

    normalized_learned = []
    for frame in learned:
        required = {"frame_id", "dialogue_act", "task_intent", "surface_patterns",
                    "context_predicates", "predecessor_act", "source_citations",
                    "status", "validation", "runtime_route"}
        if not isinstance(frame, dict) or set(frame) != required:
            raise ValueError("learned dialogue frame has an invalid shape")
        frame_id = frame["frame_id"]
        if (not isinstance(frame_id, str) or not frame_id.strip()
                or len(frame_id) > 120 or frame_id in seen_ids):
            raise ValueError("dialogue frame IDs must be unique non-empty strings")
        seen_ids.add(frame_id)
        _validate_frame_values(frame, frame_id)
        citations = _strings(frame["source_citations"],
                             f"{frame_id}.source_citations", maximum=100_000,
                             nonempty=True)
        status = frame["status"]
        if not isinstance(status, str) or status not in _FRAME_STATUSES:
            raise ValueError(f"dialogue frame {frame_id} has an unknown status")
        validation = frame["validation"]
        if status == "heldout-validated":
            keys = {"status", "train_conversation_ids",
                    "holdout_conversation_ids", "reviewer_count", "metrics"}
            if not isinstance(validation, dict) or set(validation) != keys:
                raise ValueError(
                    f"validated dialogue frame {frame_id} lacks validation metadata")
            if validation["status"] != "heldout-validated":
                raise ValueError("dialogue frame status disagrees with its validation")
            train_ids = set(_strings(
                validation["train_conversation_ids"],
                f"{frame_id}.train_conversation_ids", maximum=100_000,
                nonempty=True))
            holdout_ids = set(_strings(
                validation["holdout_conversation_ids"],
                f"{frame_id}.holdout_conversation_ids", maximum=100_000,
                nonempty=True))
            if train_ids & holdout_ids:
                raise ValueError(
                    f"dialogue frame {frame_id} has conversation split leakage")
            reviewer_count = validation["reviewer_count"]
            if (not isinstance(reviewer_count, int) or isinstance(reviewer_count, bool)
                    or reviewer_count < 2):
                raise ValueError(
                    f"dialogue frame {frame_id} needs two independent reviewers")
            if not isinstance(validation["metrics"], dict):
                raise ValueError(f"dialogue frame {frame_id} metrics must be an object")
        elif validation is not None:
            raise ValueError(
                f"unvalidated dialogue frame {frame_id} cannot carry validation metadata")
        normalized_learned.append(dict(frame))
    return {"format": FORMAT, "version": VERSION,
            "builtin_policy": normalized_builtin,
            "learned_frames": normalized_learned}


def _validate_frame_values(frame: dict[str, Any], frame_id: str) -> None:
    if (not isinstance(frame["dialogue_act"], str)
            or frame["dialogue_act"] not in _DIALOGUE_ACTS):
        raise ValueError(f"dialogue frame {frame_id} has an unknown act")
    intent = frame["task_intent"]
    if (intent is not None and (not isinstance(intent, str)
                                or intent not in _TASK_INTENTS)):
        raise ValueError(f"dialogue frame {frame_id} has an unknown task intent")
    patterns = _strings(frame["surface_patterns"],
                        f"{frame_id}.surface_patterns", maximum=100,
                        nonempty=True)
    if any("(?" in pattern or re.search(r"\\[1-9]", pattern)
           for pattern in patterns):
        raise ValueError(
            f"dialogue frame {frame_id} patterns must be literal templates, not regex")
    predicates = _strings(frame["context_predicates"],
                          f"{frame_id}.context_predicates", maximum=32)
    if set(predicates) - _CONTEXT_PREDICATES:
        raise ValueError(f"dialogue frame {frame_id} has an unknown context predicate")
    predecessor = frame["predecessor_act"]
    if (predecessor is not None
            and (not isinstance(predecessor, str)
                 or predecessor not in _PREDECESSOR_ACTS)):
        raise ValueError(f"dialogue frame {frame_id} has an unknown predecessor act")
    route = frame["runtime_route"]
    if route is not None and (not isinstance(route, str)
                              or route not in _RUNTIME_ROUTES):
        raise ValueError(f"dialogue frame {frame_id} has an unknown runtime route")
    if route is not None and frame["dialogue_act"] != _ROUTE_ACTS[route]:
        raise ValueError(f"dialogue frame {frame_id} act conflicts with its runtime route")
    if route is not None and frame["task_intent"] != _ROUTE_INTENTS[route]:
        raise ValueError(f"dialogue frame {frame_id} intent conflicts with its runtime route")
    if (frame["dialogue_act"] == "answer-clarification"
            and not set(frame["context_predicates"]) & {
                "pending_assistant_question", "pending_candidate_choice",
                "open_dialogue_slot"}):
        raise ValueError(
            f"dialogue frame {frame_id} answers a clarification without an open question")


class CRMSDialogueIntentModel:
    """Match explicitly licensed literal frames against bounded dialogue state."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = validate_dialogue_intent_memory(
            payload if payload is not None else empty_dialogue_intent_memory())

    @classmethod
    def load(cls, path: str) -> "CRMSDialogueIntentModel":
        import json
        from pathlib import Path
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @staticmethod
    def normalize_surface(value: str) -> str:
        import unicodedata
        value = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(re.findall(r"\w+(?:['’]\w+)*", value,
                                   flags=re.UNICODE))

    def resolve(self, utterance: str, *, context: set[str],
                predecessor_act: str | None) -> dict[str, Any] | None:
        """Return an intent decision for one matching frame, or abstain.

        Only built-in policy and held-out-validated learned frames can select
        an intent or runtime route. An intent may be selected without a route;
        candidate, train-only, and rejected frames
        remain stored for audit but are inert.
        """
        normalized = self.normalize_surface(utterance)
        if not normalized:
            return None
        candidates: list[dict[str, Any]] = []
        for frame in self.payload["builtin_policy"]:
            if any(self.normalize_surface(pattern) == normalized
                   for pattern in frame["surface_patterns"]):
                candidates.append({**frame, "frame_id": frame["policy_id"],
                                   "status": "builtin-policy",
                                   "evidence_refs": []})
        for frame in self.payload["learned_frames"]:
            if (frame["status"] != "heldout-validated"
                    or not any(self.normalize_surface(pattern) == normalized
                               for pattern in frame["surface_patterns"])):
                continue
            candidates.append({**frame, "evidence_refs": frame["source_citations"]})
        if not candidates:
            return None

        eligible = [frame for frame in candidates
                    if set(frame["context_predicates"]) <= context
                    and (frame["predecessor_act"] is None
                         or frame["predecessor_act"] == predecessor_act)]
        if eligible:
            signatures = {(frame["dialogue_act"], frame["task_intent"],
                           frame["runtime_route"]) for frame in eligible}
            if len(signatures) != 1:
                # A conflict among licensed readings is itself a useful
                # contextual-intent result. Preserve it as an ambiguity, but
                # never choose one of the conflicting routes.
                by_signature: dict[tuple[str, str | None, str | None], str] = {}
                for item in sorted(eligible, key=lambda value: value["frame_id"]):
                    signature = (item["dialogue_act"], item["task_intent"],
                                 item["runtime_route"])
                    by_signature.setdefault(signature, item["frame_id"])
                alternatives = tuple(
                    f"{act} / {task_intent or 'unspecified'}"
                    f" (frame {frame_id}; route {route or 'none'})"
                    for (act, task_intent, route), frame_id
                    in sorted(by_signature.items(), key=lambda pair: str(pair[0]))
                )
                evidence_refs = sorted({
                    citation for item in eligible
                    for citation in item["evidence_refs"]})[:32]
                return {
                    "dialogue_act": "uncertain",
                    "task_intent": None,
                    "decision": "ambiguous",
                    "matched_frame": "ambiguous-portable-frames",
                    "context_predicates": tuple(sorted({
                        predicate for item in eligible
                        for predicate in item["context_predicates"]})),
                    "alternatives": alternatives[:16],
                    "selected_value": None,
                    "basis": "portable_dialogue_model",
                    "evidence_refs": tuple(evidence_refs),
                    "runtime_route": None,
                }
            # Prefer the most context-specific license; stable ID ordering is
            # only a tie-break between frames that authorize the same action.
            frame = sorted(eligible, key=lambda item: (
                -len(item["context_predicates"]), item["frame_id"]))[0]
            evidence_refs = sorted({
                citation for item in eligible
                for citation in item["evidence_refs"]})[:32]
            return {
                "dialogue_act": frame["dialogue_act"],
                "task_intent": frame["task_intent"],
                "decision": "selected",
                "matched_frame": frame["frame_id"],
                "context_predicates": tuple(frame["context_predicates"]),
                "alternatives": (),
                "selected_value": None,
                "basis": "portable_dialogue_model",
                "evidence_refs": tuple(evidence_refs),
                "runtime_route": frame["runtime_route"],
            }
        return None
