"""Prepare Taskmaster-1 WOz conversations for human dialogue-move annotation.

This is a data-preparation tool, not a move learner. It keeps each complete
conversation in one deterministic split, emits citation-bearing assistant-turn
rows with preceding context, and never guesses dialogue-act labels.

Usage:
    python3 experiments/v1_363_prepare_taskmaster_dialogue_pilot.py \
        /path/to/woz-dialogs.json /path/to/new-output-directory
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
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


def _read_dialogues(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("dialogs", payload.get("dialogues", [payload]))
    if not isinstance(payload, list):
        raise ValueError("Taskmaster input must be a dialogue list")
    rows = []
    seen = set()
    for dialogue in payload:
        if not isinstance(dialogue, dict):
            raise ValueError("dialogue entries must be objects")
        conversation_id = _safe_id(dialogue.get("conversation_id"))
        if conversation_id in seen:
            raise ValueError(f"duplicate conversation_id: {conversation_id}")
        seen.add(conversation_id)
        utterances = dialogue.get("utterances")
        if not isinstance(utterances, list) or not utterances:
            raise ValueError(f"dialogue {conversation_id} has no utterances")
        normalized = []
        indices = set()
        for turn in utterances:
            if not isinstance(turn, dict):
                raise ValueError(f"dialogue {conversation_id} has a malformed turn")
            index = turn.get("index")
            speaker = turn.get("speaker")
            text = turn.get("text")
            if (type(index) is not int or index < 0 or index in indices
                    or speaker not in {"USER", "ASSISTANT"}
                    or not isinstance(text, str) or not text.strip()):
                raise ValueError(f"dialogue {conversation_id} has an invalid utterance")
            indices.add(index)
            normalized.append({"index": index, "speaker": speaker, "text": text})
        normalized.sort(key=lambda row: row["index"])
        if [row["index"] for row in normalized] != list(range(len(normalized))):
            raise ValueError(f"dialogue {conversation_id} has non-contiguous turn indices")
        rows.append({"conversation_id": conversation_id,
                     "instruction_id": str(dialogue.get("instruction_id", "")),
                     "utterances": normalized})
    return sorted(rows, key=lambda row: row["conversation_id"])


def prepare(source_path: Path, output_path: Path, *,
            maximum_dialogues: int | None = None) -> dict[str, Any]:
    source_path = source_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if output_path.exists():
        raise FileExistsError(f"output directory already exists: {output_path}")
    raw = source_path.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    dialogues = _read_dialogues(json.loads(raw.decode("utf-8")))
    if maximum_dialogues is not None:
        if type(maximum_dialogues) is not int or maximum_dialogues < 1:
            raise ValueError("maximum_dialogues must be a positive integer")
        dialogues = dialogues[:maximum_dialogues]
    if not dialogues:
        raise ValueError("no dialogues selected")

    corpus_root = output_path / "corpus"
    annotations_path = output_path / "assistant_turns_to_label.csv"
    output_path.mkdir(parents=True)
    corpus_root.mkdir()
    annotation_rows: list[dict[str, str]] = []
    split_dialogues = {"train": 0, "dev": 0, "test": 0}
    assistant_turns = 0
    for dialogue in dialogues:
        conversation_id = dialogue["conversation_id"]
        split = _split_for(conversation_id)
        split_dialogues[split] += 1
        relative = Path("dialogues") / f"{conversation_id}.txt"
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
        for position, turn in enumerate(dialogue["utterances"]):
            if turn["speaker"] != "ASSISTANT":
                continue
            assistant_turns += 1
            prior = dialogue["utterances"][:position]
            context = "\n".join(
                f"{item['speaker']}: {item['text']}" for item in prior[-2:])
            start, end = turn_spans[turn["index"]]
            annotation_rows.append({
                "split": split,
                "conversation_id": conversation_id,
                "instruction_id": dialogue["instruction_id"],
                "utterance_index": str(turn["index"]),
                "preceding_context": context,
                "assistant_utterance": turn["text"],
                "move_label": "",
                "context_license": "",
                "predecessor_label": "",
                "reviewer": "",
                "citation": (f"{document_id}#sha256={digest}"
                             f"&chars={start}:{end}"),
                "source_file_sha256": source_sha256,
                "source_conversation_id": conversation_id,
                "source_utterance_index": str(turn["index"]),
            })

    fieldnames = list(annotation_rows[0])
    with annotations_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(annotation_rows)

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
        "conversation_count": len(dialogues),
        "assistant_turn_count": assistant_turns,
        "dialogues_by_split": split_dialogues,
        "annotation_file": annotations_path.name,
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
        "manifest.json. The annotation sheet contains no machine-assigned move labels.\n")
    (output_path / "README.md").write_text(attribution, encoding="utf-8")

    # Verify that every generated utterance citation resolves through CRMS's
    # normal source index API before presenting the annotation pack as usable.
    index = CRMSResearchIndex()
    index.add_directory(corpus_root)
    for row in annotation_rows:
        resolved = index.resolve_citation(row["citation"])
        if resolved != row["assistant_utterance"]:
            raise RuntimeError("generated annotation citation failed round-trip")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Taskmaster woz-dialogs.json")
    parser.add_argument("output", type=Path, help="new output directory")
    parser.add_argument("--max-dialogues", type=int,
                        help="small deterministic prefix for a format dry-run")
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.output,
                         maximum_dialogues=args.max_dialogues)
    except (FileExistsError, FileNotFoundError, OSError, UnicodeError,
            json.JSONDecodeError, RuntimeError, ValueError) as error:
        print(f"Could not prepare Taskmaster dialogue pilot: {error}", file=sys.stderr)
        return 2
    print(json.dumps({key: result[key] for key in (
        "dataset", "conversation_count", "assistant_turn_count",
        "dialogues_by_split", "labels_assigned_automatically")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
