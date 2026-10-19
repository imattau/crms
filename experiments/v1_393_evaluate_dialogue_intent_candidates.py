"""Evaluate inert intent candidates against disjoint labeled conversations.

This reports agreement with the named primary annotator, not label accuracy.
It performs offline candidate matching and never enables a frame at runtime.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.v1_392_induce_dialogue_intent_candidates import normalize_surface
from crms_dialogue_intent import validate_dialogue_intent_memory


STATE_CONTEXT = {
    "opening": {"conversation_opening"},
    "awaiting-user-detail": {"pending_assistant_question", "awaiting_user_detail"},
    "awaiting-confirmation": {"awaiting_confirmation"},
    "answer-follow-up": {"previous_grounded_answer"},
    "correction-or-challenge": {"correction_target_available"},
    "task-in-progress": {"task_in_progress"},
    "task-complete": {"task_complete"},
}
REQUIRED_COLUMNS = {
    "split", "conversation_id", "user_utterance", "dialogue_act",
    "task_intent", "context_state", "predecessor_act", "reviewer", "citation",
    "source_utterance_index",
}
ACTIVE_TASK_INTENTS = {
    "check-availability", "make-reservation", "change-reservation",
    "cancel-reservation", "correct-prior-result", "correct-result",
    "seek-information", "provide-information", "other-task",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def evaluate(candidate_report: dict, rows: list[dict[str, str]]) -> dict:
    metadata = candidate_report.get("metadata")
    memory = candidate_report.get("memory")
    if not isinstance(metadata, dict) or not isinstance(memory, dict):
        raise ValueError("candidate report must contain metadata and memory")
    if metadata.get("source_split") != "train only":
        raise ValueError("candidate source must be training conversations only")
    memory = validate_dialogue_intent_memory(memory)
    frames = memory["learned_frames"]
    if any(frame["status"] != "candidate" for frame in frames):
        raise ValueError("evaluation input must contain only inert candidate frames")
    train_ids = set(metadata.get("training_conversation_ids", ()))
    if not train_ids:
        raise ValueError("candidate report lacks training conversation IDs")
    missing = REQUIRED_COLUMNS - set(rows[0]) if rows else REQUIRED_COLUMNS
    if missing:
        raise ValueError(f"input lacks columns: {', '.join(sorted(missing))}")
    if any(row["split"].strip() not in {"dev", "test"} for row in rows):
        raise ValueError("evaluation input must contain dev or test rows only")
    eval_ids = {row["conversation_id"].strip() for row in rows}
    overlap = train_ids & eval_ids
    if overlap:
        raise ValueError(f"training/evaluation conversation leakage: {sorted(overlap)}")
    reviewers = {row["reviewer"].strip() for row in rows if row["reviewer"].strip()}
    if len(reviewers) != 1 or not next(iter(reviewers), "").startswith("codex-ai-"):
        raise ValueError("expected one explicitly identified Codex evaluation labeler")

    labeled = [row for row in rows
               if row["dialogue_act"].strip() not in {"", "uncertain"}
               and row["task_intent"].strip() not in {"", "uncertain"}]
    active_before: dict[tuple[str, str], str | None] = {}
    by_conversation: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_conversation.setdefault(row["conversation_id"].strip(), []).append(row)
    for conversation_id, conversation_rows in by_conversation.items():
        active_task: str | None = None
        for row in sorted(conversation_rows,
                          key=lambda item: int(item["source_utterance_index"])):
            row_id = row["source_utterance_index"].strip()
            active_before[(conversation_id, row_id)] = active_task
            intent = row["task_intent"].strip()
            labeled_goal = row.get("goal_intent", "").strip()
            if labeled_goal and labeled_goal != "uncertain":
                if labeled_goal not in ACTIVE_TASK_INTENTS:
                    raise ValueError(f"unknown goal intent: {labeled_goal}")
                active_task = labeled_goal
            elif intent == "end-interaction":
                active_task = None
            elif intent in ACTIVE_TASK_INTENTS:
                active_task = intent
    matched = confident = exact_pair = act_matches = intent_matches = 0
    goal_labeled = goal_matches = 0
    conflicts = 0
    predictions = []
    for row in labeled:
        surface = normalize_surface(row["user_utterance"])
        context = STATE_CONTEXT.get(row["context_state"].strip(), set())
        active_task = active_before.get((
            row["conversation_id"].strip(),
            row["source_utterance_index"].strip()))
        if active_task in ACTIVE_TASK_INTENTS:
            context = set(context)
            context.add("active_task_" + active_task.replace("-", "_"))
        predecessor = row["predecessor_act"].strip()
        eligible = [frame for frame in frames
                    if any(normalize_surface(pattern) == surface
                           for pattern in frame["surface_patterns"])
                    and set(frame["context_predicates"]) <= context
                    and (frame["predecessor_act"] is None
                         or frame["predecessor_act"] == predecessor)]
        signatures = {(frame["dialogue_act"], frame["task_intent"],
                       frame.get("goal_intent"))
                      for frame in eligible}
        matched += bool(eligible)
        if len(signatures) > 1:
            conflicts += 1
            predictions.append({
                "citation": row["citation"], "surface": row["user_utterance"],
                "label": [row["dialogue_act"], row["task_intent"],
                          row.get("goal_intent") or None],
                "prediction": "ambiguous-candidate-conflict",
                "alternatives": [list(sig) for sig in sorted(signatures)],
            })
            continue
        if len(signatures) != 1:
            continue
        confident += 1
        predicted_act, predicted_intent, predicted_goal = next(iter(signatures))
        actual_act, actual_intent = row["dialogue_act"].strip(), row["task_intent"].strip()
        act_matches += predicted_act == actual_act
        intent_matches += predicted_intent == actual_intent
        exact_pair += (predicted_act, predicted_intent) == (actual_act, actual_intent)
        actual_goal = row.get("goal_intent", "").strip()
        if actual_goal and actual_goal != "uncertain":
            goal_labeled += 1
            goal_matches += predicted_goal == actual_goal
        predictions.append({
            "citation": row["citation"], "surface": row["user_utterance"],
            "label": [actual_act, actual_intent, actual_goal or None],
            "prediction": [predicted_act, predicted_intent, predicted_goal],
            "matches_primary_label": (predicted_act, predicted_intent)
            == (actual_act, actual_intent),
            "candidate_citations": sorted({citation for frame in eligible
                                            for citation in frame["source_citations"]}),
        })

    return {
        "experiment": "v1_393_evaluate_dialogue_intent_candidates",
        "train_conversations": len(train_ids),
        "evaluation_conversations": len(eval_ids),
        "evaluation_split": sorted({row["split"].strip() for row in rows}),
        "evaluation_labeler": next(iter(reviewers)),
        "evaluation_basis": "agreement with the named single primary annotator",
        "context_basis": "provisional turn labels plus prior labeled turns in each conversation",
        "labeled_turns": len(labeled),
        "unlabeled_or_uncertain_turns": len(rows) - len(labeled),
        "candidate_matched_turns": matched,
        "candidate_coverage": matched / len(labeled) if labeled else 0.0,
        "unique_candidate_predictions": confident,
        "conflicted_candidate_matches": conflicts,
        "act_agreement_on_unique_matches": act_matches / confident if confident else None,
        "intent_agreement_on_unique_matches": intent_matches / confident if confident else None,
        "joint_agreement_on_unique_matches": exact_pair / confident if confident else None,
        "goal_intent_labeled_matches": goal_labeled,
        "goal_intent_uncertain_labels": sum(
            row.get("goal_intent", "").strip() == "uncertain" for row in rows),
        "goal_intent_agreement_on_labeled_matches": (
            goal_matches / goal_labeled if goal_labeled else None),
        "runtime_effect": "none; candidate frames remain inert",
        "predictions": predictions,
    }


def self_test() -> None:
    candidate_report = {
        "metadata": {
            "source_split": "train only",
            "training_conversation_ids": ["train-a", "train-b"],
        },
        "memory": {
            "format": "crms-dialogue-intent-memory", "version": 1,
            "builtin_policy": [],
            "learned_frames": [{
                "frame_id": "candidate-thanks", "dialogue_act": "thanks",
                "task_intent": "social-contact", "surface_patterns": ["thank you"],
                "goal_intent": "make-reservation",
                "context_predicates": ["task_in_progress"],
                "predecessor_act": "answer",
                "source_citations": ["train-a#turn=2", "train-b#turn=4"],
                "status": "candidate", "validation": None, "runtime_route": None,
            }],
        },
    }
    rows = [{
        "split": "dev", "conversation_id": "dev-a", "user_utterance": "Thank you!",
        "dialogue_act": "thanks", "task_intent": "social-contact",
        "goal_intent": "make-reservation",
        "context_state": "task-in-progress", "predecessor_act": "answer",
        "reviewer": "codex-ai-test", "citation": "dev-a#turn=3",
        "source_utterance_index": "1",
    }, {
        "split": "dev", "conversation_id": "dev-a", "user_utterance": "Goodbye",
        "dialogue_act": "farewell", "task_intent": "end-interaction",
        "goal_intent": "uncertain",
        "context_state": "task-complete", "predecessor_act": "close",
        "reviewer": "codex-ai-test", "citation": "dev-a#turn=4",
        "source_utterance_index": "3",
    }]
    result = evaluate(candidate_report, rows)
    require(result["candidate_matched_turns"] == 1
            and result["unique_candidate_predictions"] == 1
            and result["joint_agreement_on_unique_matches"] == 1.0
            and result["goal_intent_labeled_matches"] == 1
            and result["goal_intent_agreement_on_labeled_matches"] == 1.0
            and result["goal_intent_uncertain_labels"] == 1,
            "offline candidate agreement calculation failed")
    leaked = [dict(rows[0], conversation_id="train-a")]
    try:
        evaluate(candidate_report, leaked)
    except ValueError as exc:
        require("leakage" in str(exc), "overlap failed for an unrelated reason")
    else:
        raise SystemExit("train/evaluation conversation leakage was accepted")
    print("offline candidate matching and label-agreement metrics: PASS")
    print("train/evaluation conversation leakage is rejected: PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_report", type=Path, nargs="?")
    parser.add_argument("evaluation_csv", type=Path, nargs="?")
    parser.add_argument("output_json", type=Path, nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.candidate_report is None or args.evaluation_csv is None or args.output_json is None:
        parser.error("candidate_report, evaluation_csv, and output_json are required")
    report = json.loads(args.candidate_report.read_text(encoding="utf-8"))
    with args.evaluation_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = evaluate(report, rows)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    compact = {key: value for key, value in result.items() if key != "predictions"}
    print(json.dumps(compact, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
