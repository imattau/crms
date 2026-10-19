"""Verify declared labeler attribution stays distinct from source evidence."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import generate_python, show_generated_code_evidence
from crms_model import CRMSModel, _write_rule_database


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    model = CRMSModel(max_workers=1)
    source = "python-sorting#sha256=" + "a" * 64 + "&chars=10:40"
    taught = model.teach(
        "sort the values",
        [([3, 1, 2], [1, 2, 3]), ([4, 4, -1], [-1, 4, 4]),
         ([3, -5, 2], [-5, 2, 3]), ([9, 1, 5, 2], [1, 2, 5, 9])],
        source_ids=[source, None, None, None],
        labeler_ids=["codex:labeler-v1", "user:review", "user:review",
                     "user:review"],
    )
    require(taught.status == "learned", f"sort rule did not learn: {taught!r}")
    expected_records = [
        {"phrase": "sort the values", "input": [3, 1, 2],
         "output": [1, 2, 3], "source_id": source,
         "labeler_id": "codex:labeler-v1"},
        {"phrase": "sort the values", "input": [4, 4, -1],
         "output": [-1, 4, 4], "source_id": None,
         "labeler_id": "user:review"},
        {"phrase": "sort the values", "input": [3, -5, 2],
         "output": [-5, 2, 3], "source_id": None,
         "labeler_id": "user:review"},
        {"phrase": "sort the values", "input": [9, 1, 5, 2],
         "output": [1, 2, 5, 9], "source_id": None,
         "labeler_id": "user:review"},
    ]
    require(model.example_records("sort the values") == expected_records,
            "source and labeler attribution were not aligned per example")

    artifact = generate_python(model, "sort the values")
    require(artifact is not None, "attributed rule did not generate code")
    evidence = show_generated_code_evidence(artifact)
    require("[Declared labeler: codex:labeler-v1]" in evidence
            and "[Declared labeler: user:review]" in evidence
            and "[Source not recorded]" in evidence,
            "user-facing evidence does not distinguish source and labeler")

    require(model.retry("sort the values").status == "learned",
            "retry lost the learned behavior")
    require(model.example_records("sort the values") == expected_records,
            "retry changed source or labeler attribution")

    with tempfile.TemporaryDirectory(prefix="crms-rule-labelers-") as folder:
        root = Path(folder)
        for suffix in (".json", ".sqlite3"):
            path = root / f"rules{suffix}"
            model.save(path)
            restored = CRMSModel(path, max_workers=1)
            require(restored.example_records("sort the values")
                    == expected_records,
                    f"{suffix} round trip lost attribution alignment")
            require(restored.predict("sort the values", [6, 1, 6])
                    .output == [1, 6, 6],
                    f"{suffix} round trip changed the learned rule")

        legacy_path = root / "legacy.json"
        model.save(legacy_path)
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        payload.pop("example_labelers")
        legacy_path.write_text(json.dumps(payload), encoding="utf-8")
        legacy = CRMSModel(legacy_path, max_workers=1)
        require(all(record["labeler_id"] is None
                    for record in legacy.example_records("sort the values")),
                "legacy records were assigned invented labelers")

        legacy_sqlite_path = root / "legacy.sqlite3"
        legacy_payload = json.loads(json.dumps(payload))
        _write_rule_database(legacy_sqlite_path, legacy_payload)
        legacy_sqlite = CRMSModel(legacy_sqlite_path, max_workers=1)
        require(all(record["labeler_id"] is None
                    for record in legacy_sqlite.example_records("sort the values"))
                and legacy_sqlite.example_sources("sort the values") == [source],
                "legacy SQLite memory invented labelers or lost source IDs")

        malformed_path = root / "malformed.json"
        malformed = json.loads(legacy_path.read_text(encoding="utf-8"))
        malformed["example_labelers"] = {
            "sort the values": ["only-one"]}
        malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
        try:
            CRMSModel(malformed_path, max_workers=1)
        except ValueError:
            pass
        else:
            raise SystemExit("misaligned stored labeler IDs were accepted")

    bad = CRMSModel(max_workers=1)
    try:
        bad.teach("bad labeler", [([1], [1]), ([2], [2])],
                  labeler_ids=["only-one"])
    except ValueError:
        pass
    else:
        raise SystemExit("misaligned labeler IDs were silently accepted")
    require(not bad.example_records("bad labeler"),
            "invalid labeler metadata partially modified the model")

    require(model.forget("sort the values"), "learned rule was not forgotten")
    require(model.example_records("sort the values") == [],
            "forget left labeler/example records behind")

    print("source and declared labeler remain separate per example: PASS")
    print("retry, JSON, and SQLite preserve aligned attribution: PASS")
    print("legacy JSON and SQLite remain explicitly unlabelled: PASS")
    print("artifact evidence displays labeler without treating it as validation: PASS")
    print("misaligned attribution rejected; forget removes all associated records: PASS")


if __name__ == "__main__":
    main()
