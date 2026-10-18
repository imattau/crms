"""Check derived-case revalidation across source loss and alternate proofs."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def without_source(payload: dict, source: str) -> dict:
    """Return a serialized knowledge base with one citation removed."""
    for fact in payload["facts"]:
        fact["sources"] = [item for item in fact["sources"] if item != source]
    payload["facts"] = [fact for fact in payload["facts"] if fact["sources"]]
    return payload


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "parent", "Bea", "source:family-a")
    kb.add_fact("Bea", "parent", "Cal", "source:family-b")
    kb.add_fact("Ada", "mentor", "Bea", "source:work-a")
    kb.add_fact("Bea", "mentor", "Cal", "source:work-b")
    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    kb.add_inference_rule("mentor-chain", "mentor", "mentor", "ancestor")

    practiced = kb.practice_relation("Ada", "ancestor", "Cal")
    if practiced.status != "answered" or len(practiced.proofs) != 2:
        raise SystemExit("practice did not retain both independent proof paths")
    stored = kb.derived_cases()
    if len(stored) != 1 or stored[0]["status"] != "verified" or len(stored[0]["proofs"]) != 2:
        raise SystemExit("derived artifact did not retain both proof lineages")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        original = json.loads(path.read_text(encoding="utf-8"))

        # Remove one complete premise route. The independent alternate proof
        # should keep the artifact available with only its surviving lineage.
        one_route = without_source(json.loads(json.dumps(original)), "source:family-a")
        path.write_text(json.dumps(one_route), encoding="utf-8")
        surviving = CRMSKnowledgeBase.load(path)
        artifact = surviving.retrieve_derived_case("Ada", "ancestor", "Cal")
        if artifact is None or artifact["status"] != "verified" or len(artifact["proofs"]) != 1:
            raise SystemExit("artifact failed to survive loss of one alternate proof")

        # Remove a premise from each route. The recorded conclusion must not
        # remain retrievable merely because it was once practiced.
        no_routes = without_source(json.loads(json.dumps(original)), "source:family-a")
        no_routes = without_source(no_routes, "source:work-a")
        path.write_text(json.dumps(no_routes), encoding="utf-8")
        unsupported = CRMSKnowledgeBase.load(path)
        if unsupported.retrieve_derived_case("Ada", "ancestor", "Cal") is not None:
            raise SystemExit("artifact remained available after all proof lineages were lost")
        if unsupported.derived_cases()[0]["status"] != "stale_or_conflicted":
            raise SystemExit("unsupported artifact was not marked stale or conflicted")

        # Removing one rule has the same dependency behavior as removing a
        # source premise: the alternate rule remains sufficient.
        one_rule = json.loads(json.dumps(original))
        one_rule["inference_rules"] = [
            rule for rule in one_rule["inference_rules"]
            if rule["rule_id"] != "parent-chain"
        ]
        path.write_text(json.dumps(one_rule), encoding="utf-8")
        rule_survivor = CRMSKnowledgeBase.load(path)
        artifact = rule_survivor.retrieve_derived_case("Ada", "ancestor", "Cal")
        if artifact is None or len(artifact["proofs"]) != 1:
            raise SystemExit("artifact failed to survive removal of one alternate rule")

    print("derived lineage revalidation diagnostic: PASS")
    print("alternate proof survival, source invalidation, final-lineage abstention, rule invalidation: PASS")


if __name__ == "__main__":
    main()
