"""Check assistant-move and contextual user-intent annotation preparation."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.v1_363_prepare_taskmaster_dialogue_pilot import (
    _annotation_sample, _read_dialogues, prepare,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    payload = [
        {
            "conversation_id": "c1",
            "instruction_id": "restaurant-table-1",
            "utterances": [
                {"index": 0, "speaker": "USER", "text": "Hi."},
                {"index": 1, "speaker": "ASSISTANT", "text": "Hello."},
                {"index": 2, "speaker": "USER", "text": "I need a table."},
                {"index": 3, "speaker": "ASSISTANT", "text": "For when?"},
            ],
        },
        {
            "conversation_id": "c1",
            "instruction_id": "restaurant-table-1",
            "utterances": [
                {"index": 0, "speaker": "USER", "text": "Friday."},
                {"index": 1, "speaker": "ASSISTANT", "text": "At what time?"},
            ],
        },
        {
            "conversation_id": "c2",
            "instruction_id": "restaurant-table-1",
            "utterances": [
                {"index": 0, "speaker": "USER", "text": "Seven."},
                {"index": 1, "speaker": "", "text": "Unlabelled turn."},
                {"index": 2, "speaker": "ASSISTANT", "text": "Okay."},
            ],
        },
        {
            "conversation_id": "other-domain",
            "instruction_id": "coffee-ordering-1",
            "utterances": [
                {"index": 0, "speaker": "USER", "text": "A latte."},
                {"index": 1, "speaker": "ASSISTANT", "text": "Certainly."},
            ],
        },
        {"conversation_id": "empty", "instruction_id": "restaurant-table-1",
         "utterances": []},
    ]
    decoded, *_ = _read_dialogues(payload)
    sample_a = _annotation_sample(decoded, 2, "restaurant-table")
    sample_b = _annotation_sample(decoded, 2, "restaurant-table")
    require(sample_a == sample_b and len(sample_a) == 2,
            "conversation sample is not deterministic or domain-bounded")

    with tempfile.TemporaryDirectory(prefix="crms-dialogue-intent-pack-") as folder:
        root = Path(folder)
        source = root / "woz.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        output = root / "pilot"
        manifest = prepare(source, output, annotation_dialogues=2)

        assistant_rows = list(csv.DictReader(
            (output / "assistant_turns_to_label.csv").open(encoding="utf-8")))
        user_rows = list(csv.DictReader(
            (output / "user_turns_to_label.csv").open(encoding="utf-8")))
        require(len(assistant_rows) == manifest["annotation_assistant_turn_count"] == 4,
                "assistant move rows did not include all selected assistant turns")
        require(len(user_rows) == manifest["user_intent_turn_count"] == 4,
                "user intent rows did not include all selected user turns")
        require(manifest["assistant_turn_count"] == 5,
                "full-corpus assistant count excluded unsampled domains")
        require(manifest["duplicate_conversation_id_extra_records"] == 1
                and manifest["skipped_empty_dialogue_count"] == 1
                and manifest["unknown_speaker_turn_count"] == 1,
                "irregular dataset records were not preserved and reported")
        require({row["conversation_id"] for row in assistant_rows + user_rows}
                == {"c1", "c2"},
                "annotation worksheets crossed the selected domain or IDs")
        audit_by_id = {}
        for row in assistant_rows + user_rows:
            key = row["conversation_id"]
            flag = row["double_label_required"]
            require(key not in audit_by_id or audit_by_id[key] == flag,
                    "one conversation received inconsistent audit flags")
            audit_by_id[key] = flag
        require(any(value == "true" for value in audit_by_id.values())
                and manifest["double_label_dialogue_count"]
                == sum(value == "true" for value in audit_by_id.values()),
                "conversation-level reliability sample was not recorded")
        require(all(not row[field] for row in assistant_rows for field in (
                    "move_label", "move_label_2", "adjudicated_label"))
                and all(not row[field] for row in user_rows for field in (
                    "dialogue_act", "task_intent", "dialogue_act_2",
                    "task_intent_2", "adjudicated_dialogue_act",
                    "adjudicated_task_intent")),
                "the preparation tool assigned labels automatically")

    print("contextual user-intent rows and assistant-move rows: PASS")
    print("domain selection, repeated IDs, empty records, unknown speakers: PASS")
    print("unlabeled human-review fields and shared reliability sample: PASS")


if __name__ == "__main__":
    main()
