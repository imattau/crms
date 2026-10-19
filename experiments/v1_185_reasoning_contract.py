"""Cross-family runtime diagnostic for proof and abstention contracts."""

from __future__ import annotations

from dataclasses import asdict
import copy
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_inference import InferenceRule, infer_relation
from crms_proof import verify_fact_path
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    passed_families: list[str] = []
    kb = CRMSKnowledgeBase()
    kb.add_fact("A", "links", "B", "p1")
    kb.add_fact("B", "links", "C", "p2")
    kb.add_fact("B", "links", "D", "p3")

    # Direct path family: positive proofs, complete absence, and ambiguity.
    path = kb.ask_path("A", ["links"])
    require(path.status == "answered" and path.reason_code == "supported"
            and path.complete and path.proofs, "direct path answer contract failed")
    passed_families.append("direct paths")
    facts = [asdict(fact) for fact in kb.facts()]
    for proof in path.proofs or []:
        check = verify_fact_path(proof, facts, start="A", relations=["links"],
                                 answer=path.answer or "")
        require(check.valid, f"independent path checker rejected positive answer: {check}")
        forged = copy.deepcopy(proof)
        forged[-1]["object"] = "forged"
        require(not verify_fact_path(forged, facts, start="A", relations=["links"],
                                     answer=path.answer or "").valid,
                "path checker accepted a tampered proof")
    malformed_path = verify_fact_path([{"subject": "A"}], facts,
                                      start="A", relations=["links"],
                                      answer=path.answer or "")
    require(not malformed_path.valid, "path checker accepted a malformed proof")
    absent = kb.ask_path("missing", ["links"])
    require(absent.status == "unknown" and absent.complete
            and absent.reason_code == "no_path" and not absent.proofs,
            "direct path absence was not distinguished from incomplete search")
    multi = kb.ask_path("B", ["links"])
    require(multi.status == "ambiguous" and multi.complete
            and multi.reason_code == "multiple_answers", "multiple path answers were hidden")

    # Bounded fixed-endpoint path family.
    between = kb.ask_path_between("A", "C", ["links", "links"])
    require(between.status == "answered" and between.complete
            and between.reason_code == "supported" and between.proofs,
            "fixed-endpoint path did not return a proof-backed answer")
    for proof in between.proofs or []:
        check = verify_fact_path(proof, facts, start="A",
                                 relations=["links", "links"], answer="C")
        require(check.valid, f"independent checker rejected endpoint path: {check}")
    missing = kb.ask_path_between("A", "Z", ["links", "links"])
    require(missing.status == "unknown" and missing.complete
            and missing.reason_code == "no_path", "endpoint absence contract failed")
    limited = kb.ask_path_between("A", "C", ["links", "links"], max_expansions=1)
    require(limited.status == "unknown" and not limited.complete
            and limited.reason_code == "search_limit" and not limited.proofs
            and limited.expansions == 1,
            "path budget exhaustion leaked a partial answer")
    kb.add_negative_fact("B", "links", "C", "n1")
    conflict = kb.ask_path_between("A", "C", ["links", "links"])
    require(conflict.status == "ambiguous" and conflict.complete
            and conflict.reason_code == "contradiction",
            "path contradiction was resolved silently")

    # Explicit rule family, including limits, contradiction, and tampering.
    inferred = CRMSKnowledgeBase()
    inferred.add_fact("A", "parent", "B", "r1")
    inferred.add_fact("B", "parent", "C", "r2")
    rule = inferred.add_inference_rule("transitive", "parent", "parent", "ancestor")
    result = inferred.infer_relation("A", "ancestor", "C")
    require(result.status == "answered" and result.complete and result.proofs,
            "rule inference positive answer contract failed")
    with patch("crms_knowledge.verify_inference_proof") as checker:
        checker.return_value.valid = False
        checker.return_value.reason = "diagnostic rejection"
        rejected = inferred.infer_relation("A", "ancestor", "C")
    require(rejected.status == "unknown"
            and rejected.reason_code == "proof_rejected"
            and rejected.failure_kind == "proof_rejected",
            "independent proof rejection did not expose its structured failure kind")
    fact_rows = [asdict(fact) for fact in inferred.facts()]
    rule_rows = [asdict(rule)]
    for proof in result.proofs:
        check = verify_inference_proof(proof, fact_rows, rule_rows,
                                       expected_conclusion=result.conclusion)
        require(check.valid, f"independent rule checker rejected proof: {check}")
        forged = copy.deepcopy(proof)
        forged["conclusion"]["object"] = "forged"
        require(not verify_inference_proof(forged, fact_rows, rule_rows).valid,
                "rule checker accepted a tampered proof")
    malformed_rule = verify_inference_proof({}, fact_rows, rule_rows)
    require(not malformed_rule.valid, "rule checker accepted a malformed proof")
    no_proof = inferred.infer_relation("A", "ancestor", "unknown")
    require(no_proof.status == "unknown" and no_proof.complete
            and no_proof.reason_code == "no_proof"
            and no_proof.failure_kind == "missing_premise"
            and any(item.get("missing_premise", {}).get("subject") == "B"
                    and item.get("missing_premise", {}).get("object") == "unknown"
                    for item in no_proof.missing_premises)
            and "B — parent → unknown" in CRMSKnowledgeBase.render_inference(no_proof),
            "missing premise was not explained from the bounded search")
    exhausted = inferred.infer_relation("A", "ancestor", "C", max_expansions=1)
    require(exhausted.status == "unknown" and not exhausted.complete
            and exhausted.reason_code == "search_limit" and not exhausted.proofs,
            "rule search limit leaked a partial answer")
    inferred.add_negative_fact("A", "ancestor", "C", "negative")
    contested = inferred.infer_relation("A", "ancestor", "C")
    require(contested.status == "ambiguous" and contested.complete,
            "rule contradiction was resolved silently")
    passed_families.append("two-premise rules")

    # Explicitly declared transitivity schema is a distinct proof family.
    schema = CRMSKnowledgeBase()
    schema.add_fact("A", "precedes", "B", "s1")
    schema.add_fact("B", "precedes", "C", "s2")
    schema.add_relation_type("precedes", "transitive", "schema-source")
    schema_result = schema.infer_relation("A", "precedes", "C")
    schema_facts = [asdict(fact) for fact in schema.facts()]
    require(schema_result.status == "answered" and schema_result.complete
            and schema_result.proofs, "licensed schema answer contract failed")
    for proof in schema_result.proofs:
        check = verify_inference_proof(proof, schema_facts, [],
                                       expected_conclusion=schema_result.conclusion)
        require(check.valid, f"independent verifier rejected schema proof: {check}")
        forged = copy.deepcopy(proof)
        forged["schema"]["schema_id"] = "unvalidated-schema"
        require(not verify_inference_proof(forged, schema_facts, []).valid,
                "schema checker accepted a tampered proof")
    require(not verify_inference_proof({}, schema_facts, []).valid,
            "schema proof checker accepted a malformed proof")
    passed_families.append("typed transitivity schema")
    symmetric = CRMSKnowledgeBase()
    symmetric.add_fact("Ada", "collaborates with", "Bo", "sym-edge")
    symmetric.add_relation_type("collaborates with", "symmetric", "sym-schema")
    symmetric_result = symmetric.infer_relation(
        "Bo", "collaborates with", "Ada")
    symmetric_facts = [asdict(fact) for fact in symmetric.facts()]
    require(symmetric_result.status == "answered"
            and symmetric_result.complete and symmetric_result.proofs,
            "licensed symmetry schema did not prove its positive fixture")
    for proof in symmetric_result.proofs:
        check = verify_inference_proof(
            proof, symmetric_facts, [],
            expected_conclusion=symmetric_result.conclusion)
        require(check.valid,
                f"independent verifier rejected symmetric proof: {check}")
    passed_families.append("typed symmetry schema")
    irreflexive = CRMSKnowledgeBase()
    irreflexive.add_fact("Ann", "parent of", "Bob", "parent-ab")
    irreflexive.add_fact("Bob", "parent of", "Ann", "parent-ba")
    irreflexive.add_inference_rule(
        "parent-chain", "parent of", "parent of", "ancestor of")
    irreflexive.add_relation_type(
        "ancestor of", "irreflexive", "ancestor-schema")
    self_ancestor = irreflexive.infer_relation(
        "Ann", "ancestor of", "Ann")
    require(self_ancestor.status == "ambiguous"
            and self_ancestor.reason_code == "integrity_conflict"
            and "irreflexive" in (self_ancestor.request or "")
            and "ancestor-schema" in (self_ancestor.request or ""),
            f"irreflexive derived self-relation was not reported: {self_ancestor}")

    cyclic_support = CRMSKnowledgeBase()
    cyclic_support.add_fact("Ann", "parent of", "Bob", "parent-ab")
    cyclic_support.add_fact("Bob", "parent of", "Ann", "parent-ba")
    cyclic_support.add_inference_rule(
        "parent-chain", "parent of", "parent of", "grandparent of")
    self_grandparent = cyclic_support.infer_relation(
        "Ann", "grandparent of", "Ann")
    require(self_grandparent.status == "ambiguous"
            and self_grandparent.reason_code == "cyclic_support"
            and "cycle in the supporting facts" in (self_grandparent.request or ""),
            f"untyped cycle-backed self-relation was presented as certain: "
            f"{self_grandparent}")
    chat_self_grandparent = cyclic_support.ask(
        "Is Ann a grandparent of Ann?")
    require(chat_self_grandparent.status == "ambiguous"
            and chat_self_grandparent.reason_code == "cyclic_support"
            and "cycle in the supporting facts" in
            (chat_self_grandparent.request or ""),
            "natural-language yes/no routing hid the cyclic-support warning: "
            f"{chat_self_grandparent}")
    explicit_self_relation = CRMSKnowledgeBase()
    explicit_self_relation.add_fact("Ann", "knows", "Ann", "self-fact")
    explicit_self_answer = explicit_self_relation.infer_relation(
        "Ann", "knows", "Ann")
    require(explicit_self_answer.status == "answered",
            "cycle diagnostic changed an explicit self-relation into a warning")

    asymmetric = CRMSKnowledgeBase()
    for subject, obj in (("A", "B"), ("B", "C"),
                         ("C", "D"), ("D", "A")):
        asymmetric.add_fact(subject, "parent", obj, f"parent-{subject}-{obj}")
    asymmetric.add_inference_rule(
        "parent-chain", "parent", "parent", "ancestor")
    asymmetric.add_relation_type(
        "ancestor", "asymmetric", "ancestor-asymmetric-schema")
    reverse_ancestor = asymmetric.infer_relation("A", "ancestor", "C")
    require(reverse_ancestor.status == "ambiguous"
            and reverse_ancestor.reason_code == "integrity_conflict"
            and "asymmetric" in (reverse_ancestor.request or ""),
            f"asymmetric reverse derivation was not reported: {reverse_ancestor}")
    asymmetric_limited = asymmetric.infer_relation(
        "A", "ancestor", "C", max_expansions=2)
    require(asymmetric_limited.status == "unknown"
            and not asymmetric_limited.complete
            and asymmetric_limited.reason_code == "search_limit",
            f"incomplete asymmetric integrity check leaked a conclusion: {asymmetric_limited}")
    with tempfile.TemporaryDirectory(prefix="crms-integrity-schema-") as folder:
        saved = Path(folder) / "knowledge.json"
        asymmetric.save(saved)
        restored = CRMSKnowledgeBase.load(saved)
        persisted_check = restored.infer_relation("A", "ancestor", "C")
        require(persisted_check.status == "ambiguous"
                and persisted_check.reason_code == "integrity_conflict",
                "asymmetric integrity declaration did not survive persistence")

    framed = CRMSKnowledgeBase()
    for subject, obj in (("A", "B"), ("B", "C"),
                         ("C", "D"), ("D", "A")):
        framed.add_fact(subject, "parent", obj, f"frame-parent-{subject}-{obj}")
    framed.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    for endpoint, answer in (("C", "A"), ("D", "B")):
        framed.teach_question(
            f"Who is an ancestor of {endpoint}?", relation="ancestor",
            answer_field="subject", bound_entity=endpoint, answer=answer)
    framed.add_relation_type("ancestor", "asymmetric", "frame-asymmetric-schema")
    framed_answer = framed.ask("Who is an ancestor of C?")
    require(framed_answer.status == "ambiguous"
            and "integrity constraint" in (framed_answer.request or ""),
            f"natural-language inferred question hid the integrity conflict: {framed_answer}")
    passed_families.append(
        "cycle-backed self-relation warning, declared irreflexive/asymmetric "
        "constraints, bounds, persistence")

    functional = CRMSKnowledgeBase()
    functional.add_fact("Ann", "works for", "Acme", "job-acme")
    functional.add_fact("Ann", "works for", "Beta", "job-beta")
    functional.add_relation_type("works for", "functional", "employment-schema")
    conflicting_employer = functional.infer_relation("Ann", "works for", "Acme")
    require(conflicting_employer.status == "ambiguous"
            and conflicting_employer.reason_code == "integrity_conflict"
            and "functional" in (conflicting_employer.request or "")
            and "employment-schema" in (conflicting_employer.request or ""),
            f"functional relation conflict was not reported: {conflicting_employer}")
    functional_rule = CRMSKnowledgeBase()
    functional_rule.add_fact("Ann", "child of", "Bea", "child-bea")
    functional_rule.add_fact("Bea", "manages", "Acme", "manages-acme")
    functional_rule.add_fact("Bea", "manages", "Beta", "manages-beta")
    functional_rule.add_inference_rule(
        "parent-employer", "child of", "manages", "guardian employer")
    functional_rule.add_relation_type(
        "guardian employer", "functional", "guardian-employer-schema")
    derived_conflict = functional_rule.infer_relation(
        "Ann", "guardian employer", "Acme")
    require(derived_conflict.status == "ambiguous"
            and derived_conflict.reason_code == "integrity_conflict",
            f"functional constraint missed competing derived answers: {derived_conflict}")
    passed_families.append("functional integrity constraints over facts and derived answers")

    unlicensed = CRMSKnowledgeBase()
    unlicensed.add_fact("A", "precedes", "B", "s1")
    unlicensed.add_fact("B", "precedes", "C", "s2")
    no_schema = unlicensed.infer_relation("A", "precedes", "C")
    require(no_schema.status == "unknown" and no_schema.complete
            and no_schema.reason_code == "no_proof"
            and no_schema.failure_kind == "no_applicable_rule"
            and "No inference rule" in CRMSKnowledgeBase.render_inference(no_schema),
            "undeclared schema was treated as an inference")

    # Typed arity-three rule proofs must cite both kind facts and be independently
    # verified; malformed kind evidence must not be accepted by the checker.
    typed_facts = [
        {"subject": "A", "relation": "part", "object": "M1", "sources": ["t1"]},
        {"subject": "M1", "relation": "links", "object": "M2", "sources": ["t2"]},
        {"subject": "M2", "relation": "color", "object": "blue", "sources": ["t3"]},
        {"subject": "M1", "relation": "is-a", "object": "component", "sources": ["t4"]},
        {"subject": "M2", "relation": "is-a", "object": "material", "sources": ["t5"]},
    ]
    typed_rule = InferenceRule("typed-chain", "part", "links", "has-property",
                               third_relation="color", middle_kind="component",
                               second_middle_kind="material")
    typed = infer_relation(typed_facts, [typed_rule], subject="A",
                           relation="has-property", obj="blue")
    require(typed.status == "answered" and typed.proofs,
            "typed three-premise rule did not prove its positive fixture")
    typed_check = verify_inference_proof(
        typed.proofs[0], typed_facts, [asdict(typed_rule)],
        expected_conclusion=typed.conclusion)
    require(typed_check.valid, f"typed rule proof rejected: {typed_check}")
    malformed_typed = copy.deepcopy(typed.proofs[0])
    malformed_typed["middle_kind_facts"] = malformed_typed["middle_kind_facts"][:1]
    require(not verify_inference_proof(malformed_typed, typed_facts,
                                       [asdict(typed_rule)]).valid,
            "typed proof checker accepted incomplete kind evidence")
    typed_absent = infer_relation(
        typed_facts, [typed_rule], subject="A", relation="has-property",
        obj="green")
    require(typed_absent.status == "unknown" and typed_absent.complete
            and typed_absent.reason_code == "no_proof",
            "typed three-premise absence was not reported as complete")
    typed_limited = infer_relation(
        typed_facts, [typed_rule], subject="A", relation="has-property",
        obj="blue", max_expansions=1)
    require(typed_limited.status == "unknown" and not typed_limited.complete
            and typed_limited.reason_code == "search_limit"
            and not typed_limited.proofs,
            "typed three-premise search limit leaked a partial answer")
    typed_conflict = infer_relation(
        typed_facts, [typed_rule], subject="A", relation="has-property",
        obj="blue", negative_facts=[{
            "subject": "A", "relation": "has-property", "object": "blue",
            "sources": ["typed-negative"],
        }])
    require(typed_conflict.status == "ambiguous" and typed_conflict.complete
            and typed_conflict.reason_code == "contradiction",
            "typed three-premise contradiction was resolved silently")
    passed_families.append("typed three-premise rules")

    # Regression: a symmetric schema at depth one is reached from a rule premise.
    # It must propagate the depth limit to the outer search, not report complete
    # absence of proof (the prior local assignment shadowed `exhausted`).
    nested_facts = [
        {"subject": "A", "relation": "rel", "object": "B", "sources": ["edge"]},
        {"subject": "A", "relation": "next", "object": "C", "sources": ["next"]},
        {"subject": "rel", "relation": "has relation type", "object": "symmetric",
         "sources": ["schema"]},
    ]
    nested_rule = InferenceRule("join", "rel", "next", "goal")
    limited_symmetric = infer_relation(
        nested_facts, [nested_rule], subject="B", relation="goal", obj="C",
        max_depth=1)
    require(limited_symmetric.status == "unknown"
            and not limited_symmetric.complete
            and limited_symmetric.reason_code == "search_limit",
            f"symmetric depth exhaustion was misreported: {limited_symmetric}")
    passed_families.append("symmetric-schema depth exhaustion")

    print("reasoning contract by family:")
    for family in passed_families:
        print(f"  {family}: PASS")
    print("  path/rule/schema proof tampering and malformed-proof rejection: PASS")
    print("  complete absence, incomplete search, ambiguity, and contradiction: PASS")


if __name__ == "__main__":
    main()
