"""Check report-only abstraction proposals from successful multi-step rules."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "scaffolds.json"
        model = CRMSModel(path, max_composition_depth=2, max_workers=1)
        inputs = ([1, 4, -2], [5, -3, 8], [0, 6, -7], [9, 2, 1])
        for phrase, offset in (("alpha", 1), ("bravo", 2),
                               ("charlie", 3), ("delta", 4)):
            examples = [(list(values), list(reversed([x + offset for x in values])))
                        for values in inputs]
            result = model.teach(phrase, examples)
            require(result.status == "learned" and result.procedure
                    and [step["operation"] for step in result.procedure]
                    == ["add_k", "reverse"],
                    f"fixture did not learn the intended scaffold for {phrase}: {result}")

        before = model.list_rules()
        proposals = model.propose_procedure_scaffolds()
        require(len(proposals) == 1, f"expected one success abstraction: {proposals}")
        proposal = proposals[0]
        require(proposal["descriptor"] == [
            {"operation": "add_k", "parameters": {"k": {"slot": "step0.k"}}},
            {"operation": "reverse", "parameters": {}},
        ], f"unexpected anti-unified scaffold: {proposal}")
        require(proposal["supporting_instructions"] == ["alpha", "charlie", "delta"]
                and proposal["held_out_instructions"] == ["bravo"]
                and proposal["training_parameter_values"] == {"step0.k": [1, 3, 4]}
                and proposal["artifact_id"].startswith("procedure-scaffold-v1-")
                and proposal["artifact_version"] == 1
                and [item["role"] for item in proposal["lineage"]]
                == ["training", "training", "training", "held_out"]
                and proposal["held_out_validation_examples"] == len(inputs)
                and proposal["held_out_valid"] and proposal["mdl_gate_passed"]
                and proposal["description_length_gain_bits"] > 0
                and proposal["report_only"],
                f"scaffold evidence or deterministic holdout is malformed: {proposal}")
        require(model.list_rules() == before
                and model.predict("alpha", [3, 7]).output == [8, 4],
                "report-only proposal changed rules or prediction behavior")

        restored = CRMSModel(path, max_composition_depth=2, max_workers=1)
        restored.load()
        require(restored.propose_procedure_scaffolds() == proposals,
                "successful procedure scaffold proposal changed after persistence")
        require(restored.retrieve_procedure_scaffold(proposal["artifact_id"])
                == proposal
                and restored.retrieve_procedure_scaffold(
                    "procedure-scaffold-v1-stale") is None,
                "artifact retrieval did not require a current validated ID")

        cli = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--knowledge", str(Path(directory) / "knowledge.json"),
             "--index", str(Path(directory) / "index.json"),
             "--dialogue-state", str(Path(directory) / "dialogue.json"),
             "--rules", str(path),
             "--rule-session", str(Path(directory) / "rule-session.json")],
            input="/procedure-scaffolds\n/rules\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(cli.returncode == 0
                and "supporting: alpha, charlie, delta" in cli.stdout
                and proposal["artifact_id"] in cli.stdout
                and "sha256:" in cli.stdout
                and "held out: bravo (4 demonstrations reconstructed)" in cli.stdout
                and "procedure MDL:" in cli.stdout
                and "Report only: no rules or grammar changed." in cli.stdout,
                f"CLI did not expose reviewable report-only scaffolds:\n"
                f"{cli.stdout}\n{cli.stderr}")
        after_cli = CRMSModel(path, max_composition_depth=2, max_workers=1)
        after_cli.load()
        require(after_cli.list_rules() == before,
                "CLI scaffold inspection changed learned rules")

        # A contradictory held-out demonstration must block the scaffold.
        restored._examples["bravo"][-1] = (
            restored._examples["bravo"][-1][0], [999])
        # Direct private-state mutation bypasses normal cache invalidation.
        restored._procedure_scaffold_cache.clear()
        require(not restored.propose_procedure_scaffolds(),
                "scaffold survived a corrupted held-out demonstration")

        fixed = CRMSModel(max_composition_depth=2, max_workers=1)
        for phrase in ("one", "two", "three"):
            fixed.teach(phrase, [(list(values), list(reversed([x + 2 for x in values])))
                                 for values in inputs])
        require(not fixed.propose_procedure_scaffolds(),
                "constant parameter slots produced a spurious abstraction")

        cache_probe = CRMSModel(max_composition_depth=2, max_workers=1)
        for phrase, offset in (("alpha", 1), ("bravo", 2),
                               ("charlie", 3), ("delta", 4)):
            cache_probe.teach(
                phrase, [(list(values),
                          list(reversed([value + offset for value in values])))
                         for values in inputs])
        initial = cache_probe.propose_procedure_scaffolds()
        cache_probe.teach(
            "echo", [(list(values), list(reversed([value + 5 for value in values])))
                     for values in inputs])
        expanded = cache_probe.propose_procedure_scaffolds()
        require(initial and expanded
                and expanded[0]["held_out_instructions"] == ["bravo"]
                and "echo" in expanded[0]["supporting_instructions"]
                and expanded[0]["artifact_id"] != initial[0]["artifact_id"]
                and expanded != initial,
                "teaching a success did not invalidate its scaffold index")
        cache_probe.forget("echo")
        reverted = cache_probe.propose_procedure_scaffolds()
        require(reverted == initial
                and reverted[0]["artifact_id"] == initial[0]["artifact_id"],
                "forgetting a success did not invalidate its scaffold index")
        cache_probe.forget("bravo")
        require(cache_probe.retrieve_procedure_scaffold(
                    initial[0]["artifact_id"]) is None,
                "artifact ID remained retrievable after a lineage source was forgotten")

        changed_source = CRMSModel(max_composition_depth=2, max_workers=1)
        for phrase, offset in (("alpha", 1), ("bravo", 2),
                               ("charlie", 3), ("delta", 4)):
            changed_source.teach(
                phrase, [(list(values),
                          list(reversed([value + offset for value in values])))
                         for values in inputs])
        before_source_change = changed_source.propose_procedure_scaffolds()[0]
        additional_input = [11, -5, 3]
        changed_source.teach(
            "alpha", [(additional_input,
                       list(reversed([value + 1 for value in additional_input])))])
        after_source_change = changed_source.propose_procedure_scaffolds()[0]
        require(before_source_change["artifact_id"]
                != after_source_change["artifact_id"]
                and changed_source.retrieve_procedure_scaffold(
                    before_source_change["artifact_id"]) is None
                and changed_source.retrieve_procedure_scaffold(
                    after_source_change["artifact_id"]) == after_source_change,
                "artifact identity did not track changed source demonstrations")

    print("successful procedure scaffold diagnostic: PASS")
    print("varying-slot abstraction, MDL gain, holdout reconstruction, persistence, report-only CLI, and no mutation: PASS")


if __name__ == "__main__":
    main()
