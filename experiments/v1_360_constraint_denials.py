"""Constraint-backed denials cite verified schema and witness evidence."""

from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_constraint_denial


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "owns", "Engine", "source:ada-engine")
    kb.add_relation_type("owns", "functional", "schema:owns-functional")
    functional = kb.infer_relation("Ada", "owns", "Linux")
    require(functional.status == "denied"
            and functional.reason_code == "constraint_denial"
            and functional.constraint_denial is not None,
            f"functional constraint did not deny an alternative value: {functional}")
    require(functional.constraint_denial["witness"]["conclusion"] == {
        "subject": "Ada", "relation": "owns", "object": "Engine"},
        f"functional denial has the wrong witness: {functional.constraint_denial}")
    require("schema:owns-functional" in
            CRMSKnowledgeBase.render_inference(functional)
            and "source:ada-engine" in CRMSKnowledgeBase.render_inference(functional),
            "inference renderer omitted schema or witness provenance")
    kb.add_fact("Grace", "owns", "Plane", "source:grace-plane")
    kb.teach_polar_question(
        "Does Ada own Engine?", subject="Ada", relation="owns",
        obj="Engine", answer=True)
    require(kb.teach_polar_question(
        "Does Grace own Plane?", subject="Grace", relation="owns",
        obj="Plane", answer=True),
        "varied polar examples did not license the test frame")
    chat_no = kb.ask("Does Ada own Linux?")
    require(chat_no.status == "answered" and chat_no.truth is False
            and any(item.get("object") == "Engine" for item in chat_no.evidence or [])
            and any(item.get("object") == "functional" for item in chat_no.evidence or []),
            f"chat did not return a cited functional denial: {chat_no}")
    rendered_no = CRMSKnowledgeBase.render(chat_no)
    require("source:ada-engine" in rendered_no and "schema:owns-functional" in rendered_no,
            "chat rendering omitted the competing fact's citation")
    require("No" in rendered_no,
            "chat failed to surface the constraint denial as a negative answer")
    with tempfile.TemporaryDirectory(prefix="crms-constraint-denial-") as folder:
        root = Path(folder)
        memory = root / "knowledge.json"
        fact_db = root / "facts.sqlite"
        kb.save(memory)
        disk = CRMSKnowledgeBase.load(memory, fact_db=fact_db)
        disk_denial = disk.infer_relation("Ada", "owns", "Linux")
        require(disk_denial.status == "denied"
                and disk_denial.constraint_denial is not None,
                f"SQLite-backed constraint denial failed verification: {disk_denial}")
        disk.close()

    facts = [
        {"subject": "Ada", "relation": "owns", "object": "Engine",
         "sources": ["source:ada-engine"], "qualifiers": []},
        {"subject": "owns", "relation": "has relation type", "object": "functional",
         "sources": ["schema:owns-functional"], "qualifiers": []},
    ]
    good = verify_constraint_denial(
        functional.conclusion, functional.constraint_denial,
        expected_conclusion={"subject": "Ada", "relation": "owns", "object": "Linux"},
        complete=functional.complete, facts=facts)
    require(good.valid, f"independent verifier rejected a valid denial: {good}")
    incomplete = verify_constraint_denial(
        functional.conclusion, functional.constraint_denial,
        expected_conclusion=functional.conclusion, complete=False, facts=facts)
    require(not incomplete.valid, "constraint verifier accepted an incomplete search")
    positive_conflict = verify_constraint_denial(
        functional.conclusion, functional.constraint_denial,
        expected_conclusion=functional.conclusion, complete=True,
        proofs=[{"kind": "fact"}], facts=facts)
    require(not positive_conflict.valid,
            "constraint verifier accepted denial with positive proof support")
    tampered = copy.deepcopy(functional.constraint_denial)
    tampered["witness"]["conclusion"]["object"] = "Linux"
    rejected = verify_constraint_denial(
        functional.conclusion, tampered,
        expected_conclusion=functional.conclusion, complete=True, facts=facts)
    require(not rejected.valid, "constraint verifier accepted a tampered witness")

    # The witness can itself be a recombined rule proof, not only an explicit edge.
    family = CRMSKnowledgeBase()
    family.add_fact("Ann", "parent", "Bea", "source:ann-bea")
    family.add_fact("Bea", "parent", "Cara", "source:bea-cara")
    family.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    family.add_relation_type("ancestor", "functional", "schema:ancestor-functional")
    recombined = family.infer_relation("Ann", "ancestor", "Dan")
    require(recombined.status == "denied"
            and recombined.constraint_denial["witness"]["kind"] == "rule",
            f"rule-derived witness was not used for functional denial: {recombined}")
    require(verify_constraint_denial(
        recombined.conclusion, recombined.constraint_denial,
        expected_conclusion=recombined.conclusion,
        complete=recombined.complete, facts=[
            {"subject": f.subject, "relation": f.relation, "object": f.object,
             "sources": list(f.sources), "qualifiers": list(f.qualifiers)}
            for f in family.facts()],
        rules=[{"rule_id": "parent-chain", "first_relation": "parent",
                "second_relation": "parent", "third_relation": None,
                "conclusion_relation": "ancestor", "middle_kind": None,
                "second_middle_kind": None}]).valid,
        "independent verifier rejected a recombined witness")

    irreflexive = CRMSKnowledgeBase()
    irreflexive.add_relation_type("parent", "irreflexive", "schema:parent-irreflexive")
    self_query = irreflexive.infer_relation("Ann", "parent", "Ann")
    require(self_query.status == "denied"
            and self_query.constraint_denial["constraint"] == "irreflexive",
            f"irreflexive declaration did not refute a self-edge: {self_query}")

    asymmetric = CRMSKnowledgeBase()
    asymmetric.add_fact("Cara", "defeated", "Ann", "source:reverse-defeat")
    asymmetric.add_relation_type("defeated", "asymmetric", "schema:defeated-asymmetric")
    reverse = asymmetric.infer_relation("Ann", "defeated", "Cara")
    require(reverse.status == "denied"
            and reverse.constraint_denial["constraint"] == "asymmetric",
            f"asymmetry did not refute a reversed edge: {reverse}")

    conflict = CRMSKnowledgeBase()
    conflict.add_fact("Ada", "owns", "Engine", "source:engine")
    conflict.add_fact("Ada", "owns", "Linux", "source:linux")
    conflict.add_relation_type("owns", "functional", "schema:functional")
    contested = conflict.infer_relation("Ada", "owns", "Linux")
    require(contested.status == "ambiguous"
            and contested.reason_code == "integrity_conflict",
            f"constraint conflict was collapsed into a denial: {contested}")

    scoped = CRMSKnowledgeBase()
    scoped.add_fact("Ada", "owns", "Engine", "source:old-engine",
                    qualifiers={"era": "old"})
    scoped.add_relation_type("owns", "functional", "schema:owns-functional")
    require(scoped.infer_relation("Ada", "owns", "Linux",
                                  qualifiers={"era": "new"}).status == "unknown",
            "a scoped witness escaped its requested context")

    print("functional, asymmetric, and irreflexive denials: PASS")
    print("direct and recombined witness verification, tamper rejection, citations, scope: PASS")


if __name__ == "__main__":
    main()
