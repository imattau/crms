"""Measure when identical user wording has different contextual intents.

This is a descriptive diagnostic over the authorized, single-Codex-label
Taskmaster feasibility batch. It does not measure label correctness, train an
intent model, or license runtime frames.

Run with:
    python3 experiments/v1_387_contextual_intent_ambiguity.py USER_TURNS.csv
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import sys
import unicodedata


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def normalize_surface(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+(?:['’]\w+)*", value, re.UNICODE))


def _label(row: dict[str, str]) -> tuple[str, str]:
    return row["dialogue_act"].strip(), row["task_intent"].strip()


def analyze(path: Path) -> dict:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "conversation_id", "user_utterance", "dialogue_act", "task_intent",
            "context_state", "predecessor_act", "reviewer", "citation",
        }
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input lacks columns: {', '.join(sorted(missing))}")
        rows = list(reader)

    annotators = {row["reviewer"].strip() for row in rows if row["reviewer"].strip()}
    if len(annotators) != 1 or not next(iter(annotators), "").startswith("codex-ai-"):
        raise ValueError("expected one explicitly identified Codex AI annotator")
    for number, row in enumerate(rows, 2):
        if not row["citation"].strip() or not row["conversation_id"].strip():
            raise ValueError(f"row {number} lacks source citation or conversation ID")
        if not _label(row)[0] or not _label(row)[1]:
            raise ValueError(f"row {number} lacks primary intent labels")

    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        surface = normalize_surface(row["user_utterance"])
        if surface:
            groups[surface].append(row)

    repeated: dict[str, list[dict[str, str]]] = {
        surface: group for surface, group in groups.items()
        if len({row["conversation_id"] for row in group}) >= 2
    }
    ambiguous = {
        surface: group for surface, group in repeated.items()
        if len({_label(row) for row in group}) > 1
    }

    def context_stats(features: tuple[str, ...]) -> dict:
        resolved = unresolved = 0
        rows_resolved = rows_unresolved = 0
        for group in ambiguous.values():
            bins: dict[tuple[str, ...], set[tuple[str, str]]] = defaultdict(set)
            bin_rows: Counter[tuple[str, ...]] = Counter()
            for row in group:
                key = tuple(row[name].strip() or "<blank>" for name in features)
                bins[key].add(_label(row))
                bin_rows[key] += 1
            if all(len(labels) == 1 for labels in bins.values()):
                resolved += 1
                rows_resolved += len(group)
            else:
                unresolved += 1
                rows_unresolved += len(group)
        return {
            "features": list(features),
            "ambiguous_surfaces_resolved": resolved,
            "ambiguous_surfaces_still_conflicted": unresolved,
            "rows_in_resolved_surfaces": rows_resolved,
            "rows_in_conflicted_surfaces": rows_unresolved,
        }

    examples = []
    for surface, group in sorted(
            ambiguous.items(), key=lambda item: (-len(item[1]), item[0])):
        labels = Counter(_label(row) for row in group)
        contexts: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for row in group:
            contexts[(row["context_state"], row["predecessor_act"])][_label(row)] += 1
        examples.append({
            "surface": surface,
            "occurrences": len(group),
            "conversation_count": len({row["conversation_id"] for row in group}),
            "labels": [
                {"dialogue_act": act, "task_intent": intent, "count": count}
                for (act, intent), count in sorted(labels.items())
            ],
            "context_buckets": [
                {"context_state": state, "predecessor_act": predecessor,
                 "labels": [
                     {"dialogue_act": act, "task_intent": intent, "count": count}
                     for (act, intent), count in sorted(counts.items())
                 ]}
                for (state, predecessor), counts in sorted(contexts.items())
            ],
            "citations": sorted({row["citation"] for row in group})[:8],
        })

    return {
        "diagnostic": "contextual-intent-identical-surface-ambiguity",
        "annotator": next(iter(annotators)),
        "accuracy_claimed": False,
        "summary": {
            "rows": len(rows),
            "conversation_count": len({row["conversation_id"] for row in rows}),
            "unique_normalized_surfaces": len(groups),
            "surfaces_repeated_across_conversations": len(repeated),
            "repeated_surfaces_with_multiple_act_intent_labels": len(ambiguous),
            "context_effect": [
                context_stats(("context_state",)),
                context_stats(("predecessor_act",)),
                context_stats(("context_state", "predecessor_act")),
            ],
        },
        "ambiguous_surface_examples": examples,
        "limitations": [
            "All labels come from one authorized Codex annotation pass.",
            "This measures contextual variation in the annotations, not label correctness.",
            "context_state and predecessor_act are coarse labels; question-under-discussion and open-slot state are not represented.",
            "The batch contains only Taskmaster restaurant-table conversations and cannot establish open-domain dialogue competence.",
        ],
    }


def _self_test() -> None:
    rows = [
        {"conversation_id": "a", "user_utterance": "YES!", "dialogue_act": "answer-clarification",
         "task_intent": "provide-constraint", "context_state": "awaiting-user-detail",
         "predecessor_act": "clarification-request", "reviewer": "codex-ai-test", "citation": "a#1"},
        {"conversation_id": "b", "user_utterance": "yes", "dialogue_act": "confirm",
         "task_intent": "continue-current-task", "context_state": "awaiting-confirmation",
         "predecessor_act": "other", "reviewer": "codex-ai-test", "citation": "b#1"},
        {"conversation_id": "c", "user_utterance": "Thank you", "dialogue_act": "thanks",
         "task_intent": "social-contact", "context_state": "social-exchange",
         "predecessor_act": "answer", "reviewer": "codex-ai-test", "citation": "c#1"},
    ]
    import tempfile
    with tempfile.TemporaryDirectory(prefix="crms-intent-ambiguity-") as folder:
        path = Path(folder) / "user.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        result = analyze(path)
    assert result["summary"]["unique_normalized_surfaces"] == 2
    assert result["summary"]["repeated_surfaces_with_multiple_act_intent_labels"] == 1
    assert result["summary"]["context_effect"][2][
        "ambiguous_surfaces_resolved"] == 1
    print("contextual intent ambiguity diagnostic self-test: PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_turns", nargs="?", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    if args.user_turns is None:
        parser.error("user_turns is required unless --self-test is used")
    result = analyze(args.user_turns)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
