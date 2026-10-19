"""Measure a context-gated lexical nearest-example intent baseline.

This is an offline research comparator, not a runtime route. It uses only
training turns, applies typed dialogue-state gates when labels exist, compares
the user wording and prior assistant utterance, and keeps nearest-source
citations with each prediction. Labels are compared with the named annotator,
not treated as gold.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import sys
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.v1_392_induce_dialogue_intent_candidates import ACTIVE_TASK_INTENTS


STOP_WORDS = set("""a an and are as at be but by can could did do does for from get
give had has have he her him how i if in into is it its me my of on or our she
should that the their them there these they this those to was we were what when
where which who why will with would you your""".split())


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+(?:['’][a-z0-9]+)?",
                                          text.casefold())
            if len(token) > 2 and token not in STOP_WORDS}


def _last_assistant_text(row: dict[str, str]) -> str:
    for line in reversed(row.get("preceding_context", "").splitlines()):
        speaker, separator, text = line.partition(":")
        if separator and speaker.strip().casefold() == "assistant":
            return text.strip()
    return ""


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _goal(row: dict[str, str]) -> str | None:
    value = row.get("goal_intent", "").strip()
    return None if value in {"", "uncertain"} else value


def _active_before(rows: list[dict[str, str]]) -> dict[tuple[str, str], str | None]:
    by_conversation: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_conversation[row["conversation_id"].strip()].append(row)
    result = {}
    for conversation_id, turns in by_conversation.items():
        active_goal = None
        for row in sorted(turns, key=lambda item: int(item["source_utterance_index"])):
            key = (conversation_id, row["source_utterance_index"].strip())
            result[key] = active_goal
            labeled_goal = _goal(row)
            task_intent = row["task_intent"].strip()
            if labeled_goal is not None:
                active_goal = labeled_goal
            elif task_intent == "end-interaction":
                active_goal = None
            elif task_intent in ACTIVE_TASK_INTENTS:
                active_goal = task_intent
    return result


def _classifiable(row: dict[str, str]) -> bool:
    return (row.get("dialogue_act", "").strip() not in {"", "uncertain"}
            and row.get("task_intent", "").strip() not in {"", "uncertain"})


def predict(row: dict[str, str], training: list[dict[str, Any]], *,
            active_goal: str | None, threshold: float,
            context_weight: float = 0.0) -> dict[str, Any]:
    query_terms = _tokens(row["user_utterance"])
    query_prompt_terms = _tokens(_last_assistant_text(row))
    eligible = []
    for example in training:
        source = example["row"]
        query_state = row.get("context_state", "").strip()
        source_state = source.get("context_state", "").strip()
        if query_state and source_state and source_state != query_state:
            continue
        query_predecessor = row.get("predecessor_act", "").strip()
        source_predecessor = source.get("predecessor_act", "").strip()
        if (query_predecessor and source_predecessor
                and source_predecessor != query_predecessor):
            continue
        source_goal = example["active_goal"]
        if active_goal != source_goal:
            continue
        user_similarity = _jaccard(query_terms, example["terms"])
        prompt_similarity = _jaccard(query_prompt_terms, example["prompt_terms"])
        similarity = ((1 - context_weight) * user_similarity
                      + context_weight * prompt_similarity)
        if similarity >= threshold:
            eligible.append((similarity, example))
    if not eligible:
        return {"status": "abstain", "similarity": None,
                "prediction": None, "sources": []}
    best = max(score for score, _ in eligible)
    nearest = [example for score, example in eligible if score == best]
    signatures = {
        (example["row"]["dialogue_act"].strip(),
         example["row"]["task_intent"].strip(), _goal(example["row"]))
        for example in nearest
    }
    sources = sorted({example["row"]["citation"].strip()
                      for example in nearest})
    if len(signatures) != 1:
        return {"status": "ambiguous", "similarity": best,
                "prediction": None, "sources": sources,
                "alternatives": [list(item) for item in sorted(
                    signatures, key=lambda value: str(value))]}
    act, task_intent, goal_intent = next(iter(signatures))
    return {"status": "selected", "similarity": best,
            "prediction": {"dialogue_act": act, "task_intent": task_intent,
                           "goal_intent": goal_intent},
            "sources": sources}


def evaluate(training_rows: list[dict[str, str]],
             evaluation_rows: list[dict[str, str]], *, threshold: float,
             context_weight: float = 0.0) -> dict[str, Any]:
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be greater than zero and at most one")
    if not 0 <= context_weight <= 1:
        raise ValueError("context_weight must be between zero and one")
    if not training_rows or not evaluation_rows:
        raise ValueError("training and evaluation sheets must not be empty")
    if any(row["split"].strip() != "train" for row in training_rows):
        raise ValueError("training sheet must contain train rows only")
    if any(row["split"].strip() not in {"dev", "test"}
           for row in evaluation_rows):
        raise ValueError("evaluation sheet must contain dev or test rows only")
    train_ids = {row["conversation_id"].strip() for row in training_rows}
    evaluation_ids = {row["conversation_id"].strip() for row in evaluation_rows}
    if train_ids & evaluation_ids:
        raise ValueError("training/evaluation conversation leakage")

    active_train = _active_before(training_rows)
    active_eval = _active_before(evaluation_rows)
    examples = [
        {"row": row, "terms": _tokens(row["user_utterance"]),
         "prompt_terms": _tokens(_last_assistant_text(row)),
         "active_goal": active_train.get((row["conversation_id"].strip(),
                                           row["source_utterance_index"].strip()))}
        for row in training_rows if _classifiable(row)
    ]
    labeled = [row for row in evaluation_rows if _classifiable(row)]
    status_counts: Counter[str] = Counter()
    act_correct = task_correct = joint_correct = 0
    goal_labeled = goal_correct = 0
    predictions = []
    for row in labeled:
        key = (row["conversation_id"].strip(),
               row["source_utterance_index"].strip())
        actual_goal = _goal(row)
        decision = predict(row, examples,
                           active_goal=active_eval.get(key), threshold=threshold,
                           context_weight=context_weight)
        status_counts[decision["status"]] += 1
        prediction = decision["prediction"]
        if prediction is not None:
            actual_act = row["dialogue_act"].strip()
            actual_task = row["task_intent"].strip()
            act_correct += prediction["dialogue_act"] == actual_act
            task_correct += prediction["task_intent"] == actual_task
            joint_correct += ((prediction["dialogue_act"],
                               prediction["task_intent"])
                              == (actual_act, actual_task))
            if actual_goal is not None:
                goal_labeled += 1
                goal_correct += prediction["goal_intent"] == actual_goal
        predictions.append({
            "citation": row["citation"], "utterance": row["user_utterance"],
            "actual": {"dialogue_act": row["dialogue_act"],
                       "task_intent": row["task_intent"],
                       "goal_intent": actual_goal},
            **decision,
        })
    selected = status_counts["selected"]
    return {
        "experiment": "v1_406_contextual_intent_nearest_neighbor",
        "method": "weighted content-token Jaccard over user turn and previous assistant text; exact typed context gates when labeled",
        "threshold": threshold,
        "context_weight": context_weight,
        "train_conversations": len(train_ids),
        "evaluation_conversations": len(evaluation_ids),
        "evaluation_split": sorted({row["split"].strip()
                                     for row in evaluation_rows}),
        "evaluation_labeler": sorted({row.get("reviewer", "").strip()
                                      for row in evaluation_rows
                                      if row.get("reviewer", "").strip()}),
        "evaluation_basis": "agreement with the named single primary annotator",
        "active_goal_and_context_basis": "prior labeled turns supplied as oracle context; empty typed state/act fields are ungated",
        "labeled_turns": len(labeled),
        "selected": selected,
        "ambiguous": status_counts["ambiguous"],
        "abstained": status_counts["abstain"],
        "coverage": selected / len(labeled) if labeled else 0.0,
        "act_agreement_on_selected": act_correct / selected if selected else None,
        "task_intent_agreement_on_selected": task_correct / selected if selected else None,
        "joint_agreement_on_selected": joint_correct / selected if selected else None,
        "goal_labeled_selected": goal_labeled,
        "goal_agreement_on_labeled_selected": (
            goal_correct / goal_labeled if goal_labeled else None),
        "runtime_effect": "none; offline comparator only",
        "predictions": predictions,
    }


def _self_test() -> None:
    common = {"context_state": "task-in-progress", "predecessor_act": "other",
              "dialogue_act": "request-action", "task_intent": "make-reservation",
              "goal_intent": "make-reservation"}
    train = [{**common, "split": "train", "conversation_id": "train-a",
              "source_utterance_index": "1",
              "user_utterance": "Could you book a table for two?",
              "preceding_context": "ASSISTANT: how many people are in your party?",
              "citation": "source-a#turn=1", "reviewer": "codex-ai-test"}]
    test = [{**common, "split": "test", "conversation_id": "test-a",
             "source_utterance_index": "1",
             "user_utterance": "Please book the table for two.",
             "preceding_context": "ASSISTANT: for how many people?",
             "citation": "source-b#turn=1", "reviewer": "codex-ai-test"}]
    pred = predict(test[0], [{"row": train[0], "terms": _tokens(train[0]["user_utterance"]),
                             "prompt_terms": _tokens(_last_assistant_text(train[0])),
                             "active_goal": "make-reservation"}],
                   active_goal="make-reservation", threshold=0.5,
                   context_weight=0.5)
    if pred["status"] != "selected" or pred["prediction"]["goal_intent"] != "make-reservation":
        raise SystemExit("content-word variation failed to transfer the intent")
    mismatch = predict(test[0], [{"row": train[0],
                                  "terms": _tokens(train[0]["user_utterance"]),
                                  "prompt_terms": _tokens(_last_assistant_text(train[0])),
                                  "active_goal": "make-reservation"}],
                       active_goal=None, threshold=0.5)
    if mismatch["status"] != "abstain":
        raise SystemExit("unmatched active goal did not force abstention")
    yes_train = {**train[0], "user_utterance": "Yes.",
                 "preceding_context": "ASSISTANT: would you like me to book this now?"}
    yes_query = {**test[0], "user_utterance": "Yes!",
                 "preceding_context": "ASSISTANT: would you like me to book this now?"}
    yes_prediction = predict(
        yes_query, [{"row": yes_train, "terms": _tokens("Yes."),
                     "prompt_terms": _tokens(_last_assistant_text(yes_train)),
                     "active_goal": "make-reservation"}],
        active_goal="make-reservation", threshold=0.4, context_weight=0.75)
    if yes_prediction["status"] != "selected":
        raise SystemExit("previous assistant context did not license a short yes")
    conflict = {**train[0], "dialogue_act": "question", "task_intent": "seek-information",
                "goal_intent": "make-reservation", "citation": "source-c#turn=1"}
    pred = predict(test[0], [
        {"row": train[0], "terms": _tokens(train[0]["user_utterance"]),
         "prompt_terms": _tokens(_last_assistant_text(train[0])),
         "active_goal": "make-reservation"},
        {"row": conflict, "terms": _tokens(conflict["user_utterance"]),
         "prompt_terms": _tokens(_last_assistant_text(conflict)),
         "active_goal": "make-reservation"}],
        active_goal="make-reservation", threshold=0.5)
    if pred["status"] != "ambiguous":
        raise SystemExit("equally similar conflicting labels were not abstained")
    print("content-word variation transfers within matching dialogue context: PASS")
    print("previous assistant prompt disambiguates a short yes: PASS")
    print("tied conflicting examples produce ambiguity: PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training_csv", type=Path, nargs="?")
    parser.add_argument("evaluation_csv", type=Path, nargs="?")
    parser.add_argument("output_json", type=Path, nargs="?")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--context-weight", type=float, default=0.0,
                        help="weight for content-word Jaccard on prior assistant text")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    if args.training_csv is None or args.evaluation_csv is None or args.output_json is None:
        parser.error("provide training_csv, evaluation_csv, and output_json")
    with args.training_csv.open(encoding="utf-8", newline="") as handle:
        training_rows = list(csv.DictReader(handle))
    with args.evaluation_csv.open(encoding="utf-8", newline="") as handle:
        evaluation_rows = list(csv.DictReader(handle))
    result = evaluate(training_rows, evaluation_rows, threshold=args.threshold,
                      context_weight=args.context_weight)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    summary = {key: value for key, value in result.items() if key != "predictions"}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
