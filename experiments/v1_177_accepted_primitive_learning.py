"""Exercise explicit promotion of a validated proposal into rule learning.

Run from the project root with:
    python3 experiments/v1_177_accepted_primitive_learning.py

Proposal remains report-only until ``accept_primitive_candidate`` is called.
"""
from __future__ import annotations

import sys
import json
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


TASKS = {
    "add neighboring values": [
        ([2, 5, -1, 7, 4], [7, 4, 6, 11]),
        ([8, -3, 6, 0, -2, 9], [5, 3, 6, -2, 7]),
        ([-4, 1, 10, -7, 3, 2, 8], [-3, 11, 3, -4, 5, 10]),
    ],
    "sum consecutive numbers": [
        ([5, 2, -6, 3, 9], [7, -4, -3, 12]),
        ([-8, 4, 1, 7, -5, 2], [-4, 5, 8, 2, -3]),
        ([3, 12, -2, -9, 6, 5, 0], [15, 10, -11, -3, 11, 5]),
    ],
    "total each adjacent pair": [
        ([7, -1, 8, 2, -4], [6, 7, 10, -2]),
        ([0, 5, -3, -8, 4, 6], [5, 2, -11, -4, 10]),
        ([-6, -2, 11, 3, 5, -7, 9], [-8, 9, 14, 8, -2, 2]),
    ],
}

