"""Check whether an open question and active task clarify repeated user turns.

This diagnostic uses the authorized, single-Codex-label Taskmaster batch. It
derives a small, inspectable context signature from transcript text, then asks
whether that signature partitions repeated surfaces with differing act/intent
labels. It does not train a model, assess label correctness, or license runtime
frames.

Run with:
    python3 experiments/v1_390_contextual_intent_task_slot_diagnostic.py USER_TURNS.csv
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


def normalize_surface(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+(?:['’]\w+)*", value, re.UNICODE))


def transcript_messages(value: str) -> list[tuple[str, str]]:
    """Read the worksheet's USER:/ASSISTANT: context without inventing turns."""
    messages = []
    for line in value.splitlines():
        match = re.match(r"^(USER|ASSISTANT):\s*(.*)$", line.strip(), re.I)
        if match:
            messages.append((match.group(1).upper(), match.group(2).strip()))
    return messages


def expected_slot(question: str) -> str:
    """Map a previous assistant question to a conservative slot category."""
    text = question.casefold()
    if not text or "?" not in text:
        return "none-or-not-a-question"
    if any(cue in text for cue in (
            "correct?", "is that", "did you say", "to confirm", "do you confirm")):
        return "confirmation"
    if any(cue in text for cue in (
            "how many people", "how big is your party", "party size")):
        return "party-size"
    if any(cue in text for cue in (
            "what time", "which time", "when would", "what day", "which day")):
        return "date-or-time"
    if any(cue in text for cue in (
            "what city", "which city", "what location", "where should", "where would")):
        return "location"
    if any(cue in text for cue in (
            "indoor or outdoor", "outdoor or indoor", "seating preference")):
        return "seating"
    if any(cue in text for cue in (
            "would you like to book", "would you like to make", "do you want to book")):
        return "reservation-confirmation"
    return "other-question"


def active_task(messages: list[tuple[str, str]]) -> str:
    """Infer only a narrow task cue from the most recent relevant user turn."""
    reservation_cues = ("book", "booking", "reservation", "reserve")
    search_cues = ("find", "recommend", "suggest", "looking for", "places",
                   "restaurant")
    for speaker, text in reversed(messages):
        if speaker != "USER":
            continue
        lowered = text.casefold()
        if any(re.search(rf"\b{re.escape(cue)}\b", lowered)
               for cue in reservation_cues):
            return "make-reservation"
        if any(re.search(rf"\b{re.escape(cue)}\b", lowered)
               for cue in search_cues):
            return "find-restaurant"
    return "task-unspecified"


def context_signature(row: dict[str, str]) -> tuple[str, str]:
    messages = transcript_messages(row.get("preceding_context", ""))
    last_assistant = next((text for speaker, text in reversed(messages)
                           if speaker == "ASSISTANT"), "")
    return active_task(messages), expected_slot(last_assistant)


def analyze(path: Path) -> dict:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "conversation_id", "user_utterance", "dialogue_act", "task_intent",
            "context_state", "predecessor_act", "reviewer", "citation",
            "preceding_context",
        }
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input lacks columns: {', '.join(sorted(missing))}")
        rows = list(reader)

    annotators = {row["reviewer"].strip() for row in rows if row["reviewer"].strip()}
    if len(annotators) != 1 or not next(iter(annotators), "").startswith("codex-ai-"):
        raise ValueError("expected one explicitly identified Codex AI annotator")
    repeated: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        surface = normalize_surface(row["user_utterance"])
        if surface:
            repeated[surface].append(row)
    ambiguous = {
        surface: group for surface, group in repeated.items()
        if len({row["conversation_id"] for row in group}) >= 2
        and len({(row["dialogue_act"], row["task_intent"]) for row in group}) > 1
    }

    def partition_stats(features: str) -> dict:
        resolved = still_conflicted = row_resolved = row_conflicted = 0
        for group in ambiguous.values():
            buckets: dict[tuple[str, ...], set[tuple[str, str]]] = defaultdict(set)
            for row in group:
                if features == "coarse-context":
                    key = (row["context_state"].strip() or "<blank>",
                           row["predecessor_act"].strip() or "<blank>")
                else:
                    key = context_signature(row)
                buckets[key].add((row["dialogue_act"], row["task_intent"]))
            if all(len(labels) == 1 for labels in buckets.values()):
                resolved += 1
                row_resolved += len(group)
            else:
                still_conflicted += 1
                row_conflicted += len(group)
        return {
            "features": features,
            "ambiguous_surfaces_resolved": resolved,
            "ambiguous_surfaces_still_conflicted": still_conflicted,
            "rows_in_resolved_surfaces": row_resolved,
            "rows_in_conflicted_surfaces": row_conflicted,
        }

    examples = []
    for surface, group in sorted(ambiguous.items()):
        labels_by_context: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for row in group:
            signature = context_signature(row)
            labels_by_context[signature][
                (row["dialogue_act"], row["task_intent"])] += 1
        examples.append({
            "surface": surface,
            "occurrences": len(group),
            "contexts": [
                {"active_task": task, "expected_slot": slot,
                 "labels": [
                     {"dialogue_act": act, "task_intent": intent, "count": count}
                     for (act, intent), count in sorted(labels.items())
                 ]}
                for (task, slot), labels in sorted(labels_by_context.items())
            ],
        })

    return {
        "diagnostic": "task-and-open-slot-context-partition",
        "annotator": next(iter(annotators)),
        "accuracy_claimed": False,
        "summary": {
            "rows": len(rows),
            "conversation_count": len({row["conversation_id"] for row in rows}),
            "repeated_ambiguous_surfaces": len(ambiguous),
            "partition_comparison": [
                partition_stats("coarse-context"),
                partition_stats("active-task-plus-expected-slot"),
            ],
        },
        "ambiguous_surface_examples": examples,
        "feature_definitions": {
            "active_task": "narrow keyword cue from the most recent relevant user turn",
            "expected_slot": "explicit cue match on the immediately preceding assistant turn",
        },
        "limitations": [
            "The labels come from one authorized Codex annotation pass and are not gold correctness labels.",
            "The context cues are deliberately small lexical heuristics, not a trained intent model.",
            "Same-bucket label consistency is descriptive and can be inflated by annotation bias.",
            "The restaurant-table Taskmaster sample cannot establish open-domain conversational competence.",
            "Runtime state and routing are not changed by this diagnostic.",
        ],
    }


def _self_test() -> None:
    row = {
        "preceding_context": (
            "USER: I want to book a table.\n"
            "ASSISTANT: In what city would you like to find a restaurant?"),
    }
    assert context_signature(row) == ("make-reservation", "location")
    assert expected_slot("To confirm, is that 6:30pm tonight?") == "confirmation"
    print("task and open-slot context feature extraction: PASS")


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
