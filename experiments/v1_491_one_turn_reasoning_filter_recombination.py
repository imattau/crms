"""Join verified relation reasoning and a learned procedure in one chat turn.

The user supplies a finite integer domain, asks CRMS to retain values for which
an explicit relation is supported, and names a learned list transformation.
Only independently verified positive proofs are passed to the procedure;
negative values are excluded and unknown/conflicting values make the task
abstain. Fixtures and procedure instruction labels are explicit supervision.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_451_reasoned_procedure_composition import add_chain, discover_and_accept, learn_procedure
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def build_case() -> tuple[CRMSKnowledgeBase, object]:
    knowledge = CRMSKnowledgeBase()
    discover_and_accept(knowledge)
    add_chain(knowledge, "Nia", "Orin", "Axle", "12", "runtime:record-12",
              conclusion="none")
    add_chain(knowledge, "Nia", "Pia", "Bolt", "4", "runtime:record-4a",
              conclusion="none")
    add_chain(knowledge, "Nia", "Quin", "Cove", "4", "runtime:record-4b",
              conclusion="none")
    add_chain(knowledge, "Nia", "Rae", "Dune", "9", "runtime:record-9",
              conclusion="none")
    knowledge.add_negative_fact(
        "Nia", "reaches", "7", "runtime:record-7-negative")
    return knowledge, learn_procedure()


def main() -> None:
    knowledge, procedures = build_case()
    supported = (
        "From values 12, 4, 4, 9, and 7, keep only the values that Nia reaches, "
        "then remove duplicate values then reverse the list.")
    result = compose_verified_filter(supported, knowledge, procedures)
    require(result is not None and result.status == "answered"
            and result.included_values == (12, 4, 4, 9)
            and result.excluded_negative == (7,)
            and result.output_values == (9, 4, 12)
            and result.proof_checks == 4
            and len(result.inference_proofs) == 3
            and "runtime:record-7-negative" in {
                source for item in result.evidence
                for source in item.get("sources", ())},
            f"verified finite-set composition failed: {result}")
    alternate_surfaces = (
        "From 12, 4, 4, 9 and 7, keep values Nia reaches, then "
        "remove duplicate values then reverse the list.",
        "From the values 12, 4, 4, 9, and 7, keep only values which "
        "Nia reaches, then remove duplicate values then reverse the list.",
    )
    for surface in alternate_surfaces:
        alternate = compose_verified_filter(surface, knowledge, procedures)
        require(alternate is not None and alternate.status == "answered"
                and alternate.output_values == (9, 4, 12),
                f"a basic wording variant failed: {surface!r}: {alternate}")

    unknown = compose_verified_filter(
        "From values 12, 4, 8, keep only the values that Nia reaches, "
        "then remove duplicate values then reverse the list.",
        knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.output_values == ()
            and unknown.unresolved_values == (8,)
            and "did not run the procedure on a partial set" in unknown.text,
            f"unknown member was silently filtered or composed: {unknown}")

    conflicted = CRMSKnowledgeBase()
    discover_and_accept(conflicted)
    add_chain(conflicted, "Nia", "Sol", "Tern", "7", "runtime:record-7",
              conclusion="positive")
    conflicted.add_negative_fact(
        "Nia", "reaches", "7", "runtime:record-7-negative")
    conflict = compose_verified_filter(
        "From values 7, keep only the values that Nia reaches, "
        "then remove duplicate values then reverse the list.",
        conflicted, procedures)
    require(conflict is not None and conflict.status == "conflict"
            and not conflict.output_values
            and "runtime:record-7-negative" in conflict.evidence_sources
            and bool(conflict.inference_proofs),
            f"positive/negative conflict reached the procedure: {conflict}")

    unsupported = compose_verified_filter(
        "From values 12, 4, 4, 9, and 7, keep only the values that Nia reaches, "
        "then sort the values downward.", knowledge, procedures)
    require(unsupported is not None
            and unsupported.status == "unsupported_procedure"
            and not unsupported.output_values,
            f"unlearned operation was accepted: {unsupported}")

    with tempfile.TemporaryDirectory(prefix="crms-one-turn-compose-") as folder:
        root = Path(folder)
        knowledge.save(root / "knowledge.json")
        procedures.save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command,
            input=(supported + "\nwhy?\n"
                   "From values 12, 4, 8, keep only the values that Nia reaches, "
                   "then remove duplicate values then reverse the list.\nwhy?\n"
                   "Tell me a joke.\nwhy?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = chat.stdout + chat.stderr
        after_unrelated_turn = output.split(
            "I can compose a short fictional story", 1)[-1]
        require(chat.returncode == 0 and "Traceback" not in output
                and "[9, 4, 12]" in output
                and "runtime:record-12" in output
                and "runtime:record-7-negative" in output
                and "labeler: codex:task-labeler" in output
                and "you> CRMS> I can't determine whether 8 satisfy Nia reaches" in output
                and "did not run the procedure on a partial set" in output
                and "Because Nia" in output
                and "The list operation used 7 stored procedure examples" in output
                and "runtime:record-12" not in after_unrelated_turn
                and "Because Nia" not in after_unrelated_turn,
                f"ordinary fresh-process chat failed the one-turn composition:\n{output}")

    print("one user turn: proof-checked finite relation filter + learned list procedure: PASS")
    print("explicit negative excluded with source lineage; duplicate/order result correct: PASS")
    print("unknown and conflicted members block partial output: PASS")
    print("unsupported learned-procedure wording abstains: PASS")
    print("fresh-process chat answers, explains the current composition, and avoids stale why?: PASS")
    print("scope: bounded numeric finite-set frame with Codex-supervised components")


if __name__ == "__main__":
    main()
