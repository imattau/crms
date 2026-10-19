"""Induce cited, inert dialogue-intent candidates from labeled train turns.

This is exact-surface candidate induction, not a generalizer or an accuracy
evaluation. It deliberately uses only source-disjoint training conversations.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue_intent import (CRMSDialogueIntentModel,
                                  empty_dialogue_intent_memory,
                                  validate_dialogue_intent_memory)


CONTEXT_PREDICATES = {
    "opening": ("conversation_opening",),
    "awaiting-user-detail": (
        "pending_assistant_question", "awaiting_user_detail"),
    "awaiting-confirmation": ("awaiting_confirmation",),
    "answer-follow-up": ("previous_grounded_answer",),
    "correction-or-challenge": ("correction_target_available",),
    "task-in-progress": ("task_in_progress",),
    "task-complete": ("task_complete",),
}
PREDECESSOR_ACTS = {
    "answer", "clarification-request", "action-result", "close", "other",
}
ACTIVE_TASK_INTENTS = {
    "check-availability", "make-reservation", "change-reservation",
    "cancel-reservation", "correct-prior-result", "correct-result",
    "seek-information", "provide-information", "other-task",
}
GOAL_INTENTS = set(ACTIVE_TASK_INTENTS)
REQUIRED_COLUMNS = {
    "split", "conversation_id", "user_utterance", "dialogue_act",
    "task_intent", "context_state", "predecessor_act", "reviewer", "citation",
    "source_utterance_index",
}


def normalize_surface(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+(?:['’]\w+)*", value, re.UNICODE))


def induce(rows: list[dict[str, str]], *, min_conversations: int = 2) -> dict:
    if min_conversations < 2:
        raise ValueError("candidate induction requires at least two conversations")
    missing = REQUIRED_COLUMNS - set(rows[0]) if rows else REQUIRED_COLUMNS
    if missing:
        raise ValueError(f"input lacks columns: {', '.join(sorted(missing))}")
    codex_reviewers = {row["reviewer"].strip() for row in rows
                       if row["reviewer"].strip()}
    if len(codex_reviewers) != 1 or not next(iter(codex_reviewers), "").startswith(
            "codex-ai-"):
        raise ValueError("expected one explicitly identified Codex labeler")

    train_rows = [row for row in rows if row["split"].strip() == "train"]
    if not train_rows:
        raise ValueError("input contains no labeled training turns")
    groups: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    excluded_contexts = Counter()
    excluded_predecessors = Counter()
    unlabeled = 0
    active_before: dict[tuple[str, str], str | None] = {}
    by_conversation: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in train_rows:
        by_conversation[row["conversation_id"].strip()].append(row)
    for conversation_id, conversation_rows in by_conversation.items():
        active_task: str | None = None
        for row in sorted(conversation_rows,
                          key=lambda item: int(item["source_utterance_index"])):
            row_id = row["source_utterance_index"].strip()
            active_before[(conversation_id, row_id)] = active_task
            prior_intent = row["task_intent"].strip()
            labeled_goal = row.get("goal_intent", "").strip()
            if labeled_goal:
                if labeled_goal not in GOAL_INTENTS:
                    raise ValueError(f"unknown goal intent: {labeled_goal}")
                active_task = labeled_goal
            elif prior_intent == "end-interaction":
                active_task = None
            elif prior_intent in ACTIVE_TASK_INTENTS:
                active_task = prior_intent

    for row in train_rows:
        surface = normalize_surface(row["user_utterance"])
        act, intent = row["dialogue_act"].strip(), row["task_intent"].strip()
        state = row["context_state"].strip()
        predecessor = row["predecessor_act"].strip()
        if not surface or not act or not intent or act == "uncertain" or intent == "uncertain":
            unlabeled += 1
            continue
        predicates = CONTEXT_PREDICATES.get(state)
        if predicates is None:
            excluded_contexts[state or "<blank>"] += 1
            continue
        if predecessor not in PREDECESSOR_ACTS:
            excluded_predecessors[predecessor or "<blank>"] += 1
            continue
        active_task = active_before.get((
            row["conversation_id"].strip(),
            row["source_utterance_index"].strip()))
        if active_task in ACTIVE_TASK_INTENTS:
            predicates = (*predicates,
                          "active_task_" + active_task.replace("-", "_"))
        goal_intent = row.get("goal_intent", "").strip() or None
        if goal_intent is not None and goal_intent not in GOAL_INTENTS:
            raise ValueError(f"unknown goal intent: {goal_intent}")
        signature = (surface, act, intent, goal_intent, predicates, predecessor)
        groups[signature].append(row)

    payload = empty_dialogue_intent_memory()
    candidates = []
    repeated_conflicts = 0
    surface_signatures: dict[str, set[tuple]] = defaultdict(set)
    for signature, examples in groups.items():
        surface, act, intent, goal_intent, predicates, predecessor = signature
        conv_ids = sorted({row["conversation_id"].strip() for row in examples})
        surface_signatures[surface].add(
            (act, intent, goal_intent, predicates, predecessor))
        if len(conv_ids) < min_conversations:
            continue
        frame_hash = hashlib.sha256("\0".join(map(str, signature)).encode()).hexdigest()[:16]
        citations = sorted({row["citation"].strip() for row in examples
                            if row["citation"].strip()})
        if len(citations) < min_conversations:
            continue
        frame = {
            "frame_id": f"candidate-{frame_hash}",
            "dialogue_act": act,
            "task_intent": intent,
            "goal_intent": goal_intent,
            "surface_patterns": [surface],
            "context_predicates": list(predicates),
            "predecessor_act": predecessor,
            "source_citations": citations,
            "status": "candidate",
            "validation": None,
            "runtime_route": None,
        }
        candidates.append(frame)
    repeated_conflicts = sum(1 for signatures in surface_signatures.values()
                             if len(signatures) > 1)
    payload["learned_frames"] = sorted(candidates, key=lambda item: item["frame_id"])
    validated = validate_dialogue_intent_memory(payload)
    # This invariant is central: induction never silently licenses a route.
    model = CRMSDialogueIntentModel(validated)
    for frame in validated["learned_frames"]:
        require(model.resolve(frame["surface_patterns"][0],
                              context=set(frame["context_predicates"]),
                              predecessor_act=frame["predecessor_act"]) is None,
                "a candidate frame unexpectedly affected runtime resolution")
    return {
        "metadata": {
            "experiment": "v1_392_induce_dialogue_intent_candidates",
            "labeler": next(iter(codex_reviewers)),
            "label_status": "single-annotator; provisional",
            "source_split": "train only",
            "training_conversation_ids": sorted({
                row["conversation_id"].strip() for row in train_rows}),
            "active_task_context": "derived from preceding labeled turns per conversation",
            "goal_intent_labels": ("provided by optional goal_intent column"
                                   if "goal_intent" in rows[0] else "not supplied"),
            "minimum_distinct_conversations": min_conversations,
            "training_turns": len(train_rows),
            "excluded_uncertain_or_blank_rows": unlabeled,
            "excluded_context_counts": dict(sorted(excluded_contexts.items())),
            "excluded_predecessor_counts": dict(sorted(excluded_predecessors.items())),
            "ambiguous_repeated_surface_count": repeated_conflicts,
            "candidate_count": len(candidates),
            "frame_status": "candidate; inert",
            "generalization": "exact normalized surface only",
        },
        "memory": validated,
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def self_test() -> None:
    base = {
        "split": "train", "user_utterance": "Thank you!",
        "dialogue_act": "thanks", "task_intent": "social-contact",
        "context_state": "task-in-progress", "predecessor_act": "answer",
        "reviewer": "codex-ai-test", "source_utterance_index": "1",
    }
    rows = [
        {**base, "conversation_id": "conversation-a",
         "citation": "source-a#turn=2"},
        {**base, "conversation_id": "conversation-b",
         "source_utterance_index": "3",
         "citation": "source-b#turn=4"},
        {**base, "conversation_id": "booking-a", "source_utterance_index": "1",
         "user_utterance": "Book a table", "dialogue_act": "request-action",
         "task_intent": "make-reservation", "context_state": "task-in-progress",
         "predecessor_act": "other", "citation": "booking-a#turn=1",
         "goal_intent": "make-reservation"},
        {**base, "conversation_id": "booking-a", "source_utterance_index": "3",
         "user_utterance": "Two people", "dialogue_act": "answer-clarification",
         "task_intent": "make-reservation", "context_state": "awaiting-user-detail",
         "predecessor_act": "clarification-request", "citation": "booking-a#turn=3",
         "goal_intent": "make-reservation"},
        {**base, "conversation_id": "booking-b", "source_utterance_index": "1",
         "user_utterance": "Reserve a table", "dialogue_act": "request-action",
         "task_intent": "make-reservation", "context_state": "task-in-progress",
         "predecessor_act": "other", "citation": "booking-b#turn=1",
         "goal_intent": "make-reservation"},
        {**base, "conversation_id": "booking-b", "source_utterance_index": "3",
         "user_utterance": "Two people", "dialogue_act": "answer-clarification",
         "task_intent": "make-reservation", "context_state": "awaiting-user-detail",
         "predecessor_act": "clarification-request", "citation": "booking-b#turn=3",
         "goal_intent": "make-reservation"},
        {**base, "conversation_id": "mixed-a", "source_utterance_index": "1",
         "user_utterance": "Book that restaurant", "dialogue_act": "request-action",
         "task_intent": "make-reservation", "context_state": "task-in-progress",
         "predecessor_act": "other", "citation": "mixed-a#turn=1",
         "goal_intent": "make-reservation"},
        {**base, "conversation_id": "mixed-a", "source_utterance_index": "3",
         "user_utterance": "Could you just give me the phone number?",
         "dialogue_act": "request-action", "task_intent": "seek-information",
         "context_state": "task-in-progress", "predecessor_act": "answer",
         "citation": "mixed-a#turn=3", "goal_intent": "make-reservation"},
        {**base, "conversation_id": "mixed-b", "source_utterance_index": "1",
         "user_utterance": "I want to book it", "dialogue_act": "request-action",
         "task_intent": "make-reservation", "context_state": "task-in-progress",
         "predecessor_act": "other", "citation": "mixed-b#turn=1",
         "goal_intent": "make-reservation"},
        {**base, "conversation_id": "mixed-b", "source_utterance_index": "3",
         "user_utterance": "Could you just give me the phone number?",
         "dialogue_act": "request-action", "task_intent": "seek-information",
         "context_state": "task-in-progress", "predecessor_act": "answer",
         "citation": "mixed-b#turn=3", "goal_intent": "make-reservation"},
        {**base, "split": "dev", "conversation_id": "conversation-c",
         "dialogue_act": "reject", "task_intent": "other-task",
         "citation": "source-c#turn=8"},
    ]
    report = induce(rows)
    frames = report["memory"]["learned_frames"]
    thank_you = [frame for frame in frames
                 if frame["surface_patterns"] == ["thank you"]]
    reservation_party = [frame for frame in frames
                         if frame["surface_patterns"] == ["two people"]]
    phone_request = [frame for frame in frames
                     if frame["surface_patterns"]
                     == ["could you just give me the phone number"]]
    require(len(thank_you) == 1 and thank_you[0]["status"] == "candidate"
            and len(thank_you[0]["source_citations"]) == 2
            and len(reservation_party) == 1
            and "active_task_make_reservation"
            in reservation_party[0]["context_predicates"]
            and len(reservation_party[0]["source_citations"]) == 2,
            "candidate grouping, citation retention, or train-only split failed")
    require(len(phone_request) == 1
            and phone_request[0]["task_intent"] == "seek-information"
            and phone_request[0]["goal_intent"] == "make-reservation"
            and "active_task_make_reservation" in phone_request[0]["context_predicates"],
            "candidate induction lost the annotated broad goal")
    require(report["metadata"]["label_status"] == "single-annotator; provisional"
            and report["metadata"]["candidate_count"] == 3,
            "single-labeler provenance or candidate count was lost")
    print("candidate induction uses consistent train-only examples and citations: PASS")
    print("heldout rows do not contaminate candidate induction: PASS")
    print("single-labeler candidates remain provisional and inert: PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_turns_csv", type=Path, nargs="?")
    parser.add_argument("output_json", type=Path, nargs="?")
    parser.add_argument("--min-conversations", type=int, default=2)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.user_turns_csv is None or args.output_json is None:
        parser.error("user_turns_csv and output_json are required unless --self-test is used")
    with args.user_turns_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    report = induce(rows, min_conversations=args.min_conversations)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    print(json.dumps(report["metadata"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
