"""Prepare Taskmaster-1 WOz conversations for human dialogue-move annotation.

This is a data-preparation tool, not an act or intent learner. It keeps each
complete conversation in one deterministic split, emits citation-bearing user
and assistant turn rows with preceding context, and never guesses labels.

Usage:
    python3 experiments/v1_363_prepare_taskmaster_dialogue_pilot.py \
        /path/to/woz-dialogs.json /path/to/new-output-directory
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
import re
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSResearchIndex


DATASET_README = (
    "https://github.com/google-research-datasets/Taskmaster/blob/master/"
    "TM-1-2019/README.md")
PAPER = "https://aclanthology.org/D19-1459/"
ASSISTANT_MOVE_CLASSES = (
    "greet", "acknowledge", "clarify-request", "repair", "close")


def _safe_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("each conversation needs a non-empty conversation_id")
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        raise ValueError(f"unsafe conversation_id: {value!r}")
    return value


def _split_for(conversation_id: str) -> str:
    bucket = int(hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "dev"
    return "test"


def _annotation_sample(dialogues: list[dict[str, Any]], limit: int,
                       domain_filter: str) -> set[tuple[str, str]]:
    """Choose conversation IDs deterministically within one dialogue domain."""
    if type(limit) is not int or limit < 1:
        raise ValueError("annotation_dialogues must be a positive integer")
    groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for dialogue in dialogues:
        domain = dialogue["instruction_id"].rsplit("-", 1)[0] or "unknown"
        if domain != domain_filter:
            continue
        groups[domain].setdefault(dialogue["conversation_id"], dialogue)
    available = sum(len(rows) for rows in groups.values())
    if not available:
        raise ValueError(f"no conversations found for annotation domain {domain_filter!r}")
    target = min(limit, available)
    exact = {domain: target * len(rows) / available
             for domain, rows in groups.items()}
    quotas = {domain: math.floor(value) for domain, value in exact.items()}
    remainder = target - sum(quotas.values())
    for domain in sorted(groups, key=lambda value: (
            -(exact[value] - quotas[value]), value))[:remainder]:
        quotas[domain] += 1
    chosen: set[tuple[str, str]] = set()
    for domain, rows in groups.items():
        ranked = sorted(rows, key=lambda conversation_id: (
            hashlib.sha256(f"{domain}\0{conversation_id}".encode("utf-8"))
            .hexdigest(), conversation_id))
        chosen.update((domain, conversation_id)
                      for conversation_id in ranked[:quotas[domain]])
    return chosen


def _double_label_sample(
        dialogues: list[dict[str, Any]],
        annotation_ids: set[tuple[str, str]],
        fraction: float = 0.20) -> tuple[set[tuple[str, str]], dict[str, int]]:
    """Choose whole conversations for independent review within each split."""
    grouped: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for dialogue in dialogues:
        domain = dialogue["instruction_id"].rsplit("-", 1)[0] or "unknown"
        key = (domain, dialogue["conversation_id"])
        if key in annotation_ids:
            grouped[_split_for(dialogue["conversation_id"])].add(key)
    selected: set[tuple[str, str]] = set()
    counts = {}
    for split, keys in grouped.items():
        ranked = sorted(keys, key=lambda key: (
            hashlib.sha256(
                f"dialogue-move-audit-v1\0{split}\0{key[0]}\0{key[1]}"
                .encode("utf-8")).hexdigest(), key))
        count = math.ceil(len(keys) * fraction)
        selected.update(ranked[:count])
        counts[split] = count
    for split in ("train", "dev", "test"):
        counts.setdefault(split, 0)
    return selected, counts


def _read_dialogues(payload: Any
                    ) -> tuple[list[dict[str, Any]], list[str], int, int, int]:
    if isinstance(payload, dict):
        payload = payload.get("dialogs", payload.get("dialogues", [payload]))
    if not isinstance(payload, list):
        raise ValueError("Taskmaster input must be a dialogue list")
    rows = []
    skipped_empty = []
    input_count = len(payload)
    unknown_speaker_turns = 0
    id_counts: dict[str, int] = {}
    for record_ordinal, dialogue in enumerate(payload):
        if not isinstance(dialogue, dict):
            raise ValueError("dialogue entries must be objects")
        conversation_id = _safe_id(dialogue.get("conversation_id"))
        id_counts[conversation_id] = id_counts.get(conversation_id, 0) + 1
        utterances = dialogue.get("utterances")
        if not isinstance(utterances, list):
            raise ValueError(f"dialogue {conversation_id} has malformed utterances")
        if not utterances:
            skipped_empty.append(conversation_id)
            continue
        normalized = []
        indices = set()
        for turn in utterances:
            if not isinstance(turn, dict):
                raise ValueError(f"dialogue {conversation_id} has a malformed turn")
            index = turn.get("index")
            speaker = turn.get("speaker")
            text = turn.get("text")
            if (type(index) is not int or index < 0 or index in indices
                    or speaker not in {"USER", "ASSISTANT", ""}
                    or not isinstance(text, str) or not text.strip()):
                raise ValueError(f"dialogue {conversation_id} has an invalid utterance")
            if speaker == "":
                speaker = "UNKNOWN"
                unknown_speaker_turns += 1
            indices.add(index)
            normalized.append({"index": index, "speaker": speaker, "text": text})
        normalized.sort(key=lambda row: row["index"])
        if [row["index"] for row in normalized] != list(range(len(normalized))):
            raise ValueError(f"dialogue {conversation_id} has non-contiguous turn indices")
        rows.append({"conversation_id": conversation_id,
                     "source_record_ordinal": record_ordinal,
                     "instruction_id": str(dialogue.get("instruction_id", "")),
                     "utterances": normalized})
    return (sorted(rows, key=lambda row: row["conversation_id"]),
            sorted(skipped_empty), input_count, unknown_speaker_turns,
            sum(count - 1 for count in id_counts.values() if count > 1))


def prepare(source_path: Path, output_path: Path, *,
            maximum_dialogues: int | None = None,
            annotation_dialogues: int = 500,
            annotation_domain: str = "restaurant-table") -> dict[str, Any]:
    source_path = source_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if output_path.exists():
        raise FileExistsError(f"output directory already exists: {output_path}")
    raw = source_path.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    (dialogues, skipped_empty, input_count, unknown_speaker_turns,
     duplicate_id_records) = _read_dialogues(json.loads(raw.decode("utf-8")))
    if maximum_dialogues is not None:
        if type(maximum_dialogues) is not int or maximum_dialogues < 1:
            raise ValueError("maximum_dialogues must be a positive integer")
        dialogues = dialogues[:maximum_dialogues]
    if not dialogues:
        raise ValueError("no dialogues selected")
    annotation_ids = _annotation_sample(
        dialogues, annotation_dialogues, annotation_domain)
    double_label_ids, double_label_dialogues_by_split = _double_label_sample(
        dialogues, annotation_ids)

    corpus_root = output_path / "corpus"
    annotations_path = output_path / "assistant_turns_to_label.csv"
    user_annotations_path = output_path / "user_turns_to_label.csv"
    output_path.mkdir(parents=True)
    corpus_root.mkdir()
    annotation_rows: list[dict[str, str]] = []
    user_annotation_rows: list[dict[str, str]] = []
    split_dialogues = {"train": 0, "dev": 0, "test": 0}
    annotation_splits = {"train": 0, "dev": 0, "test": 0}
    assistant_turns = 0
    annotation_assistant_turns = 0
    annotation_ids_written: set[tuple[str, str]] = set()
    for dialogue in dialogues:
        conversation_id = dialogue["conversation_id"]
        domain = dialogue["instruction_id"].rsplit("-", 1)[0] or "unknown"
        annotation_key = (domain, conversation_id)
        record_ordinal = dialogue["source_record_ordinal"]
        split = _split_for(conversation_id)
        split_dialogues[split] += 1
        record_id = f"{conversation_id}__record_{record_ordinal:05d}"
        relative = Path("dialogues") / f"{record_id}.txt"
        destination = corpus_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        pieces = []
        turn_spans = {}
        offset = 0
        for turn in dialogue["utterances"]:
            prefix = f"{turn['speaker']}: "
            line = prefix + turn["text"] + "\n"
            start = offset + len(prefix)
            end = start + len(turn["text"])
            turn_spans[turn["index"]] = (start, end)
            pieces.append(line)
            offset += len(line)
        transcript = "".join(pieces)
        destination.write_text(transcript, encoding="utf-8", newline="")
        digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        # add_directory() uses absolute file paths as document IDs; match the
        # normal CRMS citation format so this sheet can be used after indexing
        # the generated corpus directory.
        document_id = str(destination.resolve())
        if (annotation_key in annotation_ids
                and annotation_key not in annotation_ids_written):
            annotation_ids_written.add(annotation_key)
            annotation_splits[split] += 1
        for position, turn in enumerate(dialogue["utterances"]):
            if turn["speaker"] not in {"ASSISTANT", "USER"}:
                continue
            if turn["speaker"] == "ASSISTANT":
                assistant_turns += 1
            if annotation_key not in annotation_ids:
                continue
            prior = dialogue["utterances"][:position]
            context = "\n".join(
                f"{item['speaker']}: {item['text']}" for item in prior[-2:])
            start, end = turn_spans[turn["index"]]
            common = {
                "split": split,
                "conversation_id": conversation_id,
                "source_record_ordinal": str(record_ordinal),
                "instruction_id": dialogue["instruction_id"],
                "utterance_index": str(turn["index"]),
                "preceding_context": context,
                "double_label_required": str(annotation_key in double_label_ids).lower(),
                "citation": (f"{document_id}#sha256={digest}"
                             f"&chars={start}:{end}"),
                "source_file_sha256": source_sha256,
                "source_conversation_id": conversation_id,
                "source_utterance_index": str(turn["index"]),
            }
            if turn["speaker"] == "ASSISTANT":
                annotation_assistant_turns += 1
                annotation_rows.append(common | {
                    "assistant_utterance": turn["text"],
                    "move_label": "",
                    "context_license": "",
                    "predecessor_label": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "protocol_version": "",
                    "move_label_2": "",
                    "context_license_2": "",
                    "predecessor_label_2": "",
                    "reviewer_2": "",
                    "reviewed_at_2": "",
                    "protocol_version_2": "",
                    "adjudicated_label": "",
                    "adjudicator": "",
                    "adjudicated_at": "",
                    "annotator_note": "",
                })
            else:
                user_annotation_rows.append(common | {
                    "user_utterance": turn["text"],
                    "dialogue_act": "",
                    "task_intent": "",
                    "goal_intent": "",
                    "context_state": "",
                    "predecessor_act": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "protocol_version": "",
                    "dialogue_act_2": "",
                    "task_intent_2": "",
                    "goal_intent_2": "",
                    "context_state_2": "",
                    "predecessor_act_2": "",
                    "reviewer_2": "",
                    "reviewed_at_2": "",
                    "protocol_version_2": "",
                    "adjudicated_dialogue_act": "",
                    "adjudicated_task_intent": "",
                    "adjudicated_goal_intent": "",
                    "adjudicator": "",
                    "adjudicated_at": "",
                    "annotator_note": "",
                })

    if not annotation_rows or not user_annotation_rows:
        raise ValueError("selected annotation sample needs both user and assistant turns")
    for path, rows in ((annotations_path, annotation_rows),
                       (user_annotations_path, user_annotation_rows)):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    manifest = {
        "dataset": "Taskmaster-1, two-person Wizard-of-Oz dialogues",
        "dataset_readme": DATASET_README,
        "paper": PAPER,
        "license": "CC BY 4.0",
        "attribution": (
            "Bill Byrne, Karthik Krishnamoorthi, Chinnadhurai Sankar, Arvind "
            "Neelakantan, Amit Dubey, Kyu-Young Kim, and Andy Cedilnik, "
            "Taskmaster-1: Toward a Realistic and Diverse Dialog Dataset, 2019."),
        "source_file": str(source_path),
        "source_file_sha256": source_sha256,
        "conversation_split": "sha256(conversation_id) mod 100: train 80%, dev 10%, test 10%",
        "input_conversation_count": input_count,
        "conversation_count": len(dialogues),
        "duplicate_conversation_id_extra_records": duplicate_id_records,
        "skipped_empty_dialogue_count": len(skipped_empty),
        "skipped_empty_dialogue_ids": skipped_empty,
        "unknown_speaker_turn_count": unknown_speaker_turns,
        "assistant_turn_count": assistant_turns,
        "dialogues_by_split": split_dialogues,
        "annotation_dialogue_target": annotation_dialogues,
        "annotation_domain": annotation_domain,
        "annotation_dialogue_count": len(annotation_ids),
        "annotation_dialogues_with_assistant_turns": len(annotation_ids_written),
        "annotation_assistant_turn_count": annotation_assistant_turns,
        "annotation_dialogues_by_split": annotation_splits,
        "double_label_fraction": 0.20,
        "double_label_dialogues_by_split": double_label_dialogues_by_split,
        "double_label_dialogue_count": len(double_label_ids),
        "double_label_turn_count": sum(
            1 for row in annotation_rows if row["double_label_required"] == "true"),
        "annotation_file": annotations_path.name,
        "user_intent_annotation_file": user_annotations_path.name,
        "user_intent_turn_count": len(user_annotation_rows),
        "double_label_user_turn_count": sum(
            1 for row in user_annotation_rows
            if row["double_label_required"] == "true"),
        "corpus_directory": corpus_root.name,
        "move_classes_for_human_review": list(ASSISTANT_MOVE_CLASSES),
        "labels_assigned_automatically": False,
        "citation_note": (
            "Each annotation citation resolves to the assistant utterance in the "
            "normalized transcript. The row also preserves original file SHA-256, "
            "conversation ID, and utterance index."),
        "limitations": [
            "The dataset's published labels are transaction/API annotations, not dialogue acts.",
            "This pilot measures task-service conversations, not open-domain dialogue.",
            "Conversation IDs are distinct conversations within one corpus, not independent publishers.",
        ],
    }
    (output_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    attribution = (
        "# Taskmaster-1 dialogue pilot preparation\n\n"
        "This directory contains normalized transcripts derived from Taskmaster-1's "
        "two-person Wizard-of-Oz dialogue collection.\n\n"
        f"Dataset documentation: {DATASET_README}\n\n"
        f"Paper: {PAPER}\n\n"
        "License: CC BY 4.0. Attribution and the input file digest are recorded in "
        "manifest.json. User intent and assistant move labels are blank for human review.\n")
    (output_path / "README.md").write_text(attribution, encoding="utf-8")

    # Verify that every generated utterance citation resolves through CRMS's
    # normal source index API before presenting the annotation pack as usable.
    index = CRMSResearchIndex()
    index.add_directory(corpus_root)
    for row in annotation_rows + user_annotation_rows:
        resolved = index.resolve_citation(row["citation"])
        expected = row.get("assistant_utterance", row.get("user_utterance"))
        if resolved != expected:
            raise RuntimeError("generated annotation citation failed round-trip")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Taskmaster woz-dialogs.json")
    parser.add_argument("output", type=Path, help="new output directory")
    parser.add_argument("--max-dialogues", type=int,
                        help="small deterministic prefix for a format dry-run")
    parser.add_argument("--annotation-dialogues", type=int, default=500,
                        help="unique conversations sampled for human labels (default: 500)")
    parser.add_argument("--annotation-domain", default="restaurant-table",
                        help="single Taskmaster domain to label (default: restaurant-table)")
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.output,
                         maximum_dialogues=args.max_dialogues,
                         annotation_dialogues=args.annotation_dialogues,
                         annotation_domain=args.annotation_domain)
    except (FileExistsError, FileNotFoundError, OSError, UnicodeError,
            json.JSONDecodeError, RuntimeError, ValueError) as error:
        print(f"Could not prepare Taskmaster dialogue pilot: {error}", file=sys.stderr)
        return 2
    print(json.dumps({key: result[key] for key in (
        "dataset", "input_conversation_count", "conversation_count",
        "skipped_empty_dialogue_count", "duplicate_conversation_id_extra_records",
        "unknown_speaker_turn_count", "assistant_turn_count",
        "dialogues_by_split", "annotation_domain", "annotation_dialogue_count",
        "annotation_dialogues_with_assistant_turns",
        "annotation_assistant_turn_count", "annotation_dialogues_by_split",
        "double_label_fraction", "double_label_dialogues_by_split",
        "double_label_dialogue_count", "double_label_turn_count",
        "user_intent_turn_count", "double_label_user_turn_count",
        "labels_assigned_automatically")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
