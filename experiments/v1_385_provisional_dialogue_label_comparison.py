"""Compare the current context-free intent baseline with single-AI labels.

This is a development diagnostic, not an accuracy evaluation. The labels in
the feasibility batch were entered by one AI annotator and have no independent
second-rater review. A matching output therefore measures agreement with that
annotator, not correctness or generalization.

Run with:
    python3 experiments/v1_385_provisional_dialogue_label_comparison.py \
        /tmp/crms_dialogue_feasibility_v1/user_turns_to_label.csv
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_conversation import classify_user_intent
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def _mapped_act(value: str) -> str:
    return {
        "reaction": "other",
        "elaboration": "continuation-request",
        "cancel-follow-up": "continuation-request",
    }.get(value, value)


def evaluate(path: Path) -> dict:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "split", "user_utterance", "dialogue_act", "task_intent",
            "context_state", "reviewer", "reviewer_2",
            "adjudicated_dialogue_act", "adjudicated_task_intent",
        }
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input lacks columns: {', '.join(sorted(missing))}")
        rows = list(reader)

    annotators = {row["reviewer"].strip() for row in rows if row["reviewer"].strip()}
    if len(annotators) != 1 or not all(
            annotator.startswith("codex-ai-") for annotator in annotators):
        raise ValueError("this diagnostic only accepts one explicitly identified AI annotator")
    if any(row["reviewer_2"].strip()
           or row["adjudicated_dialogue_act"].strip()
           or row["adjudicated_task_intent"].strip() for row in rows):
        raise ValueError("independent or adjudicated labels require a separate evaluator")

    aggregate = Counter()
    by_act: dict[str, Counter] = defaultdict(Counter)
    by_intent: dict[str, Counter] = defaultdict(Counter)
    by_context: dict[str, Counter] = defaultdict(Counter)
    predicted_acts: Counter[str] = Counter()
    predicted_intents: Counter[str] = Counter()
    for row in rows:
        aggregate["total"] += 1
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        hypothesis = classify_user_intent(dialogue, row["user_utterance"])
        groups = (
            (by_act, row["dialogue_act"]),
            (by_intent, row["task_intent"]),
            (by_context, row["context_state"]),
        )
        if hypothesis is None:
            aggregate["no_hypothesis"] += 1
            for table, key in groups:
                table[key]["no_hypothesis"] += 1
            continue

        aggregate["hypothesis"] += 1
        if hypothesis.decision == "selected":
            aggregate["selected"] += 1
        else:
            aggregate["ambiguous_or_unlicensed"] += 1

        predicted_act = _mapped_act(hypothesis.dialogue_act)
        predicted_acts[predicted_act] += 1
        predicted_intents[hypothesis.task_intent or "<none>"] += 1
        act_match = predicted_act == row["dialogue_act"]
        intent_match = hypothesis.task_intent == row["task_intent"]
        aggregate["act_label_matches"] += act_match
        aggregate["intent_label_matches"] += intent_match
        aggregate["both_label_matches"] += act_match and intent_match
        by_act[row["dialogue_act"]]["hypothesis"] += 1
        by_act[row["dialogue_act"]]["act_match"] += act_match
        by_intent[row["task_intent"]]["hypothesis"] += 1
        by_intent[row["task_intent"]]["intent_match"] += intent_match
        by_context[row["context_state"]]["hypothesis"] += 1

    def breakdown(table: dict[str, Counter], match_key: str) -> dict:
        result = {}
        for key, counts in sorted(table.items()):
            total = counts["hypothesis"] + counts["no_hypothesis"]
            item = {"total": total, **dict(sorted(counts.items()))}
            item["coverage"] = counts["hypothesis"] / total if total else None
            if match_key:
                item["label_match_rate_on_hypotheses"] = (
                    counts[match_key] / counts["hypothesis"]
                    if counts["hypothesis"] else None)
            result[key] = item
        return result

    total = aggregate["total"]
    predicted = aggregate["hypothesis"]
    return {
        "diagnostic": "context_free_baseline_vs_single_ai_labels",
        "label_source": next(iter(annotators)),
        "accuracy_claimed": False,
        "state_policy": "fresh-empty-dialogue-per-utterance",
        "summary": {
            **dict(sorted(aggregate.items())),
            "hypothesis_coverage": aggregate["hypothesis"] / total if total else None,
            "selected_intent_coverage": aggregate["selected"] / total if total else None,
            "act_label_match_rate_on_hypotheses": (
                aggregate["act_label_matches"] / predicted if predicted else None),
            "intent_label_match_rate_on_hypotheses": (
                aggregate["intent_label_matches"] / predicted if predicted else None),
            "both_label_match_rate_on_hypotheses": (
                aggregate["both_label_matches"] / predicted if predicted else None),
        },
        "by_annotated_dialogue_act": breakdown(by_act, "act_match"),
        "by_annotated_task_intent": breakdown(by_intent, "intent_match"),
        "by_context_state": breakdown(by_context, ""),
        "predicted_dialogue_acts": dict(sorted(predicted_acts.items())),
        "predicted_task_intents": dict(sorted(predicted_intents.items())),
        "limitations": [
            "One AI annotator supplied the comparison labels; they are not independent human gold.",
            "The intent baseline receives an empty dialogue state for every turn.",
            "This measures label agreement and abstention only, not answer quality or task success.",
            "Do not use these figures to claim held-out accuracy or to license model frames.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_turns", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(args.user_turns)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        print(f"Could not compare provisional dialogue labels: {error}",
              file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
