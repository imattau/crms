"""Evaluate contextual intent on a newly reserved Taskmaster-1 test slice.

This is a small, single-Codex-labeler transfer diagnostic, not task accuracy.
Conversation IDs were hash-ranked after excluding IDs in the existing local
Taskmaster/dialogue annotation CSVs. The selected IDs are fixed below so later
replays use the same conversations.

Usage:
    python3 experiments/v1_462_taskmaster_fresh_dialogue_intent_holdout.py \
        /path/to/woz-dialogs.json --json-out experiments/reports/v1_462.json
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSResearchIndex
from v1_436_transcript_context_intent_replay import evaluate

EXPECTED_SOURCE_SHA256 = "cd3bc4e968487315d412c044d30af2bf0a4b33c3ef8b74c589f1e1fa832bf72f"
RESERVED_IDS = (
    "dlg-55ba0118-df2b-4ad9-9f92-afd4df0c5a5d",
    "dlg-e41052fb-f4a4-4975-a198-3f668bd3f69e",
    "dlg-c9aff912-d0a5-48a3-b6d6-edb9f314bac8",
)

# Primary labels by (conversation_id, original utterance index):
# (dialogue_act, immediate task_intent). These are frozen single-Codex labels
# under docs/dialogue_move_annotation_protocol.md; no secondary labels exist.
LABELS = {
    (RESERVED_IDS[0], 1): ("request-action", "seek-information"),
    (RESERVED_IDS[0], 5): ("provide-information", "provide-constraint"),
    (RESERVED_IDS[0], 8): ("question", "seek-information"),
    (RESERVED_IDS[0], 9): ("answer-clarification", "resolve-ambiguity"),
    (RESERVED_IDS[0], 11): ("question", "seek-information"),
    (RESERVED_IDS[0], 13): ("confirm", "resolve-ambiguity"),
    (RESERVED_IDS[0], 15): ("request-action", "seek-information"),
    (RESERVED_IDS[0], 17): ("uncertain", "uncertain"),
    (RESERVED_IDS[0], 19): ("thanks", "social-contact"),
    (RESERVED_IDS[1], 1): ("request-action", "seek-information"),
    (RESERVED_IDS[1], 3): ("provide-information", "provide-constraint"),
    (RESERVED_IDS[1], 7): ("answer-clarification", "resolve-ambiguity"),
    (RESERVED_IDS[1], 8): ("question", "seek-information"),
    (RESERVED_IDS[1], 10): ("question", "seek-information"),
    (RESERVED_IDS[1], 12): ("uncertain", "uncertain"),
    (RESERVED_IDS[1], 13): ("request-action", "make-reservation"),
    (RESERVED_IDS[1], 15): ("provide-information", "provide-constraint"),
    (RESERVED_IDS[1], 16): ("provide-information", "provide-constraint"),
    (RESERVED_IDS[1], 19): ("provide-information", "provide-constraint"),
    (RESERVED_IDS[1], 21): ("reject", "end-interaction"),
    (RESERVED_IDS[2], 1): ("request-action", "make-reservation"),
    (RESERVED_IDS[2], 3): ("provide-information", "provide-constraint"),
    (RESERVED_IDS[2], 5): ("uncertain", "uncertain"),
    (RESERVED_IDS[2], 7): ("provide-information", "provide-constraint"),
    (RESERVED_IDS[2], 9): ("provide-information", "provide-constraint"),
    (RESERVED_IDS[2], 11): ("acknowledgement", "end-interaction"),
    (RESERVED_IDS[2], 13): ("farewell", "end-interaction"),
}


def _split(conversation_id: str) -> str:
    bucket = int(hashlib.sha256(conversation_id.encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 80 else "dev" if bucket < 90 else "test"


def _git_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()


def _prior_annotation_inventory() -> tuple[set[str], list[str], str]:
    patterns = (
        "/tmp/crms_taskmaster*/*.csv",
        "/tmp/crms_dialogue*/*.csv",
        "/tmp/crms_dialogue_feasibility*/*.csv",
    )
    paths = sorted({Path(path) for pattern in patterns for path in glob.glob(pattern)})
    ids = set()
    for path in paths:
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    conversation_id = row.get("conversation_id", "").strip()
                    if conversation_id:
                        ids.add(conversation_id)
        except (OSError, UnicodeError, csv.Error) as error:
            raise ValueError(f"could not inspect prior annotation CSV {path}") from error
    digest = hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()
    return ids, [str(path.relative_to("/tmp")) for path in paths], digest


def run(source_path: Path) -> dict[str, Any]:
    prior_ids, prior_files, prior_ids_digest = _prior_annotation_inventory()
    if any(conversation_id in prior_ids for conversation_id in RESERVED_IDS):
        raise ValueError("a reserved conversation now overlaps a local annotation CSV")
    raw = source_path.read_bytes()
    source_digest = hashlib.sha256(raw).hexdigest()
    if source_digest != EXPECTED_SOURCE_SHA256:
        raise ValueError("Taskmaster source digest differs from the reserved dataset")
    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("dialogs", payload.get("dialogues", []))
    if not isinstance(payload, list):
        raise ValueError("Taskmaster source must contain a dialogue list")

    unique_records = {}
    for record in payload:
        conversation_id = record.get("conversation_id")
        if conversation_id:
            unique_records.setdefault(conversation_id, record)
    eligible = [
        conversation_id for conversation_id, record in unique_records.items()
        if str(record.get("instruction_id", "")).rsplit("-", 1)[0] == "restaurant-table"
        and _split(conversation_id) == "test"
        and conversation_id not in prior_ids
    ]
    ranked_eligible = sorted(
        eligible,
        key=lambda conversation_id: (
            hashlib.sha256(f"fresh-reserve-v1\0{conversation_id}".encode()).hexdigest(),
            conversation_id,
        ),
    )
    if tuple(ranked_eligible[:len(RESERVED_IDS)]) != RESERVED_IDS:
        raise ValueError("reserved IDs do not match the current deterministic selection")

    selected = {}
    for record in payload:
        conversation_id = record.get("conversation_id")
        if conversation_id in RESERVED_IDS:
            if conversation_id in selected:
                raise ValueError(f"duplicate reserved conversation {conversation_id}")
            selected[conversation_id] = record
    if set(selected) != set(RESERVED_IDS):
        raise ValueError("one or more reserved conversation IDs are missing")
    for conversation_id, record in selected.items():
        if _split(conversation_id) != "test":
            raise ValueError(f"reserved conversation is not in test split: {conversation_id}")
        if not str(record.get("instruction_id", "")).startswith("restaurant-table-"):
            raise ValueError(f"reserved conversation is outside restaurant-table: {conversation_id}")

    with tempfile.TemporaryDirectory(prefix="crms-v1-462-") as temp:
        corpus = Path(temp) / "corpus"
        corpus.mkdir()
        annotation_rows = []
        conversation_stats = []
        for conversation_id in RESERVED_IDS:
            record = selected[conversation_id]
            turns = sorted(record["utterances"], key=lambda turn: turn["index"])
            transcript_parts = []
            spans = {}
            offset = 0
            for turn in turns:
                speaker = turn["speaker"] or "UNKNOWN"
                prefix = f"{speaker}: "
                text = turn["text"]
                line = prefix + text + "\n"
                spans[turn["index"]] = (offset + len(prefix), offset + len(prefix) + len(text))
                transcript_parts.append(line)
                offset += len(line)
            transcript = "".join(transcript_parts)
            filename = f"{conversation_id}.txt"
            transcript_path = corpus / filename
            transcript_path.write_text(transcript, encoding="utf-8", newline="")
            transcript_digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
            conversation_stats.append({
                "conversation_id": conversation_id,
                "instruction_id": record["instruction_id"],
                "split": _split(conversation_id),
                "turn_count": len(turns),
                "user_turn_count": sum(t["speaker"] == "USER" for t in turns),
                "normalized_transcript_sha256": transcript_digest,
            })
            for position, turn in enumerate(turns):
                if turn["speaker"] != "USER":
                    continue
                key = (conversation_id, turn["index"])
                if key not in LABELS:
                    raise ValueError(f"missing frozen annotation for {key}")
                act, intent = LABELS[key]
                start, end = spans[turn["index"]]
                preceding_context = "\n".join(
                    f"{item['speaker'] or 'UNKNOWN'}: {item['text']}"
                    for item in turns[max(0, position - 2):position]
                )
                annotation_rows.append({
                    "conversation_id": conversation_id,
                    "utterance_index": str(turn["index"]),
                    "preceding_context": preceding_context,
                    "user_utterance": turn["text"],
                    "codex_dialogue_act": act,
                    "codex_task_intent": intent,
                    "codex_context_state": "",
                    "citation": (
                        f"{transcript_path.resolve()}#sha256={transcript_digest}"
                        f"&chars={start}:{end}"
                    ),
                })

        if set(LABELS) != {
                (row["conversation_id"], int(row["utterance_index"]))
                for row in annotation_rows}:
            raise ValueError("frozen labels do not exactly match reserved user turns")
        index = CRMSResearchIndex()
        index.add_directory(corpus)
        for row in annotation_rows:
            resolved = index.resolve_citation(row["citation"])
            if resolved != row["user_utterance"]:
                raise ValueError("citation did not resolve to the labeled utterance")
        # The public evaluator consumes CSVs. Keep its data temporary so the
        # released report contains metrics and a compact disagreement record.
        csv_path = Path(temp) / "reserved.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(annotation_rows[0]))
            writer.writeheader()
            writer.writerows(annotation_rows)
        metrics = evaluate(csv_path)
        metrics["limitations"] = [
            "Three conversations from one transactional domain are not representative of open-domain dialogue.",
            "The evaluator measures intent-label agreement, not answer correctness or task completion.",
            "The labels are single-Codex annotations and are not independent ground truth.",
            "Context is limited to the preceding two transcript turns and CRMS's own prior predictions.",
        ]

    return {
        "experiment": "v1_462_taskmaster_fresh_dialogue_intent_holdout",
        "code_revision": _git_revision(),
        "dataset": "Taskmaster-1, two-person Wizard-of-Oz dialogues",
        "dataset_license": "CC BY 4.0",
        "attribution": (
            "Bill Byrne, Karthik Krishnamoorthi, Chinnadhurai Sankar, Arvind "
            "Neelakantan, Amit Dubey, Kyu-Young Kim, and Andy Cedilnik, "
            "Taskmaster-1: Toward a Realistic and Diverse Dialog Dataset, 2019."
        ),
        "source_sha256": source_digest,
        "sampling": (
            "Three restaurant-table conversations from the deterministic Taskmaster test split; "
            "IDs were hash-ranked after excluding IDs in the prepared and previously labeled "
            "local Taskmaster/dialogue CSVs. IDs were frozen before this replay."
        ),
        "selection_audit": {
            "eligible_unseen_restaurant_test_conversations": len(ranked_eligible),
            "prior_annotation_csv_count": len(prior_files),
            "prior_annotation_csv_basenames": prior_files,
            "prior_csv_conversation_id_count": len(prior_ids),
            "prior_csv_conversation_ids_sha256": prior_ids_digest,
            "selected_ids_ranked_first": True,
        },
        "annotation_provenance": (
            "Single Codex primary labels by the protocol; no independent human review or "
            "second labeler. Agreement is not accuracy."
        ),
        "label_count": len(annotation_rows),
        "citation_validation": {"verified": len(annotation_rows), "total": len(annotation_rows)},
        "conversations": conversation_stats,
        "metrics": metrics,
        "limitations": [
            "Three conversations from one transactional domain are not representative of open-domain dialogue.",
            "The evaluator measures intent-label agreement, not answer correctness or task completion.",
            "The labels are single-Codex annotations and are not independent ground truth.",
            "Sampling excluded IDs found in local annotation CSVs; the report records inventory filenames and a digest of their combined ID set.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = run(args.source)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
