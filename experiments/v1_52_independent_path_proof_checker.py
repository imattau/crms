"""Validate CRMS path proofs with a checker separate from query code.

Run from the project root with:
    python3 experiments/v1_52_independent_path_proof_checker.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_proof import verify_fact_path


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada Lovelace", "designed", "Engine", "source:design",
                qualifiers={"period": "1840s"})
    kb.add_fact("Engine", "used", "Steam", "source:steam",
                qualifiers={"period": "1840s"})
    kb.add_fact("Engine", "used", "Electricity", "source:electric",
                qualifiers={"period": "1840s"})

    facts = [fact.__dict__ for fact in kb.facts()]
    result = kb.ask_path("Ada Lovelace", ["designed", "used"],
                         qualifiers={"period": "1840s"})
    if result.status != "ambiguous" or len(result.proofs or []) != 2:
        raise SystemExit(f"expected two supported paths: {result}")
    for proof in result.proofs or []:
        endpoint = proof[-1]["object"]
        checked = verify_fact_path(
            proof, facts, start="Ada Lovelace",
            relations=["designed", "used"], answer=endpoint,
            qualifiers={"period": "1840s"})
        if not checked.valid:
            raise SystemExit(f"valid query proof rejected: {checked}")

    valid = result.proofs[0]
    mutations = []
    wrong_edge = copy.deepcopy(valid)
    wrong_edge[1]["subject"] = "Unrelated"
    mutations.append((wrong_edge, "path discontinuity"))
    wrong_relation = copy.deepcopy(valid)
    wrong_relation[1]["relation"] = "invented"
    mutations.append((wrong_relation, "wrong relation"))
    forged_source = copy.deepcopy(valid)
    forged_source[0]["sources"] = ["source:forged"]
    mutations.append((forged_source, "forged provenance"))
    missing_context = copy.deepcopy(valid)
    missing_context[0]["qualifiers"] = []
    mutations.append((missing_context, "missing requested context"))
    for proof, label in mutations:
        checked = verify_fact_path(
            proof, facts, start="Ada Lovelace",
            relations=["designed", "used"], answer=valid[-1]["object"],
            qualifiers={"period": "1840s"})
        if checked.valid:
            raise SystemExit(f"checker accepted {label}")

    incomplete = verify_fact_path(
        valid[:1], facts, start="Ada Lovelace",
        relations=["designed", "used"], answer=valid[-1]["object"])
    wrong_start = verify_fact_path(
        valid, facts, start="Grace Hopper",
        relations=["designed", "used"], answer=valid[-1]["object"])
    if incomplete.valid or wrong_start.valid:
        raise SystemExit("checker accepted an incomplete proof or wrong start")

    unknown = kb.ask_path("Unknown Person", ["designed", "used"])
    if unknown.status != "unknown" or unknown.proofs:
        raise SystemExit(f"unsupported path did not abstain without proof: {unknown}")
    print("independent path proof checker: PASS")
    print("valid paths, ambiguity, edge continuity, relation order, provenance, qualifiers, abstention: PASS")


if __name__ == "__main__":
    main()
