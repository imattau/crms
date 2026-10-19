"""Exercise indexed candidate generation for learned variable inference questions.

Run from the project root with:
    python3 experiments/v1_340_indexed_variable_inference.py
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase, SQLiteFactMap
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def build_kb() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    kb.add_inference_rule("grandparent", "parent", "parent", "grandparent")
    for subject, obj in (
            ("Ann", "Bob"), ("Bob", "Cara"),
            ("Dee", "Eli"), ("Eli", "Fay"),
            ("Gus", "Hal"), ("Hal", "Ivy")):
        kb.add_fact(subject, "parent", obj, f"family:{subject}-{obj}")
    kb.teach_question(
        "Who is a grandparent of Cara?", relation="grandparent",
        answer_field="subject", bound_entity="Cara", answer="Ann")
    kb.teach_question(
        "Who is a grandparent of Fay?", relation="grandparent",
        answer_field="subject", bound_entity="Fay", answer="Dee")
    kb.teach_question(
        "Which person is Ann the grandparent of?", relation="grandparent",
        answer_field="object", bound_entity="Ann", answer="Cara")
    kb.teach_question(
        "Which person is Dee the grandparent of?", relation="grandparent",
        answer_field="object", bound_entity="Dee", answer="Fay")
    for index in range(300):
        kb.add_fact(f"Unrelated{index}", "unrelated", f"Entity{index}",
                    f"noise:{index}")
    return kb


def check_answer(kb: CRMSKnowledgeBase, question: str, expected: str) -> None:
    result = kb.ask(question)
    require(result.status == "answered" and result.answer == expected,
            f"{question!r} should answer {expected!r}, got {result}")
    require(result.inference_proofs,
            f"{question!r} did not retain the inference proof")
    rules = [asdict(rule) for rule in kb._inference_rules.values()]
    for proof in result.inference_proofs:
        verified = verify_inference_proof(
            proof, kb.facts(), rules,
            expected_conclusion=proof["conclusion"],
            fact_lookup=kb._proof_fact_is_present)
        require(verified.valid,
                f"{question!r} returned an invalid proof: {verified.reason}")


def main() -> None:
    kb = build_kb()
    check_answer(kb, "Who is a grandparent of Ivy?", "Gus")
    check_answer(kb, "Which person is Gus the grandparent of?", "Ivy")

    missing = kb.ask("Who is a grandparent of Nobody?")
    require(missing.status == "unknown" and missing.request
            and "no matching fact" in missing.request.casefold(),
            f"an exhaustive indexed miss should be a complete unknown: {missing}")

    with tempfile.TemporaryDirectory(prefix="crms-indexed-variable-") as folder:
        database = Path(folder) / "knowledge.sqlite"
        kb.save(database)
        kb.close()
        restored = CRMSKnowledgeBase.load(database)
        require(isinstance(restored._facts, SQLiteFactMap),
                "roundtrip did not use the indexed SQLite fact map")
        check_answer(restored, "Who is a grandparent of Ivy?", "Gus")
        check_answer(restored, "Which person is Gus the grandparent of?", "Ivy")
        restored.close()

    recursive = CRMSKnowledgeBase()
    recursive.add_inference_rule(
        "ancestor-base", "parent", "parent", "ancestor")
    recursive.add_inference_rule(
        "ancestor-recursive", "parent", "ancestor", "ancestor")
    recursive.add_fact("TeachA", "parent", "TeachB", "frame:ab")
    recursive.add_fact("TeachB", "parent", "TeachC", "frame:bc")
    recursive.add_fact("TeachD", "parent", "TeachE", "frame:de")
    recursive.add_fact("TeachE", "parent", "TeachF", "frame:ef")
    recursive.teach_question(
        "Who is an ancestor of TeachC?", relation="ancestor",
        answer_field="subject", bound_entity="TeachC", answer="TeachA")
    recursive.teach_question(
        "Who is an ancestor of TeachF?", relation="ancestor",
        answer_field="subject", bound_entity="TeachF", answer="TeachD")
    chain = [f"Person{index}" for index in range(5)]
    for subject, obj in zip(chain, chain[1:]):
        recursive.add_fact(subject, "parent", obj,
                           f"family:{subject}-{obj}")
    for index in range(300):
        recursive.add_fact(f"Noise{index}", "unrelated", f"Other{index}",
                           f"noise:{index}")
    recursive_result = recursive.ask(
        "Who is an ancestor of Person4?")
    require(recursive_result.status == "ambiguous"
            and set(recursive_result.candidates or ())
            == {"Person0", "Person1", "Person2"}
            and recursive_result.inference_proofs
            and any("ancestor-recursive" in repr(proof)
                    for proof in recursive_result.inference_proofs),
            "indexed recursion should exhaustively return the three supported "
            f"ancestors with recursive proofs, got {recursive_result}")
    rule_rows = [asdict(rule) for rule in recursive._inference_rules.values()]
    for proof in recursive_result.inference_proofs:
        verified = verify_inference_proof(
            proof, recursive.facts(), rule_rows,
            expected_conclusion=proof["conclusion"],
            fact_lookup=recursive._proof_fact_is_present)
        require(verified.valid,
                f"recursive variable query returned an invalid proof: {verified.reason}")

    tree = CRMSKnowledgeBase()
    tree.add_inference_rule("ancestor-base", "parent", "parent", "ancestor")
    tree.add_inference_rule(
        "ancestor-recursive", "parent", "ancestor", "ancestor")
    tree.add_fact("TeachA", "parent", "TeachB", "tree-frame:ab")
    tree.add_fact("TeachB", "parent", "TeachC", "tree-frame:bc")
    tree.add_fact("TeachD", "parent", "TeachE", "tree-frame:de")
    tree.add_fact("TeachE", "parent", "TeachF", "tree-frame:ef")
    tree.teach_question(
        "Who is an ancestor of TeachC?", relation="ancestor",
        answer_field="subject", bound_entity="TeachC", answer="TeachA")
    tree.teach_question(
        "Who is an ancestor of TeachF?", relation="ancestor",
        answer_field="subject", bound_entity="TeachF", answer="TeachD")
    for node in range(1, 2047):
        tree.add_fact(f"Node{(node - 1) // 2}", "parent", f"Node{node}",
                      f"tree:{node}")
    leaf_ancestors = {f"Node{index}" for index in
                      (510, 254, 126, 62, 30, 14, 6, 2, 0)}
    tree_result = tree.ask("Who is an ancestor of Node2046?")
    require(tree_result.status == "ambiguous"
            and set(tree_result.candidates or ()) == leaf_ancestors
            and tree_result.inference_proofs,
            "indexed recursive reasoning missed ancestors in a 2,047-node "
            f"binary tree: {tree_result}")
    tree_rules = [asdict(rule) for rule in tree._inference_rules.values()]
    for proof in tree_result.inference_proofs:
        verified = verify_inference_proof(
            proof, tree.facts(), tree_rules,
            expected_conclusion=proof["conclusion"],
            fact_lookup=tree._proof_fact_is_present)
        require(verified.valid,
                f"binary-tree variable answer has invalid proof: {verified.reason}")

    scan_limited = CRMSKnowledgeBase()
    scan_limited.add_inference_rule(
        "grandparent", "parent", "parent", "grandparent")
    for subject, middle, obj in (("FrameA", "FrameB", "FrameC"),
                                 ("FrameD", "FrameE", "FrameF")):
        scan_limited.add_fact(subject, "parent", middle, f"frame:{subject}")
        scan_limited.add_fact(middle, "parent", obj, f"frame:{middle}")
    scan_limited.teach_question(
        "Who is a grandparent of FrameC?", relation="grandparent",
        answer_field="subject", bound_entity="FrameC", answer="FrameA")
    scan_limited.teach_question(
        "Who is a grandparent of FrameF?", relation="grandparent",
        answer_field="subject", bound_entity="FrameF", answer="FrameD")
    for index in range(10_005):
        scan_limited.add_fact(
            f"Qualified{index}", "parent", "CrowdedTarget", f"q:{index}")
    exhausted = scan_limited.ask(
        "Who is a grandparent of CrowdedTarget?")
    require(exhausted.status == "unknown" and exhausted.request
            and "bounded inference" in exhausted.request.casefold(),
            "fact-scan exhaustion must remain incomplete, got "
            f"{exhausted}")

    mutual = CRMSKnowledgeBase()
    mutual.add_inference_rule(
        "alpha-base", "parent", "parent", "alpha ancestor")
    mutual.add_inference_rule(
        "beta-from-alpha", "parent", "alpha ancestor", "beta ancestor")
    mutual.add_inference_rule(
        "alpha-from-beta", "parent", "beta ancestor", "alpha ancestor")
    for prefix, length in (("Short", 2), ("Long", 4), ("Beta", 3)):
        chain = [f"{prefix}{index}" for index in range(length + 1)]
        for subject, obj in zip(chain, chain[1:]):
            mutual.add_fact(subject, "parent", obj,
                            f"mutual:{subject}-{obj}")
    mutual.teach_question(
        "Who is an alpha ancestor of Short2?", relation="alpha ancestor",
        answer_field="subject", bound_entity="Short2", answer="Short0")
    mutual.teach_question(
        "Who is an alpha ancestor of Long4?", relation="alpha ancestor",
        answer_field="subject", bound_entity="Long4", answer="Long0")
    mutual.teach_question(
        "Which person is Short0 an alpha ancestor of?",
        relation="alpha ancestor", answer_field="object",
        bound_entity="Short0", answer="Short2")
    mutual.teach_question(
        "Which person is Long0 an alpha ancestor of?",
        relation="alpha ancestor", answer_field="object",
        bound_entity="Long0", answer="Long2")
    for index in range(300):
        mutual.add_fact(f"MutualNoise{index}", "unrelated",
                        f"MutualOther{index}", f"mutual-noise:{index}")
    mutual_result = mutual.ask("Who is an alpha ancestor of Long4?")
    require(mutual_result.status == "ambiguous"
            and set(mutual_result.candidates or ()) == {"Long0", "Long2"}
            and mutual_result.inference_proofs,
            "indexed variable inference should close mutually recursive alpha/beta "
            f"rules over more than 256 entities, got {mutual_result}")
    mutual_rules = [asdict(rule) for rule in mutual._inference_rules.values()]
    for proof in mutual_result.inference_proofs:
        verified = verify_inference_proof(
            proof, mutual.facts(), mutual_rules,
            expected_conclusion=proof["conclusion"],
            fact_lookup=mutual._proof_fact_is_present)
        require(verified.valid,
                f"mutually recursive variable answer has invalid proof: {verified.reason}")
    mutual_inverse = mutual.ask("Which person is Long0 an alpha ancestor of?")
    require(mutual_inverse.status == "ambiguous"
            and set(mutual_inverse.candidates or ()) == {"Long2", "Long4"}
            and mutual_inverse.inference_proofs,
            "inverse indexed variable inference should close mutually recursive "
            f"rules, got {mutual_inverse}")
    for proof in mutual_inverse.inference_proofs:
        verified = verify_inference_proof(
            proof, mutual.facts(), mutual_rules,
            expected_conclusion=proof["conclusion"],
            fact_lookup=mutual._proof_fact_is_present)
        require(verified.valid,
                f"inverse mutually recursive proof is invalid: {verified.reason}")
    with tempfile.TemporaryDirectory(prefix="crms-mutual-variable-") as folder:
        database = Path(folder) / "mutual.sqlite"
        mutual.save(database)
        mutual.close()
        mutual_restored = CRMSKnowledgeBase.load(database)
        mutual_sqlite_result = mutual_restored.ask(
            "Who is an alpha ancestor of Long4?")
        mutual_sqlite_inverse = mutual_restored.ask(
            "Which person is Long0 an alpha ancestor of?")
        require(mutual_sqlite_result.status == "ambiguous"
                and set(mutual_sqlite_result.candidates or ())
                == {"Long0", "Long2"}
                and mutual_sqlite_result.inference_proofs,
                "mutually recursive indexed answers did not survive SQLite backing: "
                f"{mutual_sqlite_result}")
        require(mutual_sqlite_inverse.status == "ambiguous"
                and set(mutual_sqlite_inverse.candidates or ())
                == {"Long2", "Long4"}
                and mutual_sqlite_inverse.inference_proofs,
                "inverse mutually recursive answers did not survive SQLite backing: "
                f"{mutual_sqlite_inverse}")
        mutual_sqlite_rules = [asdict(rule) for rule in
                               mutual_restored._inference_rules.values()]
        for result in (mutual_sqlite_result, mutual_sqlite_inverse):
            for proof in result.inference_proofs:
                verified = verify_inference_proof(
                    proof, mutual_restored.facts(), mutual_sqlite_rules,
                    expected_conclusion=proof["conclusion"],
                    fact_lookup=mutual_restored._proof_fact_is_present)
                require(verified.valid,
                        "SQLite mutual-recursion proof failed verification: "
                        f"{verified.reason}")
        mutual_restored.close()

    print("Indexed variable inference diagnostic: PASS")
    print("subject and object directions, recursive fixed-point proofs, exhaustive misses, "
          "mutual recursion, SQLite backing, and fact-scan exhaustion: PASS")


if __name__ == "__main__":
    main()
