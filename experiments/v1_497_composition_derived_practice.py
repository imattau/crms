"""Explicitly practice a verified composed output from chat.

Ordinary composition remains read-only. The user can ask CRMS to re-derive
the full request, then retain its output, proof set, procedure examples, and
lineage as a content-addressed derived artifact. Positive relation results are
also retained separately; correcting a dependency invalidates affected memory
rather than promoting it to a fact.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import copy
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_492_reasoned_filter_language_coverage import (
    build_case, learn_connective_procedures, teach_relation_surface,
)
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_task_composition import revalidate_derived_composition
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


REQUEST = (
    "From values 12, 4, 4, 9, and 7, keep only the values that Nia can reach, "
    "then remove duplicate values then reverse the list."
)
UNKNOWN_REQUEST = (
    "From values 12, 4, and 8, keep only the values that Nia can reach, then "
    "remove duplicate values then reverse the list."
)


def run_chat(root: Path, knowledge_path: Path, procedures_path: Path,
             index_path: Path, lines: tuple[str, ...]) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path),
        "--rules", str(procedures_path),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--index", str(index_path),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
    ]
    result = subprocess.run(
        command, input="\n".join((*lines, "/quit", "")), text=True,
        capture_output=True, cwd=root, timeout=60, check=False)
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"fresh-process chat failed:\n{output}")
    return output


def main() -> None:
    knowledge, _ = build_case()
    procedures = learn_connective_procedures()
    index = CRMSResearchIndex()
    teach_relation_surface(knowledge, index)

    with tempfile.TemporaryDirectory(prefix="crms-composition-practice-") as folder:
        root = Path(folder)
        knowledge_path = root / "model.sqlite3"
        procedures_path = root / "procedures.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(procedures_path)
        index.save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        # A successful answer alone must not mutate model knowledge.
        first_output = run_chat(root, knowledge_path, procedures_path,
                                index_path, (REQUEST,))
        require("[9, 4, 12]" in first_output,
                f"composition did not answer before practice: {first_output}")
        untouched = CRMSKnowledgeBase.load(knowledge_path)
        require(not untouched.derived_cases(),
                "ordinary composition wrote derived cases without opt-in")

        # The explicit action re-runs the proof path; it does not trust the
        # response's cached claims or add them to ordinary fact storage.
        output = run_chat(
            root, knowledge_path, procedures_path, index_path,
            (REQUEST, "/practice-composition", "/practice-composition",
             UNKNOWN_REQUEST, "/practice-composition", "/derived-cases",
             "/derived-compositions"))
        require("Stored the complete composed result [9, 4, 12] as derived artifact"
                    in output
                and "Separately verified derived relation cases are available"
                    in output
                and "[12, 4, 9]" in output
                and "These remain derived cases, not facts or new procedures."
                    in output
                and "already been practiced in this session" in output
                and "There is no successful proof-backed list composition"
                    in output
                and "Derived composition [current]" in output,
                f"explicit composition practice was not reported accurately:\n{output}")
        stored = CRMSKnowledgeBase.load(knowledge_path)
        cases = stored.derived_cases()
        by_object = {case["conclusion"]["object"]: case for case in cases}
        require(set(by_object) == {"12", "4", "9"}
                and all(case["status"] == "verified"
                        and case["practice_count"] == 1
                        and case["lineage"]["sources"]
                        and case["lineage"]["rule_ids"]
                        for case in by_object.values()),
                f"SQLite reload lost or invalidated practiced cases: {cases}")
        require(not any(fact.subject == "Nia" and fact.relation == "reaches"
                        and fact.object in by_object
                        for fact in stored.facts()),
                "practiced results were promoted into the fact store")
        artifacts = stored.derived_compositions()
        require(len(artifacts) == 1
                and artifacts[0]["output_values"] == [9, 4, 12]
                and artifacts[0]["procedure_records"]
                and artifacts[0]["inference_proofs"]
                and artifacts[0]["negative_evidence"]
                and artifacts[0]["language_evidence"]
                and artifacts[0]["lineage"]["sources"]
                and artifacts[0]["lineage"]["rule_ids"],
                f"complete output/procedure lineage did not survive reload: {artifacts}")
        tampered = copy.deepcopy(artifacts[0])
        tampered["output_values"] = [999]
        try:
            stored.record_derived_composition(tampered)
        except ValueError:
            pass
        else:
            raise SystemExit("tampered composition artifact passed its content identity")

        # Repeating the exact request in a new chat session must find the
        # content-addressed artifact instead of increasing practice counts.
        repeated = run_chat(root, knowledge_path, procedures_path, index_path,
                            (REQUEST, "/practice-composition"))
        require("already stored with current evidence" in repeated,
                f"a duplicate composition was practiced again: {repeated}")
        unchanged = CRMSKnowledgeBase.load(knowledge_path)
        require(all(case["practice_count"] == 1
                    for case in unchanged.derived_cases()),
                "repeating the same artifact inflated derived-case practice counts")

        mutated_procedures = copy.deepcopy(procedures)
        updated = mutated_procedures.teach(
            "reverse the list", [([31, 47], [47, 31])],
            source_ids=["review:additional-reverse-example"],
            labeler_ids=["codex:independent-practice-check"],
            instruction_source_ids=["review:reverse-instruction"])
        require(updated.status == "learned",
                f"could not add a consistent procedure example: {updated}")
        procedure_status, procedure_reason = revalidate_derived_composition(
            artifacts[0], stored, mutated_procedures)
        require(procedure_status == "stale"
                and "procedure examples changed" in procedure_reason,
                f"procedure change did not stale the composed artifact: "
                f"{procedure_status}: {procedure_reason}")
        mutated_path = root / "mutated-procedures.json"
        mutated_procedures.save(mutated_path)
        procedure_listing = run_chat(
            root, knowledge_path, mutated_path, index_path,
            ("/derived-compositions",))
        require("Derived composition [stale]" in procedure_listing
                and "procedure examples changed" in procedure_listing,
                f"chat did not explain procedure-driven staleness: {procedure_listing}")

        # Retraction invalidates exactly the case whose proof depended on the
        # removed premise. A derived case cannot stand in for that premise.
        require(stored.remove_fact("Nia", "employs", "Orin",
                                   "runtime:record-12"),
                "could not correct the source premise")
        stored.save(knowledge_path)
        corrected = CRMSKnowledgeBase.load(knowledge_path)
        artifact_status, artifact_reason = revalidate_derived_composition(
            artifacts[0], corrected, procedures)
        require(artifact_status == "stale"
                and ("knowledge or rule state changed" in artifact_reason
                     or "proof set changed" in artifact_reason
                     or "no longer proves" in artifact_reason),
                f"source correction did not stale the full composed artifact: "
                f"{artifact_status}: {artifact_reason}")
        evidence_listing = run_chat(
            root, knowledge_path, procedures_path, index_path,
            ("/derived-compositions",))
        require("Derived composition [stale]" in evidence_listing,
                f"chat did not show source-corrected artifact as stale: {evidence_listing}")
        require(corrected.retrieve_derived_case(
                    "Nia", "reaches", "12", record_use=False) is None,
                "a corrected dependency left its derived case usable")
        require(corrected.retrieve_derived_case(
                    "Nia", "reaches", "4", record_use=False) is not None
                and corrected.retrieve_derived_case(
                    "Nia", "reaches", "9", record_use=False) is not None,
                "correction invalidated unrelated practiced results")
        recomposed = compose_verified_filter(REQUEST, corrected, procedures)
        require(recomposed is not None and recomposed.status == "unknown"
                and recomposed.unresolved_values == (12,)
                and not recomposed.output_values,
                f"retracted premise was supplied by its derived case: {recomposed}")

    print("ordinary composition is read-only; explicit practice stores complete output and lineage: PASS")
    print("relation caches and composed artifacts survive SQLite reload outside facts: PASS")
    print("tampered artifacts are rejected; procedure changes mark artifacts stale: PASS")
    print("source correction invalidates dependent artifacts and preserves unrelated cases: PASS")
    print("stale derived memory cannot replace a missing proof premise: PASS")


if __name__ == "__main__":
    main()
