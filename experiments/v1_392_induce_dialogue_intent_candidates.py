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
REQUIRED_COLUMNS = {
    "split", "conversation_id", "user_utterance", "dialogue_act",
    "task_intent", "context_state", "predecessor_act", "reviewer", "citation",
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
        signature = (surface, act, intent, predicates, predecessor)
        groups[signature].append(row)

    payload = empty_dialogue_intent_memory()
    candidates = []
    repeated_conflicts = 0
    surface_signatures: dict[str, set[tuple]] = defaultdict(set)
    for signature, examples in groups.items():
        surface, act, intent, predicates, predecessor = signature
        conv_ids = sorted({row["conversation_id"].strip() for row in examples})
        surface_signatures[surface].add((act, intent, predicates, predecessor))
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
        "reviewer": "codex-ai-test", "source_record_ordinal": "1",
    }
    rows = [
        {**base, "conversation_id": "conversation-a",
         "citation": "source-a#turn=2"},
        {**base, "conversation_id": "conversation-b",
         "citation": "source-b#turn=4"},
        {**base, "split": "dev", "conversation_id": "conversation-c",
         "dialogue_act": "reject", "task_intent": "other-task",
         "citation": "source-c#turn=8"},
    ]
    report = induce(rows)
    frames = report["memory"]["learned_frames"]
    require(len(frames) == 1
            and frames[0]["status"] == "candidate"
            and len(frames[0]["source_citations"]) == 2
            and frames[0]["surface_patterns"] == ["thank you"],
            "candidate grouping, citation retention, or train-only split failed")
    require(report["metadata"]["label_status"] == "single-annotator; provisional"
            and report["metadata"]["candidate_count"] == 1,
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
