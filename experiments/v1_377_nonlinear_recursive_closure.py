"""Indexed proof construction for the nonlinear self-composition rule R,R -> R."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_chain(hops: int, *, typed: bool = False) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    kb.add_inference_rule("ancestor-base", "parent", "parent", "ancestor",
                          middle_kind="person" if typed else None)
    kb.add_inference_rule("ancestor-compose", "ancestor", "ancestor", "ancestor",
                          middle_kind="person" if typed else None)
    for index in range(hops + 1):
        if typed:
            kb.add_fact(f"N{index}", "is-a", "person", f"type:{index}")
        if index < hops:
            kb.add_fact(f"N{index}", "parent", f"N{index + 1}",
                        f"parent:{index}")
    return kb


def verify_result(kb: CRMSKnowledgeBase, result: object) -> None:
    facts = [asdict(fact) for fact in kb.facts()]
    rules = [asdict(rule) for rule in kb._inference_rules.values()]
    for proof in result.proofs or ():
        checked = verify_inference_proof(
            proof, facts, rules, expected_conclusion=result.conclusion)
        require(checked.valid,
                f"independent proof verifier rejected result: {checked}")


def main() -> None:
    measured_expansions = []
    direct_edges = CRMSKnowledgeBase()
    direct_edges.add_inference_rule(
        "relation-compose", "linked", "linked", "linked")
    for source, target in (("A", "B"), ("B", "C"), ("C", "D")):
        direct_edges.add_fact(source, "linked", target,
                              f"direct:{source}:{target}")
    direct_result = direct_edges.infer_relation("A", "linked", "D")
    require(direct_result.status == "answered" and direct_result.complete
            and direct_result.proofs,
            f"direct extensional self-composition failed: {direct_result}")
    verify_result(direct_edges, direct_result)

    for hops in (4, 8, 12):
        kb = make_chain(hops)
        result = kb.infer_relation("N0", "ancestor", f"N{hops}")
        require(result.status == "answered" and result.complete and result.proofs,
                f"nonlinear recursion failed on a {hops}-edge chain: {result}")
        require(result.expansions < 10_000,
                f"indexed closure still exhausted the old 10,000-expansion scale: {result}")
        measured_expansions.append((hops, result.expansions))
        verify_result(kb, result)
        if hops == 8:
            shallow = kb.infer_relation(
                "N0", "ancestor", "N8", max_depth=1)
            require(shallow.status == "unknown" and not shallow.complete
                    and shallow.limit_kind == "depth_limit",
                    f"a shallow depth limit was not preserved: {shallow}")
            bounded = kb.infer_relation(
                "N0", "ancestor", "N8", max_expansions=1)
            require(bounded.status == "unknown" and not bounded.complete
                    and bounded.limit_kind == "expansion_limit",
                    f"an expansion limit was not preserved: {bounded}")

    typed = make_chain(8, typed=True)
    typed_result = typed.infer_relation("N0", "ancestor", "N8")
    require(typed_result.status == "answered" and typed_result.proofs,
            f"typed nonlinear recursion failed: {typed_result}")
    verify_result(typed, typed_result)
    require(any("middle_kind_fact" in repr(proof)
                for proof in typed_result.proofs),
            "recursive proof omitted a required middle-entity type witness")

    disconnected = CRMSKnowledgeBase()
    disconnected.add_inference_rule(
        "ancestor-base", "parent", "parent", "ancestor")
    disconnected.add_inference_rule(
        "ancestor-compose", "ancestor", "ancestor", "ancestor")
    for source, target in (("A", "B"), ("B", "C"),
                          ("X", "Y"), ("Y", "Z")):
        disconnected.add_fact(source, "parent", target,
                              f"disconnected:{source}:{target}")
    no_path = disconnected.infer_relation("A", "ancestor", "Z")
    require(no_path.status == "unknown" and no_path.complete
            and no_path.reason_code == "no_proof",
            f"complete nonlinear miss was not an honest unknown: {no_path}")

    cyclic = CRMSKnowledgeBase()
    cyclic.add_inference_rule("ancestor-base", "parent", "parent", "ancestor")
    cyclic.add_inference_rule("ancestor-compose", "ancestor", "ancestor", "ancestor")
    cyclic.add_fact("A", "parent", "B", "cycle:ab")
    cyclic.add_fact("B", "parent", "A", "cycle:ba")
    self_relation = cyclic.infer_relation("A", "ancestor", "A")
    require(self_relation.status == "ambiguous"
            and self_relation.reason_code == "cyclic_support"
            and self_relation.proofs,
            f"nonlinear closure concealed cyclic self-support: {self_relation}")
    verify_result(cyclic, self_relation)

    with tempfile.TemporaryDirectory(prefix="crms-nonlinear-recursion-") as folder:
        database = Path(folder) / "knowledge.sqlite"
        disk_kb = make_chain(8, typed=True)
        disk_kb.save(database)
        disk_kb.close()
        restored = CRMSKnowledgeBase.load(database)
        disk_result = restored.infer_relation("N0", "ancestor", "N8")
        require(disk_result.status == "answered" and disk_result.complete,
                f"nonlinear recursive closure failed on SQLite: {disk_result}")
        verify_result(restored, disk_result)
        restored.close()

    print("nonlinear recursive ancestor closure on 4/8/12-edge chains: PASS "
          f"(expansions: {measured_expansions})")
    print("direct extensional self-composition seed edges: PASS")
    print("nested proofs independently verified, including typed middle witnesses: PASS")
    print("depth and expansion limits still abstain; disconnected closure is unknown: PASS")
    print("cyclic self-support remains ambiguous; SQLite roundtrip preserves proofs: PASS")


if __name__ == "__main__":
    main()
