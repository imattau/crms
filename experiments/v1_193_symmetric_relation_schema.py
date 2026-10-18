"""Check explicit symmetry schema proofs and their language/runtime path."""

from __future__ import annotations

from dataclasses import asdict
import copy
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    untyped = CRMSKnowledgeBase()
    untyped.add_fact("Bea", "collaborates with", "Ada", "edge:ba")
    require(untyped.infer_relation("Ada", "collaborates with", "Bea").status
            == "unknown",
            "reverse relation was inferred without an explicit symmetry declaration")

    kb = CRMSKnowledgeBase()
    kb.add_fact("Bea", "collaborates with", "Ada", "edge:ba")
    kb.add_relation_type("collaborates with", "symmetric", "schema:teacher")
    result = kb.infer_relation("Ada", "collaborates with", "Bea")
    require(result.status == "answered" and result.complete and result.proofs
            and all(proof.get("kind") == "schema"
                    and proof.get("schema", {}).get("schema_id") == "symmetry-v1"
                    for proof in result.proofs),
            f"explicit symmetry did not produce schema proofs: {result}")
    facts = [asdict(fact) for fact in kb.facts()]
    for proof in result.proofs:
        checked = verify_inference_proof(
            proof, facts, [], expected_conclusion=result.conclusion)
        require(checked.valid,
                f"independent checker rejected symmetric proof: {checked}")
        forged = copy.deepcopy(proof)
        forged["schema"]["schema_id"] = "unknown-schema"
        require(not verify_inference_proof(forged, facts, []).valid,
                "verifier accepted an altered symmetry schema identifier")
        forged = copy.deepcopy(proof)
        forged["premises"][0]["fact"]["subject"] = "Other"
        require(not verify_inference_proof(forged, facts, []).valid,
                "verifier accepted a premise that does not reverse the conclusion")
    require("schema:teacher" in result.source_documents,
            "schema declaration source is missing from inference provenance")
    composed = CRMSKnowledgeBase()
    composed.add_fact("Ada", "parent", "Bea", "edge:ab")
    composed.add_fact("Bea", "parent", "Cal", "edge:bc")
    composed.add_inference_rule(
        "parent-transitivity", "parent", "parent", "ancestor")
    composed.add_relation_type("ancestor", "symmetric", "schema:ancestor")
    composed_result = composed.infer_relation("Cal", "ancestor", "Ada")
    composed_facts = [asdict(fact) for fact in composed.facts()]
    require(composed_result.status == "answered"
            and composed_result.proofs
            and any(proof.get("kind") == "schema"
                    and proof.get("premises", [{}])[0].get("kind") == "rule"
                    for proof in composed_result.proofs),
            "symmetry did not reverse a rule-proved relation")
    for proof in composed_result.proofs:
        checked = verify_inference_proof(
            proof, composed_facts,
            [asdict(rule) for rule in composed._inference_rules.values()],
            expected_conclusion=composed_result.conclusion)
        require(checked.valid,
                f"independent checker rejected rule-backed symmetry: {checked}")
    shallow = composed.infer_relation(
        "Cal", "ancestor", "Ada", max_depth=1)
    require(shallow.status == "unknown" and not shallow.complete
            and shallow.reason_code == "search_limit",
            f"rule-backed symmetry escaped the depth bound: {shallow}")
    composed.add_negative_fact("Cal", "ancestor", "Ada", "negative:cal-ada")
    composed_conflict = composed.infer_relation("Cal", "ancestor", "Ada")
    require(composed_conflict.status == "ambiguous"
            and composed_conflict.proofs,
            "rule-backed symmetry hid explicit contradictory evidence")

    practiced = kb.practice_relation("Ada", "collaborates with", "Bea")
    reused = kb.infer_relation("Ada", "collaborates with", "Bea")
    derived = kb.retrieve_derived_case("Ada", "collaborates with", "Bea")
    require(practiced.status == "answered" and reused.status == "answered"
            and reused.expansions == 0 and derived is not None
            and "symmetry-v1" in derived["lineage"]["rule_ids"],
            "symmetric schema proof was not retained and revalidated as a derived case")

    conflicted = CRMSKnowledgeBase()
    conflicted.add_fact("Bea", "collaborates with", "Ada", "edge:ba")
    conflicted.add_relation_type("collaborates with", "symmetric", "schema:yes")
    conflicted.add_negative_fact("collaborates with", "has relation type",
                                 "symmetric", "schema:no")
    conflict = conflicted.infer_relation("Ada", "collaborates with", "Bea")
    require(conflict.status == "ambiguous" and conflict.support_class == "contested",
            "conflicting schema declaration was silently accepted")

    contextual = CRMSKnowledgeBase()
    contextual.add_fact("Yuki", "trusts", "Xan", "context:edge",
                        qualifiers={"period": "winter"})
    contextual.add_relation_type("trusts", "symmetric", "context:schema",
                                 qualifiers={"period": "winter"})
    scoped = contextual.infer_relation(
        "Xan", "trusts", "Yuki", qualifiers={"period": "winter"})
    unscoped = contextual.infer_relation("Xan", "trusts", "Yuki")
    require(scoped.status == "answered" and unscoped.status == "unknown",
            "symmetric schema escaped its exact qualifier scope")

    # A learned yes/no frame can consume the independently checked schema proof.
    language = CRMSKnowledgeBase()
    language.add_fact("Bea", "collaborates with", "Ada", "edge:ba")
    language.add_fact("Dee", "collaborates with", "Cal", "edge:dc")
    language.add_relation_type("collaborates with", "symmetric", "schema:teacher")
    first = language.teach_polar_question(
        "Does Ada collaborate with Bea?", subject="Ada",
        relation="collaborates with", obj="Bea", answer=True)
    second = language.teach_polar_question(
        "Does Cal collaborate with Dee?", subject="Cal",
        relation="collaborates with", obj="Dee", answer=True)
    require(not first and second,
            "two schema-backed examples did not license the polar question frame")
    answer = language.ask("Does Ada collaborate with Bea?")
    require(answer.status == "answered" and answer.truth is True
            and answer.inference_proofs
            and "symmetry-v1" in language.render(answer),
            f"learned language QA did not return the symmetry proof: {answer}")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "list-rules.json"
        session_path = root / "rule-session.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(state_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input=("/practice-inference Ada|collaborates with|Bea\n"
                   "/quit\n"), text=True, capture_output=True,
            check=False, timeout=30)
        require(process.returncode == 0
                and "Derived: Ada — collaborates with → Bea." in process.stdout
                and "symmetry-v1" in process.stdout
                and "Verified derivation stored as a separate derived case." in process.stdout,
                f"terminal schema inference failed:\n{process.stdout}\n{process.stderr}")
        persisted = CRMSKnowledgeBase.load(knowledge_path)
        restored = persisted.infer_relation("Ada", "collaborates with", "Bea")
        require(restored.status == "answered"
                and restored.expansions == 0
                and "symmetry-v1" in persisted.render_inference(restored),
                "symmetric relation declaration did not survive persistence")

    print("symmetric relation schema diagnostic: PASS")
    print("explicit license, direct/cached/rule-backed edges, independent proof "
          "validation, conflict/scope/limit handling, language QA, CLI, persistence: PASS")


if __name__ == "__main__":
    main()
