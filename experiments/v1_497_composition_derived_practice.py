"""Explicitly practice verified relation results from a chat composition.

Ordinary composition remains read-only. The user can ask CRMS to re-derive
and independently verify each positive relation result, retain those proofs as
separate derived cases, and later observe that correcting a premise invalidates
the affected cache rather than promoting it to a fact.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
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
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


REQUEST = (
    "From values 12, 4, 4, 9, and 7, keep only the values that Nia reaches, "
    "then remove duplicate values then reverse the list."
)
UNKNOWN_REQUEST = (
    "From values 12, 4, and 8, keep only the values that Nia reaches, then "
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
             UNKNOWN_REQUEST, "/practice-composition", "/derived-cases"))
        require("Stored separately verified derived relation cases" in output
                and "[12, 4, 9]" in output
                and "These remain derived cases, not facts or new procedures."
                    in output
                and "already been practiced in this session" in output
                and "There is no successful proof-backed list composition"
                    in output,
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

        # Retraction invalidates exactly the case whose proof depended on the
        # removed premise. A derived case cannot stand in for that premise.
        require(stored.remove_fact("Nia", "employs", "Orin",
                                   "runtime:record-12"),
                "could not correct the source premise")
        stored.save(knowledge_path)
        corrected = CRMSKnowledgeBase.load(knowledge_path)
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

    print("ordinary composition remains read-only; explicit practice stores 3 verified cases: PASS")
    print("derived cases survive SQLite reload without entering the fact store: PASS")
    print("source correction invalidates its dependent case and preserves unrelated cases: PASS")
    print("stale derived memory cannot replace a missing proof premise: PASS")


if __name__ == "__main__":
    main()
