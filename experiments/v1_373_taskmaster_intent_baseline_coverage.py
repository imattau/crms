"""Measure contextual-intent rule coverage without treating it as accuracy.

Run with:
    python3 experiments/v1_373_taskmaster_intent_baseline_coverage.py \
        /path/to/user_turns_to_label.csv

Each utterance is evaluated in a fresh, empty dialogue state. This deliberately
measures the current phrase-level baseline without giving it dialogue context.
It is a coverage diagnostic only; human annotations are required to assess
whether a hypothesis is correct or whether context would resolve it.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_conversation import classify_user_intent
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def evaluate(path: Path) -> dict:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"split", "user_utterance"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input lacks columns: {', '.join(sorted(missing))}")
        rows = list(reader)

    by_split: dict[str, Counter] = {}
    decisions: Counter[tuple[str, str, str]] = Counter()
    for row_number, row in enumerate(rows, 2):
        split = row["split"].strip() or "unspecified"
        utterance = row["user_utterance"]
        if not isinstance(utterance, str):
            raise ValueError(f"row {row_number} has no utterance text")
        counts = by_split.setdefault(split, Counter())
        counts["total"] += 1
        hypothesis = classify_user_intent(
            CRMSDialogue(CRMSKnowledgeBase()), utterance)
        if hypothesis is None:
            counts["no_hypothesis"] += 1
            continue
        counts["hypothesis"] += 1
        if (hypothesis.decision == "selected"
                and hypothesis.task_intent is not None):
            counts["selected_intent"] += 1
        else:
            counts["ambiguous_or_unlicensed"] += 1
        decisions[(hypothesis.dialogue_act, hypothesis.task_intent or "none",
                   hypothesis.decision)] += 1

    result = {"diagnostic": "context-free-user-intent-rule-coverage",
              "accuracy_claimed": False,
              "state_policy": "fresh-empty-dialogue-per-utterance",
              "splits": {}}
    for split, counts in sorted(by_split.items()):
        total = counts["total"]
        result["splits"][split] = {
            **dict(sorted(counts.items())),
            "hypothesis_coverage": counts["hypothesis"] / total if total else None,
            "selected_intent_coverage": counts["selected_intent"] / total
            if total else None,
        }
    result["hypotheses"] = [
        {"dialogue_act": act, "task_intent": intent, "decision": decision,
         "count": count}
        for (act, intent, decision), count in sorted(decisions.items())
    ]
    result["limitations"] = [
        "Coverage is not correctness; the annotation sheets must be completed for accuracy.",
        "Fresh empty state intentionally excludes preceding-turn context.",
        "A missing hypothesis may be appropriate for content turns and slot values.",
        "The current runtime rules are hand-checked, not learned from this corpus.",
    ]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_turns", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = evaluate(args.user_turns)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
