"""Report annotation coverage and inter-rater agreement for the dialogue pilot."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
import sys
from typing import Any


SCHEMAS = {
    "assistant_moves": (
        ("move_label", "move_label_2", "adjudicated_label"),
        ("predecessor_label", "predecessor_label_2", None),
    ),
    "user_intents": (
        ("dialogue_act", "dialogue_act_2", "adjudicated_dialogue_act"),
        ("task_intent", "task_intent_2", "adjudicated_task_intent"),
        ("context_state", "context_state_2", None),
        ("predecessor_act", "predecessor_act_2", None),
    ),
}
ALLOWED_LABELS = {
    "move_label": {"greet", "acknowledge", "clarify-request", "repair",
                    "confirm", "close", "other-task", "other-social", "uncertain"},
    "predecessor_label": {"user-question", "user-answer", "user-correction",
                           "user-greeting", "assistant-question", "assistant-answer",
                           "assistant-other", "conversation-start", "uncertain"},
    "dialogue_act": {"question", "request-action", "provide-information",
                     "answer-clarification", "confirm", "reject", "correction",
                     "continuation-request", "greeting", "thanks", "farewell",
                     "other", "uncertain"},
    "task_intent": {"check-availability", "make-reservation", "change-reservation",
                    "cancel-reservation", "provide-constraint", "resolve-ambiguity",
                    "correct-prior-result", "seek-information", "continue-current-task",
                    "social-contact", "end-interaction", "other-task", "uncertain"},
    "context_state": {"opening", "awaiting-user-detail", "awaiting-confirmation",
                      "answer-follow-up", "correction-or-challenge", "task-in-progress",
                      "task-complete", "social-exchange", "no-open-task", "uncertain"},
    "predecessor_act": {"question", "clarification-request", "answer",
                        "confirmation-request", "greeting", "action-result", "close",
                        "other", "uncertain"},
}


def _read_csv(path: Path, expected_fields: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"annotation file has no header: {path}")
        missing = sorted(set(expected_fields) - set(reader.fieldnames))
        if missing:
            raise ValueError(f"{path} lacks required columns: {', '.join(missing)}")
        return list(reader)


def _check_partition_integrity(rows: list[dict[str, str]], name: str) -> None:
    partitions: dict[str, set[str]] = {}
    seen_rows = set()
    for row in rows:
        conversation_id = row["conversation_id"]
        split = row["split"]
        partitions.setdefault(conversation_id, set()).add(split)
        identity = (conversation_id, row["source_record_ordinal"],
                    row["utterance_index"])
        if identity in seen_rows:
            raise ValueError(f"{name} repeats annotation row {identity!r}")
        seen_rows.add(identity)
        if row["double_label_required"] not in {"true", "false"}:
            raise ValueError(f"{name} has an invalid double-label flag")
        if (row["double_label_required"] != "true"
                and any(row[field].strip() for field in
                        ("reviewer_2",) + tuple(
                            field for field in row
                            if field.endswith("_2") and field != "reviewer_2"))):
            raise ValueError(f"{name} has a second-rater label outside the audit sample")
        if (row["double_label_required"] != "true"
                and any(value.strip() for field, value in row.items()
                        if field.startswith("adjudicated_"))):
            raise ValueError(f"{name} has an adjudicated label outside the audit sample")
    split_leaks = sorted(key for key, values in partitions.items() if len(values) != 1)
    if split_leaks:
        raise ValueError(f"{name} has conversations across splits: {split_leaks[:5]}")


def _check_annotation_provenance(
        rows: list[dict[str, str]], primary_fields: set[str], name: str) -> None:
    adjudicated_fields = {
        "move_label": "adjudicated_label",
        "dialogue_act": "adjudicated_dialogue_act",
        "task_intent": "adjudicated_task_intent",
    }
    for row_number, row in enumerate(rows, 2):
        if any(row[field].strip() for field in primary_fields):
            if not all(row[field].strip() for field in
                       ("reviewer", "reviewed_at", "protocol_version")):
                raise ValueError(
                    f"{name} row {row_number} lacks primary-label provenance")
        second_fields = {field + "_2" for field in primary_fields}
        if any(row[field].strip() for field in second_fields):
            if not all(row[field].strip() for field in
                       ("reviewer_2", "reviewed_at_2", "protocol_version_2")):
                raise ValueError(
                    f"{name} row {row_number} lacks second-rater provenance")
        for primary, adjudicated in adjudicated_fields.items():
            if (primary in primary_fields and row[adjudicated].strip()
                    and not all(row[field].strip() for field in
                                ("adjudicator", "adjudicated_at"))):
                raise ValueError(
                    f"{name} row {row_number} lacks adjudication provenance")


def _check_labels(rows: list[dict[str, str]], fields: set[str], name: str) -> None:
    for row_number, row in enumerate(rows, 2):
        for base in fields:
            adjudicated_field = {
                "move_label": "adjudicated_label",
                "dialogue_act": "adjudicated_dialogue_act",
                "task_intent": "adjudicated_task_intent",
            }.get(base)
            candidate_fields = [base, base + "_2"]
            if adjudicated_field:
                candidate_fields.append(adjudicated_field)
            for field in candidate_fields:
                value = row.get(field, "").strip()
                if value and value not in ALLOWED_LABELS[base]:
                    raise ValueError(
                        f"{name} row {row_number} has unsupported "
                        f"{field} label {value!r}")


def _agreement(rows: list[dict[str, str]], first: str, second: str,
               adjudicated: str | None) -> dict[str, Any]:
    audit_rows = [row for row in rows if row["double_label_required"] == "true"]
    pairs = [(row[first].strip(), row[second].strip()) for row in audit_rows
             if row[first].strip() and row[second].strip()]
    first_labels = [row[first].strip() for row in rows if row[first].strip()]
    confusion: Counter[tuple[str, str]] = Counter(pairs)
    disagreements = sum(left != right for left, right in pairs)
    adjudicated_disagreements = (
        sum(bool(row[first].strip() and row[second].strip()
                 and row[first].strip() != row[second].strip()
                 and row[adjudicated].strip()) for row in audit_rows)
        if adjudicated else None)
    if pairs:
        observed = sum(left == right for left, right in pairs) / len(pairs)
        left_counts = Counter(left for left, _ in pairs)
        right_counts = Counter(right for _, right in pairs)
        expected = sum(left_counts[label] * right_counts[label]
                       for label in left_counts.keys() | right_counts.keys()) / (len(pairs) ** 2)
        kappa = ((observed - expected) / (1 - expected)
                 if expected < 1 else None)
    else:
        observed = None
        kappa = None
    adjudicated_count = (sum(bool(row[adjudicated].strip()) for row in audit_rows)
                         if adjudicated else None)
    return {
        "primary_field": first,
        "primary_labeled_rows": len(first_labels),
        "rows_total": len(rows),
        "audit_rows_required": len(audit_rows),
        "complete_independent_pairs": len(pairs),
        "audit_pair_coverage": len(pairs) / len(audit_rows) if audit_rows else None,
        "raw_agreement": observed,
        "cohen_kappa": kappa,
        "disagreements": disagreements,
        "adjudicated_disagreements": adjudicated_disagreements,
        "unadjudicated_disagreements": (
            disagreements - adjudicated_disagreements
            if adjudicated_disagreements is not None else None),
        "primary_label_counts": dict(sorted(Counter(first_labels).items())),
        "confusion_counts": {
            f"{left} | {right}": count
            for (left, right), count in sorted(confusion.items())
        },
        "adjudicated_rows": adjudicated_count,
    }


def evaluate(user_path: Path, assistant_path: Path) -> dict[str, Any]:
    user_fields = (
        "conversation_id", "source_record_ordinal", "utterance_index", "split",
        "double_label_required", "reviewer_2", "dialogue_act", "dialogue_act_2",
        "adjudicated_dialogue_act", "task_intent", "task_intent_2",
        "adjudicated_task_intent", "context_state", "context_state_2",
        "predecessor_act", "predecessor_act_2", "reviewer", "reviewed_at",
        "protocol_version", "reviewed_at_2", "protocol_version_2",
        "adjudicator", "adjudicated_at",
    )
    assistant_fields = (
        "conversation_id", "source_record_ordinal", "utterance_index", "split",
        "double_label_required", "reviewer_2", "move_label", "move_label_2",
        "adjudicated_label", "predecessor_label", "predecessor_label_2",
        "reviewer", "reviewed_at", "protocol_version", "reviewed_at_2",
        "protocol_version_2", "adjudicator", "adjudicated_at",
    )
    user_rows = _read_csv(user_path, user_fields)
    assistant_rows = _read_csv(assistant_path, assistant_fields)
    _check_partition_integrity(user_rows, "user-intent sheet")
    _check_partition_integrity(assistant_rows, "assistant-move sheet")
    _check_labels(user_rows, {"dialogue_act", "task_intent", "context_state",
                              "predecessor_act"}, "user-intent sheet")
    _check_labels(assistant_rows, {"move_label", "predecessor_label"},
                  "assistant-move sheet")
    _check_annotation_provenance(
        user_rows, {"dialogue_act", "task_intent", "context_state", "predecessor_act"},
        "user-intent sheet")
    _check_annotation_provenance(
        assistant_rows, {"move_label", "predecessor_label"}, "assistant-move sheet")

    label_metrics = {}
    for label_set, rows, schemas in (
            ("user_intents", user_rows, SCHEMAS["user_intents"]),
            ("assistant_moves", assistant_rows, SCHEMAS["assistant_moves"])):
        label_metrics[label_set] = [
            _agreement(rows, first, second, adjudicated)
            for first, second, adjudicated in schemas
        ]
    all_primary = sum(metric["primary_labeled_rows"]
                      for metrics in label_metrics.values() for metric in metrics)
    all_rows = len(user_rows) + len(assistant_rows)
    all_primary_complete = all(
        metric["primary_labeled_rows"] == metric["rows_total"]
        for metrics in label_metrics.values() for metric in metrics)
    all_audit_pairs_complete = all(
        metric["audit_rows_required"] == metric["complete_independent_pairs"]
        for metrics in label_metrics.values() for metric in metrics)
    all_disagreements_adjudicated = all(
        metric["unadjudicated_disagreements"] in (0, None)
        for metrics in label_metrics.values() for metric in metrics)
    status = "awaiting_annotations" if all_primary == 0 else (
        "complete" if (all_primary_complete and all_audit_pairs_complete
                       and all_disagreements_adjudicated) else "incomplete")
    return {
        "status": status,
        "user_turn_rows": len(user_rows),
        "assistant_turn_rows": len(assistant_rows),
        "total_turn_rows": all_rows,
        "labels_assigned_by_tool": False,
        "metrics": label_metrics,
    }


def _self_test() -> None:
    def synthetic_row(index: int, left: str, right: str) -> dict[str, str]:
        return {
            "conversation_id": f"c{index}",
            "source_record_ordinal": str(index),
            "utterance_index": "0",
            "split": "train",
            "double_label_required": "true",
            "reviewer_2": "rater-b",
            "label": left,
            "label_2": right,
            "adjudicated": "",
        }
    rows = [synthetic_row(1, "greet", "greet"),
            synthetic_row(2, "acknowledge", "greet"),
            synthetic_row(3, "close", "close"),
            synthetic_row(4, "greet", "greet")]
    result = _agreement(rows, "label", "label_2", "adjudicated")
    if result["raw_agreement"] != 0.75 or result["complete_independent_pairs"] != 4:
        raise AssertionError(f"agreement calculation failed: {result}")
    if abs(result["cohen_kappa"] - (5 / 9)) > 1e-9:
        raise AssertionError(f"Cohen's kappa calculation failed: {result}")
    _check_partition_integrity(rows, "synthetic sheet")
    rows.append({**rows[0], "source_record_ordinal": "99",
                 "utterance_index": "1", "split": "dev"})
    try:
        _check_partition_integrity(rows, "synthetic sheet")
    except ValueError:
        pass
    else:
        raise AssertionError("split leakage was not detected")
    bad_provenance = {
        "move_label": "greet", "move_label_2": "", "reviewer": "",
        "reviewed_at": "", "protocol_version": "", "reviewer_2": "",
        "reviewed_at_2": "", "protocol_version_2": "",
        "adjudicated_label": "", "adjudicator": "", "adjudicated_at": "",
    }
    try:
        _check_annotation_provenance(
            [bad_provenance], {"move_label"}, "synthetic sheet")
    except ValueError:
        pass
    else:
        raise AssertionError("missing label provenance was not detected")
    print("agreement formula, split-leakage, and provenance checks: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_sheet", nargs="?", type=Path)
    parser.add_argument("assistant_sheet", nargs="?", type=Path)
    parser.add_argument("--strict", action="store_true",
                        help="exit nonzero until every audit row has two labels")
    parser.add_argument("--self-test", action="store_true",
                        help="check agreement math and split-leak detection")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if args.user_sheet is None or args.assistant_sheet is None:
        parser.error("provide user and assistant annotation CSV paths")
    try:
        result = evaluate(args.user_sheet, args.assistant_sheet)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        print(f"Could not evaluate dialogue annotations: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and result["status"] != "complete":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
