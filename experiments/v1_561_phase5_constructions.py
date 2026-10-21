"""Phase 5 contract: learned constructions, paraphrase breadth, and retirement."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_constructions import (  # noqa: E402
    ClassPart, ConstructionExample, ConstructionGrammar, ConstructionStore,
    register_construction_rule,
)
from crms_construction_ranker import ConstructionRanker  # noqa: E402
from crms_morphology import Morphology  # noqa: E402
from crms_phase5_benchmark import (  # noqa: E402
    active_learning_lane, load_constructions, new_construction_lane,
)
from crms_rule_registry import RuleRegistry  # noqa: E402
from run_phase5_eval import evaluate  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def module_contracts() -> None:
    store = ConstructionStore()
    for index, text in enumerate((
            "sum every value {claim:claim:Mira reaches} in "
            "{values:values:3, 8}",
            "total each number {claim:claim:Nia can reach} from "
            "{values:values:5, 13}")):
        store.add_example(ConstructionExample(
            text, "direct-sum", f"test:train:{index}", operation="sum",
            name="Direct sum", composition="direct"))
    rule = store.rule("direct-sum")
    require(rule is not None, "two aligned examples did not license a construction")
    require(any(isinstance(part, ClassPart)
                for pattern in rule.patterns for part in pattern.parts),
            "induction produced no token class")
    grammar = ConstructionGrammar(store)
    match = grammar.match("total each number Mira reaches from 3, 8")
    require(match.status == "matched" and match.match is not None,
            f"learned class did not generalise: {match.status}")
    require(match.match.slots["values"] == (3, 8),
            "construction slot binding is wrong")

    with tempfile.TemporaryDirectory(prefix="crms-phase5-") as folder:
        root = Path(folder)
        store.save(root / "constructions.json")
        loaded = ConstructionStore.load(root / "constructions.json")
        require(ConstructionGrammar(loaded).match(
            "sum every value Mira reaches in 3, 8").status == "matched",
            "construction store did not survive reload")

    registry = RuleRegistry()
    record = register_construction_rule(rule, registry)
    require(record.state == "active", "licensed construction did not activate")
    governed = ConstructionGrammar(store, registry=registry)
    require(governed.match("sum every value Mira reaches in 3, 8").status
            == "matched", "governed construction is not executable")
    registry.retire(record.id, reason="test")
    retired = ConstructionGrammar(store, registry=registry)
    require(retired.match("sum every value Mira reaches in 3, 8").status
            == "no_match" and not retired.dangling_references(),
            "retired construction is still executable or dangling")
    registry.rollback(record.id)
    require(ConstructionGrammar(store, registry=registry).match(
        "sum every value Mira reaches in 3, 8").status == "matched",
        "rollback did not restore the construction")

    morphology = Morphology.default()
    require(morphology.matches("entry", "entries")
            and not morphology.matches("child", "children"),
            "regular/irregular morphology boundary is wrong")
    morphology.add_irregular("child", "children", rule_id="child",
                             source="test")
    require(morphology.matches("child", "children"),
            "observed irregular evidence was not usable")

    ranker = ConstructionRanker(max_candidates=1, max_features=3)
    proposals = ranker.propose(match.matches)
    require(len(proposals) == 1 and len(proposals[0].features) <= 3,
            "ranker exceeded its size budget")

    active = active_learning_lane()
    require(active["questions_asked"] == 1
            and "enumerate" in active["missing"]
            and active["matched_after"] == "matched",
            f"active construction learning did not close the gap: {active}")

    new = new_construction_lane()
    require(new["matched_before"] == "matched"
            and new["matched_after_retire"] == "no_match"
            and not new["dangling_references"]
            and new["matched_after_rollback"] == "matched",
            "new construction did not enter/retire/rollback cleanly")


def main() -> None:
    module_contracts()
    report = evaluate()
    require(report["gate_passed"], f"Phase 5 gate failed: {report['gate']}")
    require(report["corpus"]["constructions"] == 10
            and report["corpus"]["heldout_tasks"] == 200,
            "Phase 5 suite size is wrong")
    require(report["baseline"]["correct"] == 60
            and report["learned"]["correct"] == 200,
            f"unexpected baseline/learned counts: "
            f"{report['baseline']['correct']} / {report['learned']['correct']}")
    require(report["learned"]["coverage"]
            >= 2 * report["baseline"]["coverage"],
            "learned coverage did not double the exact-frame baseline")
    require(report["learned"]["confident_errors"] == 0
            and report["baseline"]["confident_errors"] == 0,
            "a construction route produced a confident wrong answer")
    require(report["control_and_reworded"]["baseline"]["reworded"]["correct"]
            == 0
            and report["control_and_reworded"]["learned"]["reworded"]["correct"]
            == 140,
            "reworded paraphrase split is wrong")
    require(report["abstention"]["all_abstain"],
            "an unlicensed or ambiguous production did not abstain")
    require(report["registry"]["all_active_have_holdout_evidence"],
            "an active construction lacks holdout evidence")
    require(report["morphology"]["registry_regular_active"]
            and report["morphology"]["irregular_after_evidence"],
            "morphology lane failed")
    require(report["ranker"]["bypass_same"]
            and report["ranker"]["candidate_count"]
            <= report["ranker"]["max_candidates"],
            "propose-only ranker changed the decision")
    require(report["context"]["matched"]
            and report["context"]["context_sensitive"],
            "same utterance did not respect different contexts")
    print("token classes, typed slots, and composition patterns: PASS")
    print("200 held-out paraphrases: learned 200/200, exact frames 60/200: PASS")
    print("controls 60/60, reworded 140/140, zero wrong answers: PASS")
    print("unlicensed/ambiguous abstention and morphology boundary: PASS")
    print("registry entry, retirement, rollback, and no dangling references: PASS")
    print("active construction learning and propose-only ranker: PASS")
    print("Phase 5 gate: PASS")


if __name__ == "__main__":
    main()
