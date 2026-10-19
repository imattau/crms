"""Measure the hand-checked intent router with annotated context supplied.

This is an oracle-context diagnostic: context_state, predecessor_act, and prior
task intent come from provisional labels. It is not end-to-end performance or
independent validation of those labels.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, is_open_yes_no_prompt
from crms_dialogue import CRMSDialogue, infer_open_question_slot
from crms_dialogue_intent import CRMSDialogueIntentModel
from crms_knowledge import CRMSKnowledgeBase


ACTIVE_TASKS = {
    "check-availability", "make-reservation", "change-reservation",
    "cancel-reservation", "correct-prior-result", "correct-result",
    "seek-information", "provide-information", "other-task",
}


def make_dialogue(row: dict[str, str], active_task: str | None,
                  knowledge: CRMSKnowledgeBase, *, oracle_context: bool = True,
                  question_type_from_prompt: bool = False
                  ) -> CRMSDialogue:
    dialogue = CRMSDialogue(knowledge, intent_model=CRMSDialogueIntentModel())
    if not oracle_context:
        return dialogue
    dialogue.active_task_intent = active_task
    state = row["context_state"].strip()
    if state in {"awaiting-user-detail", "awaiting-confirmation"}:
        assistant_turns = re.findall(
            r"(?im)^ASSISTANT:\s*(.+?)\s*$", row["preceding_context"])
        prompt = assistant_turns[-1] if assistant_turns else ""
        answer_kind = "yes-no" if state == "awaiting-confirmation" else "detail"
        if question_type_from_prompt:
            answer_kind = ("yes-no" if is_open_yes_no_prompt(prompt) else "detail")
        dialogue.open_dialogue_question = {
            "prompt": prompt[:512], "answer_kind": answer_kind,
            "expected_slot": infer_open_question_slot(prompt, answer_kind),
        }
        dialogue.history.append({"act": "question", "utterance": prompt[:200],
                                 "status": "clarify"})
    elif state in {"answer-follow-up", "correction-or-challenge"}:
        dialogue.last_answered = {"question": "", "answer": ""}
    if row["predecessor_act"].strip() == "answer":
        dialogue.last_answered = dialogue.last_answered or {
            "question": "", "answer": ""}
    return dialogue


def evaluate(path: Path, *, question_type_from_prompt: bool = False) -> dict:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("label file is empty")
    required = {"split", "conversation_id", "source_utterance_index",
                "user_utterance", "dialogue_act", "task_intent",
                "context_state", "predecessor_act", "reviewer",
                "preceding_context"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"missing columns: {', '.join(sorted(missing))}")
    reviewers = {row["reviewer"].strip() for row in rows if row["reviewer"].strip()}
    if len(reviewers) != 1 or not next(iter(reviewers), "").startswith("codex-ai-"):
        raise ValueError("expected one explicitly identified Codex labeler")

    by_conversation: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_conversation.setdefault(row["conversation_id"].strip(), []).append(row)
    active_before: dict[tuple[str, str], str | None] = {}
    for conversation_id, conversation_rows in by_conversation.items():
        active: str | None = None
        for row in sorted(conversation_rows,
                          key=lambda item: int(item["source_utterance_index"])):
            key = (conversation_id, row["source_utterance_index"].strip())
            active_before[key] = active
            intent = row["task_intent"].strip()
            if intent == "end-interaction":
                active = None
            elif intent in ACTIVE_TASKS:
                active = intent

    eligible = [row for row in rows
                if row["dialogue_act"].strip() not in {"", "uncertain"}
                and row["task_intent"].strip() not in {"", "uncertain"}]
    counts = {"labeled_turns": len(eligible), "hypothesized": 0,
              "selected": 0, "ambiguous": 0, "no_hypothesis": 0,
              "act_matches": 0, "intent_matches": 0, "joint_matches": 0,
              "hypothesized_act_matches": 0, "hypothesized_intent_matches": 0,
              "hypothesized_joint_matches": 0}
    predictions = []
    knowledge = CRMSKnowledgeBase()
    context_free_hypothesized = context_free_matches = 0
    for row in eligible:
        key = (row["conversation_id"].strip(),
               row["source_utterance_index"].strip())
        active = active_before.get(key)
        context_free = classify_user_intent(
            make_dialogue(row, active, knowledge, oracle_context=False,
                          question_type_from_prompt=question_type_from_prompt),
            row["user_utterance"])
        if context_free is not None:
            context_free_hypothesized += 1
            context_free_matches += (
                context_free.dialogue_act, context_free.task_intent
            ) == (row["dialogue_act"].strip(), row["task_intent"].strip())
        dialogue = make_dialogue(
            row, active, knowledge,
            question_type_from_prompt=question_type_from_prompt)
        hypothesis = classify_user_intent(dialogue, row["user_utterance"])
        expected = (row["dialogue_act"].strip(), row["task_intent"].strip())
        if hypothesis is None:
            counts["no_hypothesis"] += 1
            predicted = None
        else:
            counts["hypothesized"] += 1
            selected = hypothesis.decision == "selected"
            counts["selected" if selected else "ambiguous"] += 1
            predicted = (hypothesis.dialogue_act, hypothesis.task_intent)
            counts["act_matches"] += predicted[0] == expected[0]
            counts["intent_matches"] += predicted[1] == expected[1]
            counts["joint_matches"] += predicted == expected
            if selected:
                counts["hypothesized_act_matches"] += predicted[0] == expected[0]
                counts["hypothesized_intent_matches"] += predicted[1] == expected[1]
                counts["hypothesized_joint_matches"] += predicted == expected
        predictions.append({
            "citation": row["citation"], "utterance": row["user_utterance"],
            "context_state": row["context_state"], "active_task": active,
            "label": list(expected),
            "prediction": list(predicted) if predicted else None,
            "decision": hypothesis.decision if hypothesis else "abstain",
            "matched_frame": hypothesis.matched_frame if hypothesis else None,
        })
    counts.update({
        "experiment": ("v1_401_transcript_question_type_replay"
                       if question_type_from_prompt else
                       "v1_395_runtime_intent_oracle_context"),
        "labeler": next(iter(reviewers)),
        "evaluation_basis": "agreement with one provisional Codex labeler",
        "context_basis": (
            "oracle open-question presence, predecessor act, and prior labeled task intent; "
            "question type and slot inferred from the preceding assistant prompt"
            if question_type_from_prompt else
            "oracle context_state and predecessor labels, plus prior labeled task intent"),
        "scope_warning": "not end-to-end performance, independent review, or accuracy",
        "coverage": counts["hypothesized"] / len(eligible) if eligible else 0,
        "agreement_given_hypothesis": {
            "act": counts["act_matches"] / counts["hypothesized"] if counts["hypothesized"] else None,
            "task_intent": counts["intent_matches"] / counts["hypothesized"] if counts["hypothesized"] else None,
            "joint": counts["joint_matches"] / counts["hypothesized"] if counts["hypothesized"] else None,
        },
        "selected_agreement": {
            "act": counts["hypothesized_act_matches"] / counts["selected"] if counts["selected"] else None,
            "task_intent": counts["hypothesized_intent_matches"] / counts["selected"] if counts["selected"] else None,
            "joint": counts["hypothesized_joint_matches"] / counts["selected"] if counts["selected"] else None,
        },
        "context_free_baseline": {
            "hypothesized": context_free_hypothesized,
            "coverage": context_free_hypothesized / len(eligible) if eligible else 0,
            "exact_label_matches": context_free_matches,
            "exact_label_match_rate_over_hypotheses": (
                context_free_matches / context_free_hypothesized
                if context_free_hypothesized else None),
        },
        "predictions": predictions,
    })
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--question-type-from-prompt", action="store_true",
                        help="infer open-question type from the latest assistant prompt")
    args = parser.parse_args()
    report = evaluate(args.labels,
                      question_type_from_prompt=args.question_type_from_prompt)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
