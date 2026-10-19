"""Create a small, conversation-held-out human annotation feasibility batch.

The sampler selects whole conversations from the existing train split, copies
their cited transcripts, and marks a deterministic whole-conversation subset
for independent double labeling. It never supplies or changes labels.

Usage:
    python3 experiments/v1_382_dialogue_feasibility_batch.py \
        USER_CSV ASSISTANT_CSV CORPUS_ROOT OUTPUT_DIR
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil


SEED = "crms-dialogue-feasibility-v1"
USER_FIELDS = {
    "split", "conversation_id", "citation", "user_utterance",
    "dialogue_act", "task_intent", "context_state", "predecessor_act",
    "double_label_required",
}
ASSISTANT_FIELDS = {
    "split", "conversation_id", "citation", "assistant_utterance",
    "move_label", "context_license", "predecessor_label",
    "double_label_required",
}


def _key(conversation_id: str) -> str:
    return hashlib.sha256(f"{SEED}\0{conversation_id}".encode()).hexdigest()


def _read(path: Path, required: set[str]) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = required - set(fields)
        if missing:
            raise ValueError(f"{path} lacks columns: {', '.join(sorted(missing))}")
        return fields, list(reader)


def _validate_all_annotations_blank(rows: list[dict[str, str]],
                                    path: Path) -> None:
    annotation_fields = {
        name for row in rows for name in row
        if name in {"reviewer", "reviewer_2", "reviewed_at", "reviewed_at_2",
                    "protocol_version", "protocol_version_2", "adjudicator",
                    "adjudicated_at", "annotator_note"}
        or name.endswith("_2") or name.startswith("adjudicated_")
        or name in {"dialogue_act", "task_intent", "context_state",
                    "predecessor_act", "move_label", "context_license",
                    "predecessor_label"}
    }
    for row_number, row in enumerate(rows, 2):
        for field in annotation_fields:
            if row.get(field, "").strip():
                raise ValueError(
                    f"{path}:{row_number} already has annotation in {field}; "
                    "refusing to resample or overwrite annotated data")


def _source_path(citation: str) -> Path:
    if "#sha256=" not in citation or "&chars=" not in citation:
        raise ValueError(f"malformed transcript citation: {citation!r}")
    return Path(citation.split("#sha256=", 1)[0]).resolve()


def _copy_cited_sources(rows: list[dict[str, str]], corpus_root: Path,
                        output: Path) -> int:
    copied: set[Path] = set()
    copied_count = 0
    for row in rows:
        source = _source_path(row["citation"])
        try:
            relative = source.relative_to(corpus_root)
        except ValueError as error:
            raise ValueError(
                f"citation is outside the supplied corpus root: {source}") from error
        target = output / "corpus" / relative
        if source not in copied:
            if not source.is_file():
                raise FileNotFoundError(f"cited transcript is missing: {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.add(source)
            copied_count += 1
        row["citation"] = str(target.resolve()) + row["citation"][
            row["citation"].index("#sha256="):]
    return copied_count


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def create_batch(user_path: Path, assistant_path: Path, corpus_root: Path,
                 output: Path, *, conversations: int = 40,
                 double_label_fraction: float = 0.2) -> dict:
    if type(conversations) is not int or conversations < 2:
        raise ValueError("conversations must be an integer of at least 2")
    if (not isinstance(double_label_fraction, (int, float))
            or isinstance(double_label_fraction, bool)
            or not 0.0 < double_label_fraction < 1.0):
        raise ValueError("double_label_fraction must be between 0 and 1")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    corpus_root = corpus_root.resolve()
    user_fields, user_rows = _read(user_path, USER_FIELDS)
    assistant_fields, assistant_rows = _read(assistant_path, ASSISTANT_FIELDS)
    _validate_all_annotations_blank(user_rows, user_path)
    _validate_all_annotations_blank(assistant_rows, assistant_path)

    all_rows = user_rows + assistant_rows
    for row in all_rows:
        if row.get("split") not in {"train", "dev", "test"}:
            raise ValueError("annotation row has an unsupported split")
        if not row.get("conversation_id", "").strip():
            raise ValueError("annotation row lacks conversation_id")
    train_ids = sorted({row["conversation_id"] for row in all_rows
                        if row["split"] == "train"}, key=lambda value: (_key(value), value))
    if len(train_ids) < conversations:
        raise ValueError(
            f"requested {conversations} train conversations, only {len(train_ids)} exist")
    chosen = set(train_ids[:conversations])
    audit_count = max(1, math.ceil(conversations * double_label_fraction))
    audit_ids = set(sorted(chosen, key=lambda value: (_key("audit\0" + value), value))[
                     :audit_count])

    selected_user = [dict(row) for row in user_rows
                     if row["split"] == "train" and row["conversation_id"] in chosen]
    selected_assistant = [dict(row) for row in assistant_rows
                          if row["split"] == "train" and row["conversation_id"] in chosen]
    if ({row["conversation_id"] for row in selected_user} != chosen
            or {row["conversation_id"] for row in selected_assistant} != chosen):
        raise ValueError("selected conversations are incomplete across annotation sheets")
    for row in selected_user + selected_assistant:
        row["double_label_required"] = (
            "true" if row["conversation_id"] in audit_ids else "false")

    output.mkdir(parents=True)
    copied_count = _copy_cited_sources(
        selected_user + selected_assistant, corpus_root, output)
    user_out = output / "user_turns_to_label.csv"
    assistant_out = output / "assistant_turns_to_label.csv"
    _write_csv(user_out, user_fields, selected_user)
    _write_csv(assistant_out, assistant_fields, selected_assistant)
    manifest = {
        "format": "crms-dialogue-feasibility-batch-v1",
        "seed": SEED,
        "source_split": "train only",
        "conversation_count": len(chosen),
        "double_label_conversation_count": len(audit_ids),
        "double_label_fraction_requested": double_label_fraction,
        "user_turn_count": len(selected_user),
        "assistant_turn_count": len(selected_assistant),
        "transcript_count": copied_count,
        "label_policy": "all label cells remain blank; CRMS predictions are not labels",
        "selected_conversation_ids": sorted(chosen),
        "double_label_conversation_ids": sorted(audit_ids),
        "user_sheet": user_out.name,
        "assistant_sheet": assistant_out.name,
        "corpus_directory": "corpus/",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_sheet", type=Path)
    parser.add_argument("assistant_sheet", type=Path)
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--conversations", type=int, default=40)
    parser.add_argument("--double-label-fraction", type=float, default=0.2)
    args = parser.parse_args()
    manifest = create_batch(
        args.user_sheet, args.assistant_sheet, args.corpus_root, args.output,
        conversations=args.conversations,
        double_label_fraction=args.double_label_fraction)
    print(json.dumps({key: value for key, value in manifest.items()
                      if key not in {"selected_conversation_ids",
                                     "double_label_conversation_ids"}},
                     indent=2))


if __name__ == "__main__":
    main()