STRUCTURED_LANGUAGE_TASKS = {
    "sum neighboring values": [
        ([1, 2, 3, 4], [3, 5, 7]),
        ([6, -1, 4, 8], [5, 3, 12]),
    ],
    "sum consecutive values": [
        ([2, 7, -3, 5], [9, 4, 2]),
        ([-4, 1, 6, 2], [-3, 7, 8]),
    ],
    "add adjacent values": [
        ([5, 3, 9, -2], [8, 12, 7]),
        ([-6, 2, 4, 0], [-4, 6, 4]),
    ],
    "combine adjacent values": [
        ([9, -1, 3, 7], [8, 2, 10]),
        ([1, 8, -5, 2], [9, 3, -3]),
    ],
}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "accepted.json"
        model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        for phrase, examples in TASKS.items():
            result = model.teach(phrase, examples)
            if result.status != "no_fit":
                raise SystemExit(f"expected no_fit before acceptance: {phrase} {result}")

        proposals = model.propose_primitive_candidates()
        if len(proposals) != 1:
            raise SystemExit(f"expected one validated proposal, got {proposals}")
        descriptor = proposals[0]["descriptor"]
        if (model.accepted_primitive_candidates()
                or model.accepted_primitive_artifacts()):
            raise SystemExit("proposal was active before explicit acceptance")

        try:
            model.accept_primitive_candidate({**descriptor, "stride": 3})
        except ValueError:
            pass
        else:
            raise SystemExit("unvalidated primitive descriptor was accepted")
        if not model.accept_primitive_candidate(descriptor):
            raise SystemExit("first explicit acceptance was not recorded")
        if model.accepted_primitive_candidates() != [descriptor]:
            raise SystemExit("accepted primitive schema was not recorded exactly")
        if model.accepted_primitive_artifacts() != [proposals[0]]:
            raise SystemExit("accepted primitive lost its proposal lineage")
        if model.propose_primitive_candidates():
            raise SystemExit("stale no-fit records seeded a proposal after grammar change")

        for phrase, examples in TASKS.items():
            learned = model.retry(phrase)
            if learned.status != "learned":
                raise SystemExit(f"accepted primitive did not learn {phrase}: {learned}")
            if learned.procedure != [{
                    "operation": "map_window_binary",
                    "parameters": {"operator_id": 0, "window_width": 2,
                                   "left_offset": 0, "right_offset": 1,
                                   "stride": 1}}]:
                raise SystemExit(f"unexpected synthesized procedure: {learned.procedure}")
            probe = [9, -4, 12, 3, -8]
            expected = [left + right for left, right in zip(probe, probe[1:])]
            if model.predict(phrase, probe).output != expected:
                raise SystemExit(f"accepted primitive failed prediction for {phrase}")

        # The CLI default searches to depth two. At that depth, identity
        # aliases must not create false ambiguity, while a genuinely distinct
        # competing behavior should trigger a contrastive question. The
        # teacher's answer should then select the accepted primitive.
        default_depth_memory = Path(directory) / "accepted-default-depth.json"
        default_depth_model = CRMSModel(
            default_depth_memory, max_composition_depth=2, max_workers=1)
        for phrase, examples in TASKS.items():
            if default_depth_model.teach(phrase, examples).status != "no_fit":
                raise SystemExit("default-depth fixture unexpectedly fit before acceptance")
        default_descriptor = default_depth_model.propose_primitive_candidates()[0]["descriptor"]
        default_depth_model.accept_primitive_candidate(default_descriptor)
        pending = default_depth_model.retry("add neighboring values")
        if (pending.status != "need_more_examples"
                or pending.contrastive_input is None
                or pending.candidate_count != 3):
            raise SystemExit(
                f"default-depth search did not expose the expected contrast: {pending}")
        contrast_input = pending.contrastive_input
        contrast_output = [left + right for left, right in
                           zip(contrast_input, contrast_input[1:])]
        default_depth_model.teach(
            "add neighboring values", [(contrast_input, contrast_output)])
        resolved = default_depth_model.retry("add neighboring values")
        if (resolved.status != "learned" or resolved.candidate_count != 1
                or resolved.procedure != [{
                    "operation": "map_window_binary",
                    "parameters": {"operator_id": 0, "window_width": 2,
                                   "left_offset": 0, "right_offset": 1,
                                   "stride": 1}}]):
            raise SystemExit(
                f"default-depth contrast did not resolve to the accepted primitive: {resolved}")

        # Once installed, ordinary demonstrations can use the new operation.
        new_phrase = "combine adjacent entries"
        new_examples = [([1, 9, -2, 4], [10, 7, 2]),
                        ([-5, 3, 8, 0, 6], [-2, 11, 8, 6])]
        if model.teach(new_phrase, new_examples).status != "learned":
            raise SystemExit("active primitive did not participate in rule learning")

        for phrase, examples in STRUCTURED_LANGUAGE_TASKS.items():
            if model.teach(phrase, examples).status != "learned":
                raise SystemExit(f"structured language phrase did not learn: {phrase}")
        unseen_combination = "sum adjacent values"
        prediction = model.predict(unseen_combination, [3, -2, 6, 5])
        if (prediction.status != "ok" or prediction.output != [1, 4, 11]
                or not prediction.matched_templates
                or "{add|combine|sum}" not in prediction.matched_templates[0]
                or not prediction.evidence_phrases
                or unseen_combination in model._procedures):
            raise SystemExit(
                f"phrase-frame transfer failed for an unseen combination: {prediction}")

        restored = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        if restored.accepted_primitive_candidates() != [descriptor]:
            raise SystemExit("accepted primitive did not persist")
        if restored.accepted_primitive_artifacts() != [proposals[0]]:
            raise SystemExit("accepted primitive provenance did not persist")
        restored.load()
        if restored.accepted_primitive_candidates() != [descriptor]:
            raise SystemExit("reloading duplicated or lost an accepted primitive")
        if restored.accepted_primitive_artifacts() != [proposals[0]]:
            raise SystemExit("reloading changed accepted primitive provenance")
        audit = restored.audit_accepted_primitive_artifacts()
        if (len(audit) != 1 or audit[0]["evidence_status"] != "current"
                or audit[0]["changed_sources"]):
            raise SystemExit("accepted primitive sources were not current after reload")
        stale_audit_model = CRMSModel(
            memory, max_composition_depth=1, max_workers=1)
        changed_phrase = next(iter(TASKS))
        stale_audit_model.forget(changed_phrase)
        stale_audit = stale_audit_model.audit_accepted_primitive_artifacts()
        if (len(stale_audit) != 1 or stale_audit[0]["evidence_status"] != "stale"
                or stale_audit[0]["changed_sources"] != [changed_phrase]
                or not stale_audit_model.accepted_primitive_candidates()):
            raise SystemExit(
                "forgetting source evidence did not report stale lineage while retaining acceptance")
        legacy_memory = Path(directory) / "legacy-accepted.json"
        legacy_payload = json.loads(memory.read_text(encoding="utf-8"))
        legacy_payload.pop("accepted_primitive_artifacts")
        legacy_memory.write_text(json.dumps(legacy_payload), encoding="utf-8")
        legacy_restored = CRMSModel(
            legacy_memory, max_composition_depth=1, max_workers=1)
        if (legacy_restored.accepted_primitive_candidates() != [descriptor]
                or legacy_restored.accepted_primitive_artifacts()):
            raise SystemExit("legacy accepted descriptor did not load cleanly")
        tampered_memory = Path(directory) / "tampered-accepted.json"
        tampered_payload = json.loads(memory.read_text(encoding="utf-8"))
        tampered_payload["accepted_primitive_artifacts"][0]["lineage"][0][
            "fingerprint"] = "0" * 64
        tampered_memory.write_text(json.dumps(tampered_payload), encoding="utf-8")
        try:
            CRMSModel(tampered_memory, max_composition_depth=1, max_workers=1)
        except ValueError as error:
            if "artifact ID is invalid" not in str(error):
                raise
        else:
            raise SystemExit("tampered accepted primitive lineage was loaded")
        for phrase, examples in TASKS.items():
            if restored.predict(phrase, [4, -7, 2]).output != [-3, -5]:
                raise SystemExit(f"persisted learned rule failed for {phrase}")
        transferred = restored.predict(unseen_combination, [3, -2, 6, 5])
        if transferred.status != "ok" or transferred.output != [1, 4, 11]:
            raise SystemExit("phrase-frame transfer did not survive persistence")
        try:
            restored.revoke_primitive_candidate(descriptor)
        except ValueError as error:
            if "add neighboring values" not in str(error):
                raise
        else:
            raise SystemExit("primitive was revoked while learned rules depended on it")

        rollback_memory = Path(directory) / "rollback.json"
        rollback_model = CRMSModel(
            rollback_memory, max_composition_depth=1, max_workers=1)
        for phrase, examples in TASKS.items():
            if rollback_model.teach(phrase, examples).status != "no_fit":
                raise SystemExit("rollback fixture unexpectedly fit before acceptance")
        rollback_proposal = rollback_model.propose_primitive_candidates()[0]
        rollback_descriptor = rollback_proposal["descriptor"]
        rollback_model.accept_primitive_candidate(rollback_descriptor)
        if not rollback_model.revoke_primitive_candidate(rollback_descriptor):
            raise SystemExit("explicit primitive revocation failed")
        if (rollback_model.accepted_primitive_candidates()
                or rollback_model.accepted_primitive_artifacts()
                or rollback_model.propose_primitive_candidates()
                != [rollback_proposal]):
            raise SystemExit("revocation did not restore the prior grammar/proposal state")
        rollback_restored = CRMSModel(
            rollback_memory, max_composition_depth=1, max_workers=1)
        if (rollback_restored.accepted_primitive_candidates()
                or rollback_restored.accepted_primitive_artifacts()
                or rollback_restored.propose_primitive_candidates()
                != [rollback_proposal]):
            raise SystemExit("revoked grammar state did not persist")

        product_memory = Path(directory) / "accepted-product.json"
        product_model = CRMSModel(
            product_memory, max_composition_depth=1, max_workers=1)
        product_tasks = {
            "multiply neighboring values": [
                ([2, -3, 5, 4, -2], [-6, -15, 20, -8]),
                ([7, 1, -4, 3, 6, -2], [7, -4, -12, 18, -12]),
                ([-5, -2, 8, 3, 1, 9, -4], [10, -16, 24, 3, 9, -36]),
            ],
            "multiply consecutive numbers": [
                ([3, 6, -2, 7, 4], [18, -12, -14, 28]),
                ([-9, 2, 5, -3, 8, 1], [-18, 10, -15, -24, 8]),
                ([4, -1, -7, 6, 2, 5, 3], [-4, 7, -42, 12, 10, 15]),
            ],
            "find products of adjacent entries": [
                ([-2, 8, 3, -5, 7], [-16, 24, -15, -35]),
                ([5, 0, -6, 4, 2, -9], [0, 0, -24, 8, -18]),
                ([1, -8, -3, 7, 6, 2, -5], [-8, 24, -21, 42, 12, -10]),
            ],
        }
        for phrase, examples in product_tasks.items():
            if product_model.teach(phrase, examples).status != "no_fit":
                raise SystemExit(f"product task unexpectedly fit before acceptance: {phrase}")
        product_proposals = product_model.propose_primitive_candidates()
        if (len(product_proposals) != 1
                or product_proposals[0]["descriptor"]["operator"] != "multiply"):
            raise SystemExit(f"product primitive was not proposed: {product_proposals}")
        product_descriptor = product_proposals[0]["descriptor"]
        product_model.accept_primitive_candidate(product_descriptor)
        if product_model.retry("multiply neighboring values").status != "learned":
            raise SystemExit("accepted multiplication primitive did not synthesize a rule")
        if product_model.predict("multiply neighboring values", [3, -4, 6]).output != [-12, -24]:
            raise SystemExit("accepted multiplication primitive predicted incorrectly")

        cli_memory = Path(directory) / "chat-rules.json"
        cli_model = CRMSModel(
            cli_memory, max_composition_depth=1, max_workers=1)
        for phrase, examples in TASKS.items():
            if cli_model.teach(phrase, examples).status != "no_fit":
                raise SystemExit(f"CLI fixture unexpectedly fit: {phrase}")
        cli_proposal_id = cli_model.propose_primitive_candidates()[0]["artifact_id"]
        cli_root = Path(__file__).resolve().parents[1]
        cli_args = [
            sys.executable, str(cli_root / "crms_chat.py"),
            "--rules", str(cli_memory), "--rule-depth", "1",
            "--knowledge", str(Path(directory) / "chat-knowledge.json"),
            "--index", str(Path(directory) / "chat-index.json"),
            "--dialogue-state", str(Path(directory) / "chat-dialogue.json"),
            "--rule-session", str(Path(directory) / "chat-session.json"),
        ]
        cli = subprocess.run(
            cli_args,
            input=(f"Show primitive proposals\n"
                   f"Please accept primitive proposal {cli_proposal_id.upper()}.\n"
                   "/accepted-primitive-artifacts\n"
                   "Try to learn the rule for add neighboring values.\n"
                   "/apply-rule add neighboring values|3,-2,6\n"
                   "/revoke-primitive 1\n/quit\n"),
            text=True, capture_output=True, timeout=20, cwd=cli_root)
        if (cli.returncode != 0
                or "Accepted the current validated primitive proposal into this model's search grammar" not in cli.stdout
                or proposals[0]["artifact_id"] not in cli.stdout
                or "held-out examples=" not in cli.stdout
                or "These proposals are report-only" not in cli.stdout
                or "evidence=current" not in cli.stdout
                or "Rule learning status: learned" not in cli.stdout
                or "CRMS> [1, 4]" not in cli.stdout
                or "Could not revoke primitive: primitive is used" not in cli.stdout):
            raise SystemExit(f"chat CLI primitive workflow failed: {cli.stdout}\n{cli.stderr}")

    print("accepted primitive learning diagnostic: PASS")
    print("explicit acceptance/revocation, addition/multiplication synthesis, "
          "default-depth contrast resolution, unseen phrase-frame recombination, "
          "persistence, and chat CLI workflow: PASS")


if __name__ == "__main__":
    main()
