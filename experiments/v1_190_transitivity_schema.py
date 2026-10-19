"""Check typed transitivity schema instantiation and proof validation."""

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


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for first, second, source in (
            ("A", "B", "edge:ab"), ("B", "C", "edge:bc"),
            ("C", "D", "edge:cd"), ("D", "E", "edge:de")):
        kb.add_fact(first, "precedes", second, source)
    kb.add_relation_type("precedes", "transitive", "schema:teacher")
    return kb


def main() -> None:
    kb = seed()
    result = kb.infer_relation("A", "precedes", "E")
    require(result.status == "answered" and result.complete and result.proofs,
            f"transitivity schema did not derive a held-out pair: {result}")
    require(any(proof.get("kind") == "schema" for proof in result.proofs),
            "proof did not record schema instantiation")
    facts = [asdict(fact) for fact in kb.facts()]
    for proof in result.proofs:
        checked = verify_inference_proof(proof, facts, [],
                                         expected_conclusion=result.conclusion)
        require(checked.valid, f"independent verifier rejected schema proof: {checked}")
    require("schema:teacher" in result.source_documents,
            "result omitted provenance for the explicit relation-type declaration")
    practiced = kb.practice_relation("A", "precedes", "E")
    reused = kb.infer_relation("A", "precedes", "E")
    derived_case = kb.retrieve_derived_case("A", "precedes", "E")
    require(practiced.status == "answered" and reused.status == "answered"
            and reused.expansions == 0 and derived_case is not None
            and "transitivity-v1" in derived_case["lineage"]["rule_ids"],
            "schema-backed practice or cached proof reuse lost its lineage")

    def tampered(field: str, value: object) -> dict:
        forged = copy.deepcopy(result.proofs[0])
        if field == "schema_id":
            forged["schema"]["schema_id"] = value
        elif field == "validation":
            forged["schema"]["validation"]["status"] = value
        elif field == "relation":
            forged["schema"]["relation"] = value
        else:
            forged["relation_type_fact"]["object"] = value
        return forged

    for field, value in (("schema_id", "unknown-schema"),
                         ("validation", "unvalidated"),
                         ("relation", "owns"),
                         ("type", "symmetric")):
        forged = tampered(field, value)
        check = verify_inference_proof(forged, facts, [])
        require(not check.valid, f"schema verifier accepted tampered {field}")

    untyped = CRMSKnowledgeBase()
    untyped.add_fact("A", "precedes", "B", "edge:ab")
    untyped.add_fact("B", "precedes", "C", "edge:bc")
    absent_schema = untyped.infer_relation("A", "precedes", "C")
    require(absent_schema.status == "unknown" and absent_schema.reason_code == "no_proof",
            "relation chains were generalized without an explicit type declaration")

    kb.add_negative_fact("precedes", "has relation type", "transitive", "schema:counter")
    conflict = kb.infer_relation("A", "precedes", "C")
    require(conflict.status == "ambiguous" and conflict.support_class == "contested",
            "conflicting relation-type evidence was silently resolved")

    contextual = CRMSKnowledgeBase()
    contextual.add_fact("X", "precedes", "Y", "context:xy",
                        qualifiers={"period": "day"})
    contextual.add_fact("Y", "precedes", "Z", "context:yz",
                        qualifiers={"period": "day"})
    contextual.add_relation_type("precedes", "transitive", "context:type",
                                 qualifiers={"period": "day"})
    scoped = contextual.infer_relation("X", "precedes", "Z",
                                       qualifiers={"period": "day"})
    wrong_scope = contextual.infer_relation("X", "precedes", "Z")
    require(scoped.status == "answered" and wrong_scope.status == "unknown",
            "schema declaration escaped its exact qualifier scope")

    # The general schema must flow through learned language frames.
    language = seed()
    if language.teach_polar_question(
            "Does A precede C?", subject="A", relation="precedes",
            obj="C", answer=True):
        raise SystemExit("one schema-backed example licensed a polar frame")
    if not language.teach_polar_question(
            "Does C precede E?", subject="C", relation="precedes",
            obj="E", answer=True):
        raise SystemExit("two schema-backed examples did not license the frame")
    answer = language.ask("Does A precede E?")
    require(answer.status == "answered" and answer.truth is True
            and answer.inference_proofs
            and "transitivity-v1" in language.render(answer),
            f"learned language frame did not expose schema-backed proof: {answer}")
    language.teach_fact_pattern(
        "A precedes B.", subject="A", relation="precedes", obj="B",
        source="edge:ab", predicate_phrase="precedes")
    language.teach_fact_pattern(
        "B precedes C.", subject="B", relation="precedes", obj="C",
        source="edge:bc", predicate_phrase="precedes")
    written = language.write_about("A")
    derived_statements = [statement for statement in written.statements
                          if statement.get("inferred")
                          and statement["fact"].get("object") == "E"]
    require(derived_statements
            and "transitivity-v1" in derived_statements[0]["rules"]
            and "schema:teacher" in derived_statements[0]["sources"],
            f"writing omitted schema-derived text or its proof sources: {written}")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        session_path = root / "rule-session.json"
        source_kb = seed()
        source_kb.save(knowledge_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        if restored.infer_relation("A", "precedes", "E").status != "answered":
            raise SystemExit("relation-type schema declaration did not persist")
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(state_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input=("/teach-relation-type arrives-before|transitive|cli:type\n"
                   "/infer-relation A|precedes|E\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        require("Stored relation type: arrives-before is transitive" in process.stdout,
                f"CLI did not expose typed schema declaration:\n{process.stdout}")
        require("A — precedes → E" in process.stdout
                and "precedes — has relation type → transitive" in process.stdout
                and "schema:teacher" in process.stdout,
                f"CLI omitted schema-backed inference evidence:\n{process.stdout}")

    print("typed transitivity schema diagnostic: PASS")
    print("explicit type gate, generalization, verifier metadata, provenance, contexts, QA, writing, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
