"""Unscoped schema and kind facts apply to scoped inference queries."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_inference import InferenceRule, infer_relation
from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    scoped_edges = [
        {"subject": "A", "relation": "part of", "object": "B",
         "sources": ["edge:ab"], "qualifiers": [("era", "2020")]},
        {"subject": "B", "relation": "part of", "object": "C",
         "sources": ["edge:bc"], "qualifiers": [("era", "2020")]},
    ]
    unscoped_schema = {"subject": "part of", "relation": "has relation type",
                       "object": "transitive", "sources": ["schema:part-of"],
                       "qualifiers": []}
    facts = scoped_edges + [unscoped_schema]
    result = infer_relation(
        facts, [], subject="A", relation="part of", obj="C",
        qualifiers={"era": "2020"})
    require(result.status == "answered" and result.proofs,
            f"unscoped transitivity schema did not apply in context: {result}")
    checked = verify_inference_proof(
        result.proofs[0], facts, [], expected_conclusion=result.conclusion,
        expected_qualifiers={"era": "2020"})
    require(checked.valid, f"verifier rejected unscoped schema proof: {checked}")

    mismatch = infer_relation(
        facts, [], subject="A", relation="part of", obj="C",
        qualifiers={"era": "2021"})
    unscoped_query = infer_relation(
        facts, [], subject="A", relation="part of", obj="C")
    require(mismatch.status == "unknown" and unscoped_query.status == "unknown",
            "scoped edges escaped their requested context")

    typed_facts = [
        {"subject": "A", "relation": "parent", "object": "M",
         "sources": ["edge:am"], "qualifiers": [("era", "2020")]},
        {"subject": "M", "relation": "parent", "object": "C",
         "sources": ["edge:mc"], "qualifiers": [("era", "2020")]},
        {"subject": "M", "relation": "is-a", "object": "person",
         "sources": ["type:person"], "qualifiers": []},
    ]
    rule = InferenceRule("typed-grandparent", "parent", "parent",
                         "grandparent", middle_kind="person")
    typed = infer_relation(
        typed_facts, [rule], subject="A", relation="grandparent", obj="C",
        qualifiers={"era": "2020"})
    require(typed.status == "answered" and typed.proofs,
            f"unscoped kind fact did not type scoped premises: {typed}")
    typed_check = verify_inference_proof(
        typed.proofs[0], typed_facts, [asdict(rule)],
        expected_conclusion=typed.conclusion, expected_qualifiers={"era": "2020"})
    require(typed_check.valid, f"verifier rejected unscoped kind proof: {typed_check}")

    with tempfile.TemporaryDirectory(prefix="crms-scope-subsumption-") as folder:
        path = Path(folder) / "knowledge.sqlite"
        kb = CRMSKnowledgeBase()
        kb.add_fact("A", "part of", "B", "edge:ab",
                    qualifiers={"era": "2020"})
        kb.add_fact("B", "part of", "C", "edge:bc",
                    qualifiers={"era": "2020"})
        kb.add_relation_type("part of", "transitive", "schema:part-of")
        kb.add_fact("A", "parent", "M", "edge:am",
                    qualifiers={"era": "2020"})
        kb.add_fact("M", "parent", "C", "edge:mc",
                    qualifiers={"era": "2020"})
        kb.add_fact("M", "is-a", "person", "type:person")
        kb.add_inference_rule("typed-grandparent", "parent", "parent",
                              "grandparent", middle_kind="person")
        kb.save(path)
        kb.close()

        restored = CRMSKnowledgeBase.load(path)
        sql_schema = restored.infer_relation(
            "A", "part of", "C", qualifiers={"era": "2020"})
        sql_kind = restored.infer_relation(
            "A", "grandparent", "C", qualifiers={"era": "2020"})
        sql_mismatch = restored.infer_relation(
            "A", "part of", "C", qualifiers={"era": "2021"})
        require(sql_schema.status == "answered" and sql_kind.status == "answered"
                and sql_mismatch.status == "unknown",
                "SQLite snapshot did not preserve schema-scope subsumption "
                f"or contextual isolation: schema={sql_schema.status}/"
                f"{sql_schema.reason_code}:{sql_schema.request}, kind={sql_kind.status}/"
                f"{sql_kind.reason_code}:{sql_kind.request}, mismatch={sql_mismatch.status}/"
                f"{sql_mismatch.reason_code}")
        restored.close()

    print("unscoped schema and kind facts support scoped in-memory and SQLite "
          "queries; scoped edges remain context-bound: PASS")


if __name__ == "__main__":
    main()
