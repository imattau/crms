"""Relation specs as governed rules (Phase 11).

Each accepted relation spec is mirrored into the rule registry as a `fact-frame`
rule with a validation record produced by the deterministic spec verifier, so it
shares lifecycle, utility counts, contest, retire, and rollback with every other
rule family. A contested or retired rule stops the engine from using its spec.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from crms_pattern_memory import PatternMemory
from crms_relation_specs import RelationEngine, RelationSpec
from crms_rule_registry import RuleRecord, RuleRegistry
from crms_spec_verifier import verify_spec

SPEC_FAMILY = "fact-frame"
SPEC_ORACLE = "spec-verifier"      # deterministic checks, independent of the proposer
SPEC_ORIGIN = "relation-spec"

_RANDOM_SENTENCES = (
    "Paris is the capital of France.", "The river flows through three countries.",
    "Mount Everest is 8849 metres tall.", "Linus Torvalds developed Linux in 1991.",
    "Water boils at 100 degrees Celsius at sea level.", "Marie Curie won two Nobel Prizes.",
) * 30


def spec_rule_id(name: str) -> str:
    return f"relation-spec:{name}"


def _proposal(spec: RelationSpec, evidence: Mapping[str, Any]) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "name": spec.name, "priority": spec.priority,
        "question_patterns": list(spec.question_patterns),
        "sentence_patterns": list(spec.sentence_patterns),
        "template": spec.template, "verb_class": spec.verb_class,
        "support": list(evidence.get("support", ())),
        "heldout": list(evidence.get("heldout", ())),
        "contrast": list(evidence.get("contrast", ())),
        "grandfathered": bool(evidence.get("grandfathered")),
    }
    if "base" in evidence:
        proposal["base"] = evidence["base"]
        proposal["transforms"] = list(evidence.get("transforms", ()))
    return proposal


def replay_spec(spec: RelationSpec, evidence: Mapping[str, Any],
                engine: RelationEngine) -> tuple[bool, str, int, int]:
    """(passed, detail, cases, independent source sentences)."""
    proposal = _proposal(spec, evidence)
    result = verify_spec(proposal, engine, corpus_sentences=_RANDOM_SENTENCES)
    cases = len(proposal["support"]) + len(proposal["heldout"]) + len(proposal["contrast"])
    sentences = {item["S"] for item in proposal["support"] + proposal["heldout"] if "S" in item}
    detail = ("verifier passed: " if result.ok else "verifier failed: ") + (
        ", ".join(f"{k}={v}" for k, v in result.metrics.items() if not isinstance(v, dict))
        or "no metrics") + ("" if result.ok else " | " + "; ".join(result.reasons)[:300])
    return result.ok, detail, cases, len(sentences)


def register_spec_rule(spec: RelationSpec, evidence: Mapping[str, Any],
                       registry: RuleRegistry, engine: RelationEngine) -> RuleRecord:
    """Propose, validate, and activate the rule for one accepted spec."""
    rule_id = spec_rule_id(spec.name)
    payload = {"origin": SPEC_ORIGIN, "name": spec.name, "priority": spec.priority,
               "question_patterns": list(spec.question_patterns),
               "sentence_patterns": list(spec.sentence_patterns), "template": spec.template,
               "verb_class": spec.verb_class}
    passed, detail, cases, sources = replay_spec(spec, evidence, engine)
    provenance = [{"kind": "spec-evidence", "sentence": item.get("S", ""), "question": item.get("q", "")}
                  for item in list(evidence.get("support", ())) + list(evidence.get("heldout", ()))]
    statement = f"relation spec {spec.name}: {spec.rationale or spec.template}"
    existing = registry.get(rule_id) if rule_id in registry else None
    if existing is None:
        registry.propose(rule_id=rule_id, family=SPEC_FAMILY, statement=statement,
                         scope=f"relation questions; spec {spec.name}", payload=payload,
                         provenance=provenance, trust="taught")
    else:
        if existing.state == "retired":
            return existing
        if existing.state == "contested":
            return existing   # a contest is a review hold; do not reactivate on startup
        unchanged = (existing.payload == payload and existing.state == "active")
        if unchanged:
            return existing
        registry.revise(rule_id, statement=statement, payload=payload, provenance=provenance)
    registry.validate(rule_id, oracle=SPEC_ORACLE, passed=passed, cases=cases,
                      independent_sources=sources, detail=detail)
    record = registry.get(rule_id)
    if passed and record.state in {"proposed", "validated"}:
        registry.activate(rule_id, mode="review", authoriser="seed-file")
    return registry.get(rule_id)


def sync_spec_registry(memory: PatternMemory, registry: RuleRegistry,
                       engine: RelationEngine) -> None:
    """Mirror accepted specs into the registry and retire records of specs that are gone."""
    accepted = {s.name: s for s in memory.specs()}
    for name, spec in accepted.items():
        register_spec_rule(spec, memory.spec_evidence(name), registry, engine)
    for record in registry.records(family=SPEC_FAMILY):
        if record.state == "retired" or record.payload.get("origin") != SPEC_ORIGIN:
            continue
        if record.payload.get("name") not in accepted:
            registry.retire(record.id, reason="relation spec is no longer accepted")


def active_spec_names(registry: RuleRegistry) -> set[str]:
    return {r.payload["name"] for r in registry.records(family=SPEC_FAMILY, state="active")
            if r.payload.get("origin") == SPEC_ORIGIN}


def record_spec_outcome(registry: RuleRegistry, spec_name: str, *, success: bool,
                        min_uses: int = 3) -> RuleRecord | None:
    """Count a use; contest the rule when corrections outnumber successes
    (a wrong answer costs more than an abstention, so the spec is held for review)."""
    rule_id = spec_rule_id(spec_name)
    if rule_id not in registry:
        return None
    record = registry.record_use(rule_id, success=success)
    util = record.utility
    if (record.state == "active" and util["applications"] >= min_uses
            and util["corrections"] > util["successes"]):
        registry.contest(rule_id, reason="corrections outnumber successes")
    return registry.get(rule_id)
