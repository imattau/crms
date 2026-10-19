"""Validated inference rules and practiced proofs survive model packaging."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_package import (
    export_model_database,
    install_model_database,
    inspect_model_database,
    model_database_research_stats,
)
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_labeled_chain(kb: CRMSKnowledgeBase, index: CRMSSQLiteResearchIndex,
                      subject: str, middle: str, target: str,
                      document_id: str, url: str) -> None:
    text = (f"{subject} is parent of {middle}. {middle} is parent of {target}. "
            f"{subject} is ancestor of {target}.")
    index.add_document(document_id, f"Family record {document_id}", text, url)
    hit = next((row for row in index.search(
        f"{subject} parent {middle}", limit=5)
                if row.document_id == document_id), None)
    require(hit is not None, f"could not retrieve the training source {document_id}")
    citation = index.citation(hit)
    kb.add_fact(subject, "parent", middle, citation)
    kb.add_fact(middle, "parent", target, citation)
    kb.add_fact(subject, "ancestor", target, citation)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-validated-rule-package-") as folder:
        root = Path(folder)
        source_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(source_path)
        kb = CRMSKnowledgeBase()
        add_labeled_chain(kb, index, "Ada", "Bea", "Cal", "train:one",
                          "https://family-one.example/record")
        add_labeled_chain(kb, index, "Dee", "Eli", "Fay", "train:two",
                          "https://family-two.example/record")
        add_labeled_chain(kb, index, "Gus", "Hal", "Ivy", "holdout:one",
                          "https://family-three.example/record")
        add_labeled_chain(kb, index, "Jo", "Kim", "Lou", "holdout:two",
                          "https://family-four.example/record")

        review = kb.review_inference_rules("holdout:", research_index=index)
        target = next((number for number, row in enumerate(review.reviews, 1)
                       if (row.candidate.first_relation,
                           row.candidate.second_relation,
                           row.candidate.conclusion_relation)
                       == ("parent", "parent", "ancestor")), None)
        require(target is not None and review.complete,
                f"transitivity candidate was not discovered completely: {review}")
        accepted = kb.accept_inference_rule_candidate(
            target, "learned-parent-chain", "holdout:", research_index=index)
        require(accepted.accepted
                and accepted.review is not None
                and accepted.review.validation is not None
                and accepted.review.validation.status == "validated",
                f"source-separated rule did not pass validation: {accepted}")

        # These are new, unlabeled premises: the packaged rule must derive the
        # conclusion rather than retrieve an explicit training label.
        kb.add_fact("Nia", "parent", "Oren", "probe:source-left")
        kb.add_fact("Oren", "parent", "Pia", "probe:source-right")
        practiced, retained = kb.practice_question(
            "Is Nia an ancestor of Pia?")
        require(practiced.status == "answered" and retained,
                f"validated rule did not produce a retained derived case: {practiced}")
        require(kb.retrieve_derived_case(
            "Nia", "ancestor", "Pia", record_use=False) is not None,
            "verified practice result was not retained before packaging")

        knowledge_path = root / "knowledge.sqlite"
        rules_path = root / "rules.sqlite"
        index.close()
        kb.save(knowledge_path)
        CRMSModel().save(rules_path)
        model_path = export_model_database(
            root / "portable-model.sqlite", knowledge=knowledge_path,
            rules=rules_path, research_index=source_path)

        memories = inspect_model_database(model_path)
        require({"knowledge", "rules"} <= memories.keys(),
                "portable package omitted its knowledge or rule memory")
        stats = model_database_research_stats(model_path)
        require(stats is not None and stats["documents"] == 4,
                f"source evidence was not embedded in the model: {stats}")
        with sqlite3.connect(model_path) as db:
            packed = json.loads(db.execute(
                "SELECT payload_json FROM learned_memories "
                "WHERE kind='knowledge'").fetchone()[0])
        learned = next((row for row in packed["inference_rules"]
                        if row["rule_id"] == "learned-parent-chain"), None)
        require(learned is not None
                and learned["validation"]["status"] == "validated"
                and len(learned["validation"]["positive_examples"]) == 2
                and len(learned["validation"]["training_positive_examples"]) == 2,
                "portable model lost the learned rule's validation provenance")
        require(any(case["conclusion"]["subject"] == "Nia"
                    and case["conclusion"]["relation"] == "ancestor"
                    and case["conclusion"]["object"] == "Pia"
                    and "learned-parent-chain" in case["lineage"]["rule_ids"]
                    for case in packed["derived_cases"]),
                "portable model lost the practiced proof lineage")

        installed = install_model_database(model_path, root / "installed")
        restored = CRMSKnowledgeBase.load(installed["knowledge"])
        restored_rule = next(row for row in restored.list_inference_rules()
                             if row["rule"]["rule_id"] == "learned-parent-chain")
        require(restored_rule["status"] == "validated"
                and restored_rule["validation"]["status"] == "validated",
                "installed model did not restore the validated rule state")
        result = restored.infer_relation("Nia", "ancestor", "Pia")
        require(result.status == "answered" and result.proofs
                and "learned-parent-chain" in json.dumps(result.proofs[0]),
                f"installed learned rule did not derive the new conclusion: {result}")
        require(restored.retrieve_derived_case(
            "Nia", "ancestor", "Pia", record_use=False) is not None,
            "installed model did not restore its verified derived case")

        packaged_index = CRMSSQLiteResearchIndex.load(installed["research_index"])
        source_hit = next((hit for hit in packaged_index.search(
            "Ada parent Bea", limit=5) if hit.document_id == "train:one"), None)
        require(source_hit is not None
                and "Ada is parent of Bea" in source_hit.snippet
                and packaged_index.resolve_citation(
                    packaged_index.citation(source_hit)) == source_hit.snippet,
                "installed model did not retain searchable, resolvable evidence")
        packaged_index.close()

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(model_path),
            "--dialogue-state", str(root / "dialogue.json"),
        ]
        runtime = subprocess.run(
            command,
            input="/inference-rules\n/infer-relation Nia|ancestor|Pia\n/quit\n",
            text=True, capture_output=True, check=True, cwd=root, timeout=30)
        require("learned-parent-chain [validated]" in runtime.stdout
                and "Nia — ancestor → Pia" in runtime.stdout
                and "rule learned-parent-chain" in runtime.stdout,
                f"portable chat failed to use the learned rule:\n{runtime.stdout}")

    print("held-out-validated inference rule survives portable SQLite packaging: PASS")
    print("new conclusion remains proof-backed and the practiced case retains lineage: PASS")
    print("embedded source text remains searchable with resolvable citations: PASS")
    print("interactive portable chat uses the installed learned rule: PASS")


if __name__ == "__main__":
    main()
