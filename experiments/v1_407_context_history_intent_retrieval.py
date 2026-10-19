"""Evaluate dialogue intent retrieval with cited multi-turn history context.

This is an offline research comparator. It reconstructs each conversation's
preceding turns from citation offsets, then combines user-utterance similarity,
the latest assistant wording, and similarity between earlier same-speaker
context turns. It never changes runtime routing or factual knowledge.
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
from experiments.v1_406_contextual_intent_nearest_neighbor import (
    _classifiable, _goal, _jaccard, _tokens,
)


def _history(row: dict[str, str], file_cache: dict[Path, str], *,
             verify_span: bool = True) -> list[tuple[str, str]]:
    """Read speaker turns preceding the cited utterance without changing source text."""
    citation = row.get("citation", "")
    source, separator, fragment = citation.partition("#")
    if not separator:
        raise ValueError(f"citation has no fragment: {citation}")
    match = re.search(r"(?:^|&)chars=(\d+):(\d+)(?:&|$)", fragment)
    if not match:
        raise ValueError(f"citation has no character span: {citation}")
    start, end = map(int, match.groups())
    path = Path(source)
    if path not in file_cache:
        file_cache[path] = path.read_text(encoding="utf-8")
    text = file_cache[path]
    if not 0 <= start <= end <= len(text):
        raise ValueError(f"citation span is outside source: {citation}")
    if verify_span and text[start:end] != row["user_utterance"]:
        raise ValueError(f"citation span does not match user turn: {citation}")
    return [(speaker.upper(), utterance.strip()) for speaker, utterance in
            re.findall(r"(?im)^(USER|ASSISTANT):\s*(.+?)\s*$", text[:start])]


def _active_before(rows: list[dict[str, str]]) -> dict[tuple[str, str], str | None]:
    by_conversation: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_conversation[row["conversation_id"].strip()].append(row)
    active_before = {}
    for conversation_id, turns in by_conversation.items():
        active_goal: str | None = None
        for row in sorted(turns, key=lambda item: int(item["source_utterance_index"])):
            key = (conversation_id, row["source_utterance_index"].strip())
            active_before[key] = active_goal
            goal = _goal(row)
            task = row.get("task_intent", "").strip()
            if goal is not None:
                active_goal = goal
            elif task == "end-interaction":
                active_goal = None
            elif task in ACTIVE_TASK_INTENTS:
                active_goal = task
    return active_before


def _history_score(query: list[tuple[str, str]], source: list[tuple[str, str]],
                   window: int) -> float:
    q = [(speaker, _tokens(text)) for speaker, text in query[-window:]]
    s = [(speaker, _tokens(text)) for speaker, text in source[-window:]]
    similarities = sorted(
        (_jaccard(q_terms, s_terms)
         for q_speaker, q_terms in q
         for s_speaker, s_terms in s
         if q_speaker == s_speaker and q_terms and s_terms),
        reverse=True,
    )
    if not similarities:
        return 0.0
    # Two best same-speaker context matches reduce sensitivity to one stray word.
    return sum(similarities[:2]) / min(2, len(similarities))


def predict(row: dict[str, Any], training: list[dict[str, Any]], *,
            active_goal: str | None, threshold: float = 0.4,
            user_weight: float = 0.45, latest_assistant_weight: float = 0.15,
            history_weight: float = 0.4, window: int = 4) -> dict[str, Any]:
    if abs(user_weight + latest_assistant_weight + history_weight - 1.0) > 1e-9:
        raise ValueError("similarity weights must sum to 1")
    query_terms = _tokens(row["user_utterance"])
    query_history = row["_history"][-window:]
    query_assistants = [_tokens(text) for speaker, text in query_history
                        if speaker == "ASSISTANT"]
    eligible = []
    for example in training:
        source = example["row"]
        if (row.get("context_state", "").strip()
                and source.get("context_state", "").strip()
                and row["context_state"].strip() != source["context_state"].strip()):
            continue
        if (row.get("predecessor_act", "").strip()
                and source.get("predecessor_act", "").strip()
                and row["predecessor_act"].strip() != source["predecessor_act"].strip()):
            continue
        if active_goal != example["active_goal"]:
            continue
        user_similarity = _jaccard(query_terms, example["user_terms"])
        source_assistants = [_tokens(text)
                             for speaker, text in example["history"][-window:]
                             if speaker == "ASSISTANT"]
        assistant_similarity = (
            _jaccard(query_assistants[-1], source_assistants[-1])
            if query_assistants and source_assistants else 0.0)
        context_similarity = _history_score(query_history, example["history"], window)
        similarity = (user_weight * user_similarity
                      + latest_assistant_weight * assistant_similarity
                      + history_weight * context_similarity)
        if similarity >= threshold:
            eligible.append((similarity, example))
    if not eligible:
        return {"status": "abstain", "similarity": None,
                "prediction": None, "sources": []}
    best = max(score for score, _ in eligible)
    nearest = [example for score, example in eligible if score == best]
    signatures = {
        (item["row"]["dialogue_act"].strip(),
         item["row"]["task_intent"].strip(), _goal(item["row"]))
        for item in nearest
    }
    citations = sorted({item["row"].get("citation", "").strip()
                        for item in nearest})
    if len(signatures) != 1:
        return {"status": "ambiguous", "similarity": best,
                "prediction": None, "sources": citations,
                "alternatives": [list(item) for item in sorted(
                    signatures, key=lambda value: str(value))]}
    act, task, goal = next(iter(signatures))
    return {"status": "selected", "similarity": best,
            "prediction": {"dialogue_act": act, "task_intent": task,
                           "goal_intent": goal}, "sources": citations}


def evaluate(training_rows: list[dict[str, str]], evaluation_rows: list[dict[str, str]],
             *, threshold: float, user_weight: float, latest_assistant_weight: float,
             history_weight: float, window: int) -> dict[str, Any]:
    if not training_rows or not evaluation_rows:
        raise ValueError("training and evaluation sheets must be non-empty")
    if any(row["split"].strip() != "train" for row in training_rows):
        raise ValueError("training input must contain train rows only")
    if any(row["split"].strip() not in {"dev", "test"} for row in evaluation_rows):
        raise ValueError("evaluation input must contain dev or test rows only")
    train_ids = {row["conversation_id"].strip() for row in training_rows}
    eval_ids = {row["conversation_id"].strip() for row in evaluation_rows}
    if train_ids & eval_ids:
        raise ValueError("training/evaluation conversation leakage")
    cache: dict[Path, str] = {}
    active_train = _active_before(training_rows)
    active_eval = _active_before(evaluation_rows)
    examples = []
    for row in training_rows:
        if not _classifiable(row):
            continue
        key = (row["conversation_id"].strip(), row["source_utterance_index"].strip())
        examples.append({"row": row, "user_terms": _tokens(row["user_utterance"]),
                         "history": _history(row, cache),
                         "active_goal": active_train.get(key)})
    labeled = [row for row in evaluation_rows if _classifiable(row)]
    counts: Counter[str] = Counter()
    act_correct = task_correct = joint_correct = goal_correct = goal_n = 0
    predictions = []
    for row in labeled:
        key = (row["conversation_id"].strip(), row["source_utterance_index"].strip())
        decision = predict(
            {**row, "_history": _history(row, cache)}, examples,
            active_goal=active_eval.get(key), threshold=threshold,
            user_weight=user_weight, latest_assistant_weight=latest_assistant_weight,
            history_weight=history_weight, window=window,
        )
        counts[decision["status"]] += 1
        guess = decision["prediction"]
        if guess is not None:
            actual_act = row["dialogue_act"].strip()
            actual_task = row["task_intent"].strip()
            actual_goal = _goal(row)
            act_correct += guess["dialogue_act"] == actual_act
            task_correct += guess["task_intent"] == actual_task
            joint_correct += (guess["dialogue_act"], guess["task_intent"]) == (actual_act, actual_task)
            if actual_goal is not None:
                goal_n += 1
                goal_correct += guess["goal_intent"] == actual_goal
        predictions.append({"citation": row["citation"], "utterance": row["user_utterance"],
                            "actual": {"dialogue_act": row["dialogue_act"],
                                       "task_intent": row["task_intent"],
                                       "goal_intent": _goal(row)}, **decision})
    n = len(labeled)
    selected = counts["selected"]
    return {
        "experiment": "v1_407_context_history_intent_retrieval",
        "method": "content-token Jaccard over user turn, latest assistant turn, and up to four cited prior speaker turns; exact state, predecessor, and active-goal gates",
        "threshold": threshold,
        "weights": {"user": user_weight, "latest_assistant": latest_assistant_weight,
                    "history": history_weight},
        "history_window_turns": window,
        "train_conversations": len(train_ids), "evaluation_conversations": len(eval_ids),
        "evaluation_split": sorted({r["split"].strip() for r in evaluation_rows}),
        "evaluation_labeler": sorted({r.get("reviewer", "").strip()
                                      for r in evaluation_rows if r.get("reviewer", "").strip()}),
        "evaluation_basis": "agreement with the named single primary annotator",
        "active_goal_and_context_basis": "prior labeled goals and context supplied as oracle input",
        "labeled_turns": n, "selected": selected,
        "ambiguous": counts["ambiguous"], "abstained": counts["abstain"],
        "coverage": selected / n if n else 0,
        "act_agreement_on_selected": act_correct / selected if selected else None,
        "task_intent_agreement_on_selected": task_correct / selected if selected else None,
        "joint_agreement_on_selected": joint_correct / selected if selected else None,
        "goal_labeled_selected": goal_n,
        "goal_agreement_on_labeled_selected": goal_correct / goal_n if goal_n else None,
        "runtime_effect": "none; offline comparator only",
        "predictions": predictions,
    }


def _self_test() -> None:
    # Test citation reconstruction on a real indexed source when the Taskmaster
    # scratch corpus is present; otherwise the core scoring helpers remain usable.
    sample = Path("/tmp/crms_dialogue_feasibility_v1/test_frozen_labeled.csv")
    if sample.exists():
        with sample.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        cache: dict[Path, str] = {}
        for row in rows:
            _history(row, cache)
        print(f"verified {len(rows)} exact source spans and recovered cited dialogue histories: PASS")
    # A selected option remains visible even after the assistant's latest
    # response has moved to a different reservation detail.
    query = [("ASSISTANT", "The options are Bistro Z and Pasta Corner."),
             ("USER", "What is the price?"),
             ("ASSISTANT", "Bistro Z is moderately priced."),
             ("USER", "Let's choose that one.")]
    source = [("ASSISTANT", "The options are Bistro Z and Pasta Corner."),
              ("USER", "What is the wait time?"),
              ("ASSISTANT", "Bistro Z has a short wait."),
              ("USER", "I would like that one.")]
    if _history_score(query, source, 4) <= 0:
        raise SystemExit("multi-turn option context was not recovered")
    # Unrelated task history must not manufacture context overlap.
    if _history_score([("USER", ""), ("ASSISTANT", "Where would you like to eat?")],
                      [("USER", ""), ("ASSISTANT", "How many people are dining?")], 4) != 0:
        raise SystemExit("unrelated dialogue history unexpectedly matched")
    print("multi-turn option context is retained and unrelated history stays separate: PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("training_csv", type=Path, nargs="?")
    parser.add_argument("evaluation_csv", type=Path, nargs="?")
    parser.add_argument("output_json", type=Path, nargs="?")
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--user-weight", type=float, default=0.45)
    parser.add_argument("--assistant-weight", type=float, default=0.15)
    parser.add_argument("--history-weight", type=float, default=0.4)
    parser.add_argument("--window", type=int, default=4)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    if not args.training_csv or not args.evaluation_csv:
        parser.error("training_csv and evaluation_csv are required unless --self-test is used")
    with args.training_csv.open(encoding="utf-8", newline="") as handle:
        training = list(csv.DictReader(handle))
    with args.evaluation_csv.open(encoding="utf-8", newline="") as handle:
        evaluation = list(csv.DictReader(handle))
    report = evaluate(training, evaluation, threshold=args.threshold,
                      user_weight=args.user_weight,
                      latest_assistant_weight=args.assistant_weight,
                      history_weight=args.history_weight, window=args.window)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output_json:
        args.output_json.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
