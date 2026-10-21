"""Frozen Phase 5 paraphrase and construction-learning benchmark.

Ten construction shapes are induced from teacher-marked examples. A hand-coded
exact-frame baseline is licensed from the same examples. Both systems are scored
on 200 held-out requests by an independent operation oracle: 60 controls reuse a
training wording with new fillers, and 140 recombine learned token-class
alternatives. No answer is counted correct because a system produced it.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from crms_constructions import (
    ConstructionExample, ConstructionGrammar, ConstructionRule,
    ConstructionStore, HoldoutEvidence, construction_rule_id,
    match_constructions, register_construction_rule,
)
from crms_request_frames import FrameExample, RequestFrameStore

PROJECT = Path(__file__).resolve().parent
PHASE5_FIXTURE = PROJECT / "experiments" / "scorecard" / "phase5_constructions.json"
BASELINE_GOAL = "select-then-procedure"


def load_constructions(path: str | Path = PHASE5_FIXTURE) -> dict[str, Any]:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if raw.get("format") != "crms-phase5-constructions":
        raise ValueError("not a Phase 5 construction fixture")
    if len(raw.get("specs", ())) != 10:
        raise ValueError("Phase 5 needs exactly ten constructions")
    if len(raw.get("heldout", ())) != 200:
        raise ValueError("Phase 5 needs exactly 200 held-out tasks")
    operations = {spec["operation"] for spec in raw["specs"]}
    if not operations:
        raise ValueError("Phase 5 needs construction operations")
    by_id = {spec["id"]: spec["operation"] for spec in raw["specs"]}
    for task in raw["heldout"]:
        operation = by_id.get(task["construction_id"])
        if operation is None:
            raise ValueError("held-out task has an unknown construction")
        expected = apply_operation(
            operation, selected_values(task["values"], raw))
        if expected != list(task["expected"]):
            raise ValueError(
                f"fixture oracle disagrees for {task['source_id']}")
    return raw


def selected_values(values: Iterable[int], data: Mapping[str, Any]) -> list[int]:
    positive = {int(value) for value in data["selection"]["positive"]}
    negative = {int(value) for value in data["selection"]["negative"]}
    return [int(value) for value in values
            if int(value) in positive and int(value) not in negative]


def apply_operation(operation: str, values: Iterable[int]) -> list[int]:
    rows = list(values)
    if operation == "sum":
        return [sum(rows)]
    if operation == "double":
        return [value * 2 for value in rows]
    if operation == "reverse":
        return list(reversed(rows))
    if operation == "dedupe":
        seen: set[int] = set()
        result = []
        for value in rows:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result
    if operation == "keep_odd":
        return [value for value in rows if value % 2]
    if operation == "count":
        return [len(rows)]
    if operation == "sort":
        return sorted(rows)
    if operation == "product":
        return [math.prod(rows)]
    if operation == "max":
        return [max(rows)]
    if operation == "min":
        return [min(rows)]
    raise ValueError(f"unknown Phase 5 operation: {operation!r}")


def _expected(task: Mapping[str, Any], data: Mapping[str, Any],
              operation: str) -> list[int]:
    return apply_operation(
        operation, selected_values(task["values"], data))


def construction_store(data: Mapping[str, Any]) -> ConstructionStore:
    return ConstructionStore([
        ConstructionExample.from_dict(row) for row in data["training"]
    ])


def baseline_frames(data: Mapping[str, Any]) -> RequestFrameStore:
    store = RequestFrameStore()
    for row in data["training"]:
        text = str(row["text"])
        text = re.sub(r"\{values:values:", "{values:integer-list:", text)
        text = re.sub(
            r"\{(condition|manner):\1:", r"{\1:text:", text)
        store.examples.append(FrameExample(
            text=text, goal=BASELINE_GOAL, source_id=row["source_id"],
            fixed_procedure=row["operation"]))
    return store


@dataclass(frozen=True)
class Outcome:
    status: str
    output: list[int] | None
    expected: list[int]
    construction_id: str
    operation: str = ""
    detail: str = ""

    @property
    def correct(self) -> bool:
        return self.status == "answered" and self.output == self.expected

    @property
    def confident_error(self) -> bool:
        return self.status == "confident_error"

    @property
    def abstained(self) -> bool:
        return self.status in {"no_match", "ambiguous", "abstained"}


def operation_for(task: Mapping[str, Any], data: Mapping[str, Any]) -> str:
    spec = next(spec for spec in data["specs"]
                if spec["id"] == task["construction_id"])
    return str(spec["operation"])


def solve_task(grammar: ConstructionGrammar, task: Mapping[str, Any],
               data: Mapping[str, Any], *, record_use: bool = False) -> Outcome:
    expected = _expected(task, data, operation_for(task, data))
    result = grammar.match(str(task["text"]))
    if result.status == "ambiguous":
        return Outcome("ambiguous", None, expected,
                       str(task["construction_id"]),
                       detail="; ".join(
                           match.rule.construction_id
                           for match in result.matches[:4]))
    if result.status != "matched" or result.match is None:
        return Outcome("no_match", None, expected,
                       str(task["construction_id"]), detail=result.reason)
    match = result.match
    output = apply_operation(
        match.rule.operation,
        selected_values(task["values"], data))
    if record_use:
        grammar.record_use(match, success=output == expected)
    if output != expected:
        return Outcome("confident_error", output, expected,
                       match.rule.construction_id, match.rule.operation,
                       "independent oracle disagreed")
    return Outcome("answered", output, expected,
                   match.rule.construction_id, match.rule.operation)


def solve_baseline(store: RequestFrameStore, task: Mapping[str, Any],
                   data: Mapping[str, Any]) -> Outcome:
    expected = _expected(task, data, operation_for(task, data))
    result = store.match(str(task["text"]))
    if result.status == "ambiguous":
        return Outcome("ambiguous", None, expected,
                       str(task["construction_id"]),
                       detail="more than one exact frame")
    if result.status != "matched" or result.match is None:
        return Outcome("no_match", None, expected,
                       str(task["construction_id"]), detail=result.reason)
    operation = result.match.frame.fixed_procedure or ""
    output = apply_operation(
        operation, selected_values(task["values"], data))
    if output != expected:
        return Outcome("confident_error", output, expected,
                       str(task["construction_id"]), operation,
                       "exact frame selected the wrong operation")
    return Outcome("answered", output, expected,
                   str(task["construction_id"]), operation)


def summarize(outcomes: Iterable[Outcome]) -> dict[str, Any]:
    rows = list(outcomes)
    answered = [row for row in rows if row.status == "answered"]
    errors = [row for row in rows if row.status == "confident_error"]
    ambiguous = [row for row in rows if row.status == "ambiguous"]
    by_construction: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_construction.setdefault(
            row.construction_id,
            {"tasks": 0, "answered": 0, "correct": 0,
             "confident_errors": 0, "abstained": 0})
        bucket["tasks"] += 1
        if row.correct:
            bucket["answered"] += 1
            bucket["correct"] += 1
        elif row.confident_error:
            bucket["confident_errors"] += 1
        else:
            bucket["abstained"] += 1
    for bucket in by_construction.values():
        bucket["coverage"] = (bucket["correct"] / bucket["tasks"]
                              if bucket["tasks"] else 0.0)
    total = len(rows)
    return {
        "tasks": total,
        "answered": len(answered),
        "correct": len(answered),
        "coverage": (len(answered) / total) if total else 0.0,
        "confident_errors": len(errors),
        "ambiguous": len(ambiguous),
        "abstained": total - len(answered) - len(errors),
        "by_construction": dict(sorted(by_construction.items())),
    }


def holdout_evidence(rule: ConstructionRule, data: Mapping[str, Any]
                     ) -> HoldoutEvidence:
    tasks = [task for task in data["heldout"]
             if task["construction_id"] == rule.construction_id]
    outcomes = []
    for task in tasks:
        result = match_constructions(
            (rule,), str(task["text"]), allowed_ids={rule.construction_id})
        if result.status != "matched" or result.match is None:
            outcomes.append(False)
            continue
        expected = _expected(task, data, rule.operation)
        output = apply_operation(
            rule.operation, selected_values(task["values"], data))
        outcomes.append(output == expected)
    return HoldoutEvidence(
        passed=all(outcomes) and bool(outcomes),
        cases=len(tasks),
        independent_sources=len({task["source_id"] for task in tasks}),
        detail=(f"{sum(outcomes)}/{len(tasks)} held-out paraphrases matched "
                "and agreed with the independent operation oracle"))


def register_constructions(data: Mapping[str, Any], registry: Any
                           ) -> tuple[ConstructionStore, dict[str, Any]]:
    store = construction_store(data)
    records = {}
    for rule in store.rules():
        evidence = holdout_evidence(rule, data)
        records[rule.construction_id] = register_construction_rule(
            rule, registry, holdout=evidence, allow_successor=False)
    return store, records


def ambiguity_store(data: Mapping[str, Any]) -> ConstructionStore:
    """Two licensed constructions with overlapping wording, for abstention tests."""
    examples = []
    for construction_id in ("ambiguous-a", "ambiguous-b"):
        for index, text in enumerate((
                "sum every value {claim:claim:Mira reaches} "
                "in {values:values:3, 8}",
                "sum each number {claim:claim:Nia can reach} "
                "in {values:values:5, 13}")):
            examples.append(ConstructionExample(
                text=text,
                construction_id=construction_id,
                source_id=f"phase5:ambiguous:{construction_id}:{index}",
                operation="sum", name=construction_id, composition="direct"))
    return ConstructionStore(examples)


def registry_lane(store: ConstructionStore, registry: Any,
                  data: Mapping[str, Any]) -> dict[str, Any]:
    records = [
        record for record in registry.records(
            family="construction", state="active")
        if record.payload.get("origin") == "crms_constructions"
    ]
    active_ids = {record.payload.get("construction_id") for record in records}
    all_have_holdout = all(
        (record.validation or {}).get("passed")
        and int((record.validation or {}).get("cases", 0)) == 20
        and int((record.validation or {}).get("independent_sources", 0)) == 20
        for record in records)
    grammar = ConstructionGrammar(store, registry=registry)
    before = grammar.match("sum every value Mira reaches in 3, 8, 5")
    record_id = construction_rule_id("direct-sum")
    registry.retire(record_id, reason="phase5 retirement check")
    after_retire = ConstructionGrammar(store, registry=registry).match(
        "sum every value Mira reaches in 3, 8, 5")
    dangling = ConstructionGrammar(store, registry=registry).dangling_references()
    registry.rollback(record_id)
    restored = ConstructionGrammar(store, registry=registry).match(
        "sum every value Mira reaches in 3, 8, 5")
    return {
        "active_rule_count": len(records),
        "active_ids": sorted(active_ids),
        "all_active_have_holdout_evidence": all_have_holdout,
        "matched_before_retire": before.status,
        "after_retire": after_retire.status,
        "dangling_references": dangling,
        "matched_after_rollback": restored.status,
        "retired_id": record_id,
    }


def abstention_lane(store: ConstructionStore, registry: Any,
                    data: Mapping[str, Any]) -> dict[str, Any]:
    grammar = ConstructionGrammar(store, registry=registry)
    unlicensed = grammar.match("translate the values 3, 8 into French")
    malformed = grammar.match("sum every value in 3, 8")
    ambiguous_store = ambiguity_store(data)
    ambiguous = ConstructionGrammar(ambiguous_store).match(
        "sum every value Mira reaches in 3, 8")
    single = ConstructionStore([ConstructionExample(
        "sum every value {claim:claim:Mira reaches} in {values:values:3, 8}",
        "single-example", "phase5:single:0", operation="sum",
        name="Single example", composition="direct")])
    single_match = ConstructionGrammar(single).match(
        "sum every value Mira reaches in 3, 8")
    return {
        "unlicensed": unlicensed.status,
        "malformed_missing_slot": malformed.status,
        "ambiguous": ambiguous.status,
        "ambiguous_candidates": [
            match.rule.construction_id for match in ambiguous.matches],
        "unlicensed_single_example": single_match.status,
        "all_abstain": (unlicensed.status == "no_match"
                        and malformed.status == "no_match"
                        and ambiguous.status == "ambiguous"
                        and single_match.status == "no_match"),
    }


def morphology_lane() -> dict[str, Any]:
    from crms_morphology import (
        Morphology, MorphologyRule, register_morphology_rule,
    )
    from crms_rule_registry import RuleRegistry

    morphology = Morphology.default()
    regular = (morphology.matches("value", "values")
               and morphology.matches("entry", "entries")
               and morphology.matches("number", "numbers"))
    irregular_before = morphology.matches("child", "children")
    rule = morphology.add_irregular(
        "child", "children", rule_id="irregular-child",
        source="teacher:phase5:irregular")
    irregular_after = morphology.matches("child", "children")
    forms_generated = "children" in morphology.forms("child")

    registry = RuleRegistry()
    regular_rule = next(rule for rule in morphology.rules
                        if rule.kind == "plural")
    regular_record = register_morphology_rule(regular_rule, registry)
    irregular_record = register_morphology_rule(rule, registry)
    regular_active_before_retirement = regular_record.state == "active"
    irregular_active_before_retirement = irregular_record.state == "active"
    governed = Morphology(
        rules=(regular_rule, rule), registry=registry)
    governed_match = governed.matches("value", "values")
    governed_irregular = governed.matches("child", "children")
    registry.retire(regular_record.id, reason="phase5 morphology retirement")
    after_retire = Morphology(rules=(regular_rule, rule), registry=registry)
    retired_regular = after_retire.active_regular()
    return {
        "regular_expansion": regular,
        "irregular_before_evidence": irregular_before,
        "irregular_after_evidence": irregular_after,
        "irregular_forms_available_after_evidence": forms_generated,
        "registry_regular_active": regular_active_before_retirement,
        "registry_irregular_active": irregular_active_before_retirement,
        "governed_regular_match": governed_match,
        "governed_irregular_match": governed_irregular,
        "regular_after_retirement": retired_regular,
        "irregular_rule_id": irregular_record.id,
    }


def ranker_lane(store: ConstructionStore, registry: Any) -> dict[str, Any]:
    from crms_construction_ranker import ConstructionRanker

    grammar = ConstructionGrammar(store, registry=registry)
    result = grammar.match("sum every value Mira reaches in 3, 8, 5")
    ranker = ConstructionRanker(max_candidates=2, max_features=5)
    proposals = ranker.propose(result.matches)
    bypass = grammar.match("sum every value Mira reaches in 3, 8, 5")
    return {
        "max_candidates": ranker.max_candidates,
        "max_features": ranker.max_features,
        "candidate_count": len(proposals),
        "feature_counts": [len(row.features) for row in proposals],
        "bypass_status": bypass.status,
        "bypass_same": bypass.status == result.status,
        "ranked": [row.to_dict() for row in proposals],
    }


def active_learning_lane() -> dict[str, Any]:
    from crms_constructions import (
        propose_construction_gap, record_construction_answer,
    )
    from crms_rule_registry import RuleRegistry

    store = ConstructionStore()
    for index, variant in enumerate((
            "sum every value {claim:claim:Mira reaches} in "
            "{values:values:3, 8}",
            "total each number {claim:claim:Nia can reach} from "
            "{values:values:5, 13}")):
        store.add_example(ConstructionExample(
            variant, "direct-sum", f"phase5:active:train:{index}",
            operation="sum", name="Direct sum", composition="direct"))
    registry = RuleRegistry()
    rule = store.rule("direct-sum")
    assert rule is not None
    record = register_construction_rule(rule, registry)
    grammar = ConstructionGrammar(store, registry=registry)
    query = "enumerate every value Mira reaches in 3, 8"
    failed = grammar.match(query)
    question = propose_construction_gap(query, "select-transform", grammar)
    if question is None:
        raise RuntimeError("failed wording produced no construction question")
    answer = record_construction_answer(
        question,
        marked_text=("enumerate every value {claim:claim:Mira reaches} "
                     "in {values:values:3, 8}"),
        source_id="phase5:active:answer:1",
        store=store,
        registry=registry,
        operation="sum",
    )
    updated = ConstructionGrammar(store, registry=registry)
    return {
        "failed_status": failed.status,
        "question": question.to_dict(),
        "questions_asked": 1,
        "answer_status": answer.status,
        "rule_state": answer.rule_state,
        "matched_after": updated.match(query).status,
        "construction_id": question.construction_id,
        "missing": question.missing,
    }


def run_benchmark(data: Mapping[str, Any]) -> dict[str, Any]:
    from crms_rule_registry import RuleRegistry

    registry = RuleRegistry()
    store, records = register_constructions(data, registry)
    grammar = ConstructionGrammar(store, registry=registry)
    baseline = baseline_frames(data)
    tasks = data["heldout"]
    learned = [solve_task(grammar, task, data, record_use=True)
               for task in tasks]
    baseline_outcomes = [solve_baseline(baseline, task, data)
                         for task in tasks]
    learned_summary = summarize(learned)
    baseline_summary = summarize(baseline_outcomes)
    learned_by_kind: dict[str, list[Outcome]] = {}
    baseline_by_kind: dict[str, list[Outcome]] = {}
    for learned_row, baseline_row, task in zip(learned, baseline_outcomes, tasks):
        kind = str(task["kind"])
        learned_by_kind.setdefault(kind, []).append(learned_row)
        baseline_by_kind.setdefault(kind, []).append(baseline_row)
    return {
        "store": store,
        "registry": registry,
        "records": records,
        "learned": learned_summary,
        "baseline": baseline_summary,
        "learned_by_kind": {
            kind: summarize(rows)
            for kind, rows in sorted(learned_by_kind.items())},
        "baseline_by_kind": {
            kind: summarize(rows)
            for kind, rows in sorted(baseline_by_kind.items())},
        "tasks": tasks,
    }


def new_construction_lane() -> dict[str, Any]:
    """A new construction enters through the registry and leaves cleanly."""
    from crms_rule_registry import RuleRegistry

    store = ConstructionStore()
    for index, text in enumerate((
            "please reverse the values {claim:claim:Mira reaches} "
            "in {values:values:3, 8}",
            "please flip the entries {claim:claim:Nia can reach} "
            "from {values:values:5, 13}")):
        store.add_example(ConstructionExample(
            text, "polite-reverse", f"phase5:new:{index}",
            operation="reverse", name="Polite reverse", composition="direct"))
    rule = store.rule("polite-reverse")
    if rule is None:
        raise RuntimeError("new construction did not license")
    registry = RuleRegistry()
    record = register_construction_rule(
        rule, registry,
        holdout=HoldoutEvidence(True, 2, 2, "new construction held-out check"))
    grammar = ConstructionGrammar(store, registry=registry)
    query = "please reverse the values Mira reaches in 3, 8"
    before = grammar.match(query)
    registry.retire(record.id, reason="phase5 new-construction retirement")
    after_grammar = ConstructionGrammar(store, registry=registry)
    after = after_grammar.match(query)
    registry.rollback(record.id)
    restored = ConstructionGrammar(store, registry=registry).match(query)
    return {
        "rule_id": record.id,
        "state_before": record.state,
        "matched_before": before.status,
        "matched_after_retire": after.status,
        "dangling_references": after_grammar.dangling_references(),
        "matched_after_rollback": restored.status,
    }


def context_lane(store: ConstructionStore, registry: Any,
                 data: Mapping[str, Any]) -> dict[str, Any]:
    """The same utterance is evaluated under two different selection contexts."""
    grammar = ConstructionGrammar(store, registry=registry)
    text = "sum every value Mira reaches in 3, 8, 5"
    result = grammar.match(text)
    if result.status != "matched" or result.match is None:
        return {"matched": False, "context_sensitive": False,
                "status": result.status}
    values = [3, 8, 5]
    contexts = (
        {"positive": [3, 8, 5], "negative": [11, -2]},
        {"positive": [3], "negative": [8, 5, 11]},
    )
    outputs = []
    for context in contexts:
        selected = [value for value in values
                    if value in context["positive"]
                    and value not in context["negative"]]
        outputs.append(apply_operation("sum", selected))
    return {
        "matched": True,
        "same_slots": dict(result.match.slots),
        "outputs": outputs,
        "context_sensitive": outputs[0] != outputs[1],
        "context_count": len(contexts),
    }
