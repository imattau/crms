"""Phase 11: relation specs are governed rules.

Every accepted spec becomes a validated, active `fact-frame` rule; a contest or
retirement stops the engine using it; corrections past the reward rule contest a
spec; the registry round-trips through save and load.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import ListSentenceSource  # noqa: E402
from crms_relation_specs import RelationEngine  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402
from crms_spec_registry import (  # noqa: E402
    active_spec_names, record_spec_outcome, spec_rule_id, sync_spec_registry)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    SENTENCE = ("Lantern Bay", "Lantern Bay is a film directed by Rafe Ostin.")
    with PatternMemory(":memory:") as memory:
        memory.seed()
        engine = RelationEngine(memory.language(), memory.specs(),
                                ListSentenceSource([SENTENCE]), memory.params())
        registry = RuleRegistry()
        sync_spec_registry(memory, registry, engine)
        names = {s.name for s in memory.specs()}
        require(active_spec_names(registry) == names, "not every accepted spec became an active rule")
        record = registry.get(spec_rule_id("agent_transformed"))
        require(record.family == "fact-frame" and record.state == "active"
                and record.validation["passed"] and record.validation["oracle"] == "spec-verifier",
                f"spec rule not validated: {record.state} {record.validation}")
        require(record.validation["cases"] >= 5 and record.validation["independent_sources"] >= 3,
                "validation record is thin")

        # a second sync changes nothing
        before = {r.id: r.version for r in registry.records()}
        sync_spec_registry(memory, registry, engine)
        require({r.id: r.version for r in registry.records()} == before, "sync is not idempotent")

        engine.allowed = active_spec_names(registry)
        require(engine.ask("Who directed Lantern Bay?") is not None, "active spec did not answer")

        # a contest stops the spec; the question is no longer answered
        registry.contest(spec_rule_id("agent_transformed"), reason="reviewer hold")
        engine.allowed = active_spec_names(registry)
        require(engine.ask("Who directed Lantern Bay?") is None, "a contested spec still answered")
        sync_spec_registry(memory, registry, engine)       # restart must not clear the hold
        require(registry.get(spec_rule_id("agent_transformed")).state == "contested",
                "sync cleared a review hold")

        # reward rule: corrections that outnumber successes contest an active spec
        record_spec_outcome(registry, "named_after", success=True)
        for _ in range(3):
            record_spec_outcome(registry, "named_after", success=False)
        require(registry.get(spec_rule_id("named_after")).state == "contested",
                "repeated corrections did not contest the spec")
        require(record_spec_outcome(registry, "no_such_spec", success=True) is None, "unknown spec accepted")

        # retirement when a spec leaves the store
        memory.set_spec_status("population_of", "retired", "test")
        sync_spec_registry(memory, registry, engine)
        require(registry.get(spec_rule_id("population_of")).state == "retired",
                "a removed spec was not retired in the registry")

        # persistence
        path = Path(tempfile.mkdtemp(prefix="crms-specreg-")) / "registry.sqlite"
        registry.save(path)
        reloaded = RuleRegistry.load(path)
        require(reloaded.get(spec_rule_id("agent_transformed")).state == "contested"
                and reloaded.get(spec_rule_id("where_from")).state == "active",
                "registry state did not survive save/load")
    print("Phase 11 spec registry contract passed")


if __name__ == "__main__":
    main()
