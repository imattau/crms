"""Keep per-example source lineage through learned-rule composition."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import generate_python, show_generated_code_evidence
from crms_model import CRMSModel


VALUES = ([3, 1, 2], [4, -1, 7], [0, 5, -2, 8], [-5, 9], [12], [])
PROBE = [0, 0]
HOLDOUT_SOURCE = "fixture:held-out-evaluation-tasks"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def apply(values: list[int], operation: str) -> list[int]:
    if operation == "sort":
        return sorted(values)
    if operation == "reverse":
        return list(reversed(values))
    if operation == "unique":
        return list(dict.fromkeys(values))
    raise ValueError(operation)


def sequence(values: list[int], first: str, second: str) -> list[int]:
    return apply(apply(values, first), second)


def learn(model: CRMSModel, phrase: str, operation: str,
          source: str) -> None:
    examples = [*VALUES, PROBE]
    result = model.teach(
        phrase,
        [(values, apply(values, operation)) for values in examples],
        source_ids=[source] * len(examples),
    )
    require(result.status == "learned",
            f"component procedure did not learn: {phrase}: {result}")


def train() -> CRMSModel:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    for phrase, operation, source in (
        ("sort the list", "sort", "fixture:list-operations"),
        ("sort the values", "sort", "fixture:ordering-examples"),
        ("reverse the list", "reverse", "fixture:list-operations"),
        ("reverse the values", "reverse", "fixture:ordering-examples"),
        ("remove duplicate values", "unique", "fixture:cleanup-examples"),
    ):
        learn(model, phrase, operation, source)

    for phrase, first, second, source in (
        ("sort the list then reverse the values", "sort", "reverse",
         "fixture:order-sequences-a"),
        ("reverse the list then sort the values", "reverse", "sort",
         "fixture:order-sequences-b"),
    ):
        examples = [*VALUES, PROBE]
        result = model.teach(
            phrase,
            [(values, sequence(values, first, second)) for values in examples],
            source_ids=[source] * len(examples),
        )
        require(result.status == "learned",
                f"sequence rule did not learn: {phrase}: {result}")
    return model


def main() -> None:
    model = train()
    heldout_instruction = "sort the list then reverse the list"
    heldout_input = [4, 1, 4, 2]
    heldout_expected = [4, 4, 2, 1]
    training_sources = {
        source for phrase in model._examples
        for source in model.example_sources(phrase)
    }
    require(HOLDOUT_SOURCE not in training_sources,
            "held-out task source leaked into the trained model")
    result = model.predict(heldout_instruction, heldout_input)
    require(result.status == "ok" and result.output == heldout_expected,
            f"source-backed unseen composition failed: {result!r}")
    require(set(result.evidence_phrases or []) >= {
                "sort the list", "reverse the list",
                "sort the list then reverse the values",
                "reverse the list then sort the values"},
            f"composition omitted the rule/component lineage: {result!r}")

    artifact = generate_python(model, heldout_instruction)
    require(artifact is not None,
            "held-out natural-language composition did not generate code")
    namespace: dict[str, object] = {}
    exec(compile(artifact.source, "<source-disjoint-composition>", "exec"),
         namespace)
    require(namespace["transform"](heldout_input) == heldout_expected
            and namespace["validate_examples"](),
            "composed artifact failed independent parity checks")
    recorded_examples = namespace["CRMS_PROVENANCE"]["examples"]
    expected_artifact_sources = {
        source for phrase in artifact.evidence_phrases
        for source in model.example_sources(phrase)
    }
    recorded_sources = {row["source_id"] for row in recorded_examples}
    require(recorded_sources == expected_artifact_sources,
            f"artifact source lineage is incomplete: {recorded_sources!r}")
    require(HOLDOUT_SOURCE not in recorded_sources,
            "artifact provenance includes the held-out task source")
    evidence_view = show_generated_code_evidence(artifact)
    require(all(f"[Source: {source}]" in evidence_view
                for source in expected_artifact_sources),
            "human-readable artifact evidence omitted source IDs")

    with tempfile.TemporaryDirectory(prefix="crms-procedure-lineage-") as folder:
        root = Path(folder)
        for suffix in (".json", ".sqlite3"):
            path = root / f"rules{suffix}"
            model.save(path)
            restored = CRMSModel(path, max_composition_depth=2, max_workers=1)
            require({source for phrase in restored._examples
                     for source in restored.example_sources(phrase)}
                    == training_sources,
                    f"{suffix} round trip lost source lineage")
            repeated = restored.predict(heldout_instruction, heldout_input)
            require(repeated.status == "ok"
                    and repeated.output == heldout_expected,
                    f"{suffix} round trip changed behavior: {repeated!r}")

        # A pre-lineage JSON memory remains readable and honestly unlabelled.
        legacy_path = root / "legacy.json"
        model.save(legacy_path)
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        payload.pop("example_sources")
        legacy_path.write_text(json.dumps(payload), encoding="utf-8")
        legacy = CRMSModel(legacy_path, max_composition_depth=2, max_workers=1)
        require(legacy.example_sources("sort the list") == []
                and all(row["source_id"] is None
                        for row in legacy.example_records("sort the list")),
                "legacy memory was assigned invented source lineage")

    try:
        model.teach("bad source alignment", [([1], [1]), ([2], [2])],
                    source_ids=["only-one-source"])
    except ValueError:
        pass
    else:
        raise SystemExit("misaligned source IDs were silently accepted")

    print("held-out composition: correct output, no held-out source leakage: PASS")
    print("generated code retains each example's source ID: PASS")
    print("JSON and SQLite preserve source lineage and behavior: PASS")
    print("legacy memories remain readable with provenance marked unknown: PASS")
    print("misaligned lineage is rejected: PASS")


if __name__ == "__main__":
    main()
