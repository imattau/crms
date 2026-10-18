"""End-to-end test of expression discovery, explicit acceptance, and learning."""
from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel
from crms_expression_discovery import propose_window_expression_primitives


def main() -> None:
    phrases = {
        "square each left value then add its neighbor": 2,
        "square each left number then add its neighbor": 7,
        "square each left value then add its follower": 13,
    }
    signed_pattern = [-4, 2, 0, -7, 3, 5, -1, 8]
    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "expression-memory.json"
        model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        for phrase, offset in phrases.items():
            examples = []
            for row in range(4):
                start = (offset + row) % len(signed_pattern)
                inputs = [signed_pattern[(start + index) % len(signed_pattern)]
                          for index in range(5 + row % 2)]
                outputs = [left * left + right
                           for left, right in zip(inputs, inputs[1:])]
                examples.append((inputs, outputs))
            if model.teach(phrase, examples).status != "no_fit":
                raise SystemExit(f"fixture unexpectedly fit existing grammar: {phrase}")

        proposals = model.propose_primitive_candidates()
        expression_proposals = [proposal for proposal in proposals
                                if proposal["descriptor"].get("operation")
                                == "map_window_expression"]
        expected_descriptor = {
            "operation": "map_window_expression",
            "expression": "(+ (* x x) y)",
            "stride": 1,
        }
        if (len(expression_proposals) != 1
                or expression_proposals[0]["descriptor"] != expected_descriptor
                or not expression_proposals[0]["held_out_valid"]
                or not expression_proposals[0]["mdl_gate_passed"]):
            raise SystemExit(f"unexpected expression discovery result: {proposals}")

        corrupted = model.no_fit_cases()
        for record in corrupted:
            index = record["proposal_split"]["held_out_indices"][0]
            record["examples"][index][1][0] += 1
        if propose_window_expression_primitives(
                corrupted, minimum_supporting_phrases=3):
            raise SystemExit("expression proposal survived corrupted holdouts")

        try:
            model.accept_primitive_candidate({
                **expected_descriptor, "expression": "(+ (* x x) x)"})
        except ValueError:
            pass
        else:
            raise SystemExit("unsupported expression was accepted")
        model.accept_primitive_candidate(expected_descriptor)
        if model.accepted_primitive_candidates() != [expected_descriptor]:
            raise SystemExit("accepted expression schema was not retained")

        for phrase, offset in phrases.items():
            result = model.retry(phrase)
            if (result.status != "learned" or result.procedure is None
                    or result.procedure[0]["operation"] != "map_window_expression"):
                raise SystemExit(f"expression did not synthesize a phrase rule: {result}")
            probe = [offset - 4, 3, -2, 5]
            expected = [left * left + right for left, right
                        in zip(probe, probe[1:])]
            prediction = model.predict(phrase, probe)
            if prediction.status != "ok" or prediction.output != expected:
                raise SystemExit(f"learned expression predicted incorrectly: {prediction}")

        # Recombine independently grounded word substitutions in a phrase
        # that has no demonstration or committed rule.
        recombined_phrase = "square each left number then add its follower"
        recombined = model.predict(recombined_phrase, [3, -2, 5])
        if (recombined.status != "ok" or recombined.output != [7, 9]
                or not recombined.evidence_phrases
                or len(recombined.evidence_phrases) < 2
                or not recombined.matched_templates
                or "{number|value}" not in recombined.matched_templates[0]
                or "{follower|neighbor}" not in recombined.matched_templates[0]):
            raise SystemExit(f"grounded phrase recombination failed: {recombined}")

        restored = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        if restored.accepted_primitive_candidates() != [expected_descriptor]:
            raise SystemExit("accepted expression did not survive persistence")
        for phrase, offset in phrases.items():
            probe = [offset, -3, 2]
            expected = [left * left + right for left, right
                        in zip(probe, probe[1:])]
            if restored.predict(phrase, probe).output != expected:
                raise SystemExit(f"persisted expression rule failed for {phrase}")

        try:
            restored.revoke_primitive_candidate(expected_descriptor)
        except ValueError as error:
            if not any(phrase in str(error) for phrase in phrases):
                raise
        else:
            raise SystemExit("expression was revoked despite dependent rules")

        cli_memory = Path(directory) / "expression-cli-memory.json"
        cli_model = CRMSModel(cli_memory, max_composition_depth=1, max_workers=1)
        phrase, offset = next(iter(phrases.items()))
        for example_phrase, example_offset in phrases.items():
            examples = []
            for row in range(4):
                start = (example_offset + row) % len(signed_pattern)
                inputs = [signed_pattern[(start + index) % len(signed_pattern)]
                          for index in range(5 + row % 2)]
                examples.append((inputs, [left * left + right
                                          for left, right in zip(inputs, inputs[1:])]))
            if cli_model.teach(example_phrase, examples).status != "no_fit":
                raise SystemExit("CLI fixture unexpectedly fit before acceptance")
        root = Path(__file__).resolve().parents[1]
        cli = subprocess.run([
            sys.executable, str(root / "crms_chat.py"),
            "--rules", str(cli_memory), "--rule-depth", "1",
            "--knowledge", str(Path(directory) / "cli-knowledge.json"),
            "--index", str(Path(directory) / "cli-index.json"),
            "--dialogue-state", str(Path(directory) / "cli-dialogue.json"),
            "--rule-session", str(Path(directory) / "cli-session.json"),
        ], input=("/primitive-proposals\n/accept-primitive 1\n"
                  f"/retry-rule {phrase}\n"
                  f"/apply-rule {phrase}|3,-2,5\n/quit\n"),
            text=True, capture_output=True, timeout=30, cwd=root)
        if (cli.returncode != 0
                or "map_window_expression" not in cli.stdout
                or "Accepted primitive into this model's search grammar" not in cli.stdout
                or "Rule learning status: learned" not in cli.stdout
                or "CRMS> [7, 9]" not in cli.stdout):
            raise SystemExit(f"expression primitive CLI workflow failed: "
                             f"{cli.stdout}\n{cli.stderr}")

    print("expression primitive discovery and learning: PASS")
    print("three-cluster discovery, holdout/MDL gates, explicit acceptance, "
          "procedure synthesis, unseen phrase-slot recombination, prediction, "
          "persistence, revocation guard, and chat CLI workflow: PASS")


if __name__ == "__main__":
    main()
