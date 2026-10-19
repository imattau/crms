"""Compare context-free intent classification with transcript-context replay.

The replay reconstructs only the latest assistant question from the cited
transcript context and carries task goals forward from CRMS's own predictions.
It does not use annotation labels to build runtime state. Label columns are
read only for post-hoc agreement. Agreement with Codex-primary labels is not
accuracy or independent validation.

Usage:
    python3 experiments/v1_436_transcript_context_intent_replay.py \
        /path/to/labeled_user_turns.csv [--json-out report.json]
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

_OPENING_INVITATION_RE = re.compile(
    r"^(?:(?:good\s+(?:morning|afternoon|evening)|hi|hello|hey)"
    r"(?:\s+there)?[,!. ]+)?"
    r"(?:how\s+(?:can|may)\s+i\s+(?:help|assist)(?:\s+you)?|"
    r"what\s+can\s+i\s+do\s+for\s+you|how\s+are\s+you)\??$",
    flags=re.IGNORECASE)

from crms_conversation import classify_user_intent, is_open_yes_no_prompt
from crms_dialogue import CRMSDialogue, DialogueTurn, infer_open_question_slot
from crms_knowledge import CRMSKnowledgeBase


def _latest_assistant_question(context: str) -> dict[str, str] | None:
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    if not lines or not lines[-1].upper().startswith("ASSISTANT:"):
        return None
    prompt = lines[-1].split(":", 1)[1].strip()
    if not prompt:
        return None
    # A conversational opening invites the user to state a goal. It does not
    # establish a typed pending detail that should capture the first request.
    if _OPENING_INVITATION_RE.fullmatch(prompt):
        return None
    confirmation_statement = bool(re.fullmatch(
        r"(?:so\s+)?i\s+have\b.+", prompt, flags=re.IGNORECASE))
    if not ("?" in prompt or confirmation_statement):
        return None
    answer_kind = "yes-no" if is_open_yes_no_prompt(prompt) else "detail"
    return {
        "prompt": prompt[:500],
        "answer_kind": answer_kind,
        "expected_slot": infer_open_question_slot(prompt, answer_kind),
    }


def _new_dialogue() -> CRMSDialogue:
    return CRMSDialogue(CRMSKnowledgeBase())


def _run_context_free(rows: list[dict[str, str]]) -> dict[str, dict]:
    predictions = {}
    for row in rows:
        h = classify_user_intent(_new_dialogue(), row["user_utterance"])
        predictions[row["conversation_id"] + ":" + row["utterance_index"]] = h
    return predictions


def _run_replay(rows: list[dict[str, str]]) -> dict[str, dict]:
    by_conversation: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_conversation[row["conversation_id"]].append(row)
    predictions = {}
    for conversation_id, conversation_rows in sorted(by_conversation.items()):
        dialogue = _new_dialogue()
        for row in sorted(conversation_rows,
                          key=lambda item: int(item["utterance_index"])):
            dialogue.open_dialogue_question = _latest_assistant_question(
                row["preceding_context"])
            utterance = row["user_utterance"]
            hypothesis = classify_user_intent(dialogue, utterance)
            key = conversation_id + ":" + row["utterance_index"]
            predictions[key] = hypothesis
            if hypothesis is not None:
                act = hypothesis.dialogue_act
                status = "intent-hypothesis"
            else:
                act = "unclassified"
                status = "no-intent-hypothesis"
            # Carry only state produced by CRMS's own current classifier.
            # The original assistant line supplies a typed open question, but
            # no annotated intent, goal, slot value, or expected answer.
            dialogue.record_turn(
                utterance, act,
                DialogueTurn(status, utterance, utterance), hypothesis)
    return predictions


def _measure(rows: list[dict[str, str]], predictions: dict[str, dict]) -> dict:
    counts = Counter()
    by_act: dict[str, Counter] = defaultdict(Counter)
    by_task: dict[str, Counter] = defaultdict(Counter)
    by_context: dict[str, Counter] = defaultdict(Counter)
    disagreements = []
    for row in rows:
        key = row["conversation_id"] + ":" + row["utterance_index"]
        h = predictions[key]
        gold_act = row.get("codex_dialogue_act", "").strip()
        gold_task = row.get("codex_task_intent", "").strip()
        if not gold_act or not gold_task:
            continue
        counts["labeled"] += 1
        if gold_act == "uncertain" or gold_task == "uncertain":
            counts["uncertain_label"] += 1
        group = row["conversation_id"]
        counts["conversations"] = len({
            item["conversation_id"] for item in rows
            if item.get("codex_dialogue_act", "").strip()
        })
        if h is None:
            counts["no_hypothesis"] += 1
            by_act[gold_act]["no_hypothesis"] += 1
            by_task[gold_task]["no_hypothesis"] += 1
            context_state = row.get("codex_context_state", "") or "unspecified"
            by_context[context_state]["no_hypothesis"] += 1
            continue
        counts["hypothesis"] += 1
        if h.decision == "selected" and h.task_intent is not None:
            counts["selected_intent"] += 1
        else:
            counts["ambiguous_or_unlicensed"] += 1
        act_match = h.dialogue_act == gold_act
        task_match = h.task_intent == gold_task
        joint_match = act_match and task_match
        counts["act_match"] += act_match
        counts["task_match"] += task_match
        counts["joint_match"] += joint_match
        by_act[gold_act]["hypothesis"] += 1
        by_act[gold_act]["act_match"] += act_match
        by_task[gold_task]["hypothesis"] += 1
        by_task[gold_task]["task_match"] += task_match
        context_state = row.get("codex_context_state", "") or "unspecified"
        by_context[context_state]["hypothesis"] += 1
        if not joint_match:
            disagreements.append({
                "conversation_id": row["conversation_id"],
                "utterance_index": row["utterance_index"],
                "utterance": row["user_utterance"],
                "expected": {"dialogue_act": gold_act,
                             "task_intent": gold_task},
                "predicted": {"dialogue_act": h.dialogue_act,
                              "task_intent": h.task_intent,
                              "decision": h.decision,
                              "matched_frame": h.matched_frame},
            })

    n = counts["labeled"]
    nh = counts["hypothesis"]
    return {
        **dict(sorted(counts.items())),
        "hypothesis_coverage": counts["hypothesis"] / n if n else None,
        "selected_intent_coverage": counts["selected_intent"] / n if n else None,
        "joint_label_agreement_all_labeled": counts["joint_match"] / n if n else None,
        "joint_label_agreement_on_hypotheses": counts["joint_match"] / nh if nh else None,
        "disagreements": disagreements,
    }


def evaluate(path: Path) -> dict:
    required = {"conversation_id", "utterance_index", "preceding_context",
                "user_utterance", "codex_dialogue_act", "codex_task_intent"}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError("input lacks columns: " + ", ".join(sorted(missing)))
        rows = list(reader)
    labeled = [row for row in rows
               if row["codex_dialogue_act"].strip()
               and row["codex_task_intent"].strip()]
    if not labeled:
        raise ValueError("input contains no primary labels")
    if (_latest_assistant_question("ASSISTANT: How can I help you?") is not None
            or _latest_assistant_question("ASSISTANT: hi, how may I assist you?") is not None
            or _latest_assistant_question("ASSISTANT: Good morning how can I help you?") is not None
            or _latest_assistant_question("ASSISTANT: What movie would you like to see?") is None):
        raise AssertionError("opening-invitation/question distinction regressed")
    return {
        "diagnostic": "transcript_context_intent_replay",
        "label_provenance": "Codex primary labels; not independent gold",
        "accuracy_claimed": False,
        "context_free": _measure(labeled, _run_context_free(labeled)),
        "transcript_replay": _measure(labeled, _run_replay(labeled)),
        "replay_policy": [
            "Reconstruct only the final visible assistant question from preceding_context.",
            "Carry active goal only when selected by CRMS's own prior intent hypothesis.",
            "Do not use annotated intent, goal, slot values, or expected answer to build state.",
            "This replays the intent classifier; it does not simulate complete assistant responses.",
        ],
        "limitations": [
            "One Codex annotator supplied the labels; agreement is not accuracy.",
            "The sample is small and comes from one transactional movie-ticket corpus.",
            "Context is limited to the prepared preceding_context window.",
            "A source-inferred question kind is a deterministic replay approximation.",
            "The initial replay output exposed an opening-invitation parsing error; this sample is exploratory for parser design and is not untouched validation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labeled_user_turns", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(args.labeled_user_turns)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        print(f"Could not replay dialogue intent: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
