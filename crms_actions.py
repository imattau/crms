"""Production actions for the typed task planner.

The first two adapters cover Family A: select values with verified positive
relation evidence, then apply a learned integer-list procedure. Verification is
independent of search: inference proofs are rechecked with
``crms_rule_proof.verify_inference_proof`` and procedure execution is replayed
for parity with the stored procedure.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Mapping

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_planner import Action, ExecutionContext, Verification
from crms_rule_proof import verify_inference_proof
from crms_tasks import EvidenceRef, Step, StepResult


def _same_endpoint(left: str, right: str) -> bool:
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


def _qualifier_key(value: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(item)) for key, item in (value or {}).items()))


class SelectVerifiedPositiveAction(Action):
    """Select values with a complete verified positive relation.

    Explicit negative evidence excludes a value. Missing evidence is unknown;
    it is never treated as negative. A positive proof plus explicit negative
    evidence is a conflict and fails the step.
    """

    name = "select-verified-positive"

    def __init__(self, knowledge: CRMSKnowledgeBase) -> None:
        self.knowledge = knowledge

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        values = inputs.get("values")
        subject = inputs.get("subject")
        relation = inputs.get("relation")
        qualifiers = inputs.get("qualifiers", {})
        return (
            isinstance(subject, str) and bool(subject.strip())
            and isinstance(relation, str) and bool(relation.strip())
            and isinstance(values, (list, tuple))
            and 1 <= len(values) <= 32
            and all(isinstance(value, int) and not isinstance(value, bool)
                    for value in values)
            and isinstance(qualifiers, Mapping)
        )

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        subject = str(inputs["subject"]).strip()
        relation = str(inputs["relation"]).strip()
        values = [int(value) for value in inputs["values"]]
        qualifiers = {
            str(key): str(value)
            for key, value in dict(inputs.get("qualifiers", {})).items()
        }
        facts = [asdict(fact) for fact in self.knowledge.facts()]
        negatives = [asdict(fact) for fact in self.knowledge.negative_facts()]
        rules = [asdict(rule)
                 for rule in self.knowledge._inference_rules.values()]
        fact_records = facts + negatives

        selected: list[int] = []
        excluded: list[int] = []
        unknown: list[int] = []
        incomplete: list[int] = []
        evidence: list[EvidenceRef] = []
        checks = 0

        for value in values:
            object_text = str(value)
            matched_negative = [
                fact for fact in self.knowledge.negative_facts()
                if _same_endpoint(fact.subject, subject)
                and _same_endpoint(fact.relation, relation)
                and _same_endpoint(fact.object, object_text)
                and _qualifier_key(dict(fact.qualifiers))
                == _qualifier_key(qualifiers)
            ]
            inference = self.knowledge.infer_relation(
                subject, relation, object_text,
                qualifiers=qualifiers or None)
            verified_proof = None
            for proof in inference.proofs or ():
                checked = verify_inference_proof(
                    proof, fact_records, rules,
                    expected_conclusion={
                        "subject": subject,
                        "relation": relation,
                        "object": object_text,
                    },
                    expected_qualifiers=qualifiers)
                checks += 1
                if checked.valid:
                    verified_proof = proof
                    break

            if matched_negative and verified_proof is not None:
                for fact in matched_negative:
                    evidence.append(EvidenceRef(
                        "fact", f"{subject} {relation} {object_text}",
                        source=sorted(fact.sources)[0] if fact.sources else None,
                        detail={"negative": True, "qualifiers": qualifiers,
                                "object": object_text,
                                "fact": asdict(fact),
                                "sources": sorted(fact.sources)}))
                proof_sources = sorted(_proof_leaf_sources(verified_proof))
                evidence.append(EvidenceRef(
                    "proof", f"{subject} {relation} {object_text}",
                    source=proof_sources[0] if proof_sources else None,
                    detail={
                        "subject": subject,
                        "relation": relation,
                        "object": object_text,
                        "qualifiers": qualifiers,
                        "proof": verified_proof,
                    }))
                return StepResult(
                    step.id, "failed", evidence=tuple(evidence),
                    reason_code="conflict",
                    metadata={"conflict_value": value, "checks": checks},
                    detail=(f"both positive proof and explicit negative "
                            f"evidence exist for {subject} {relation} "
                            f"{object_text}"))
            if inference.status in {"ambiguous", "contradicted"}:
                for fact in matched_negative:
                    evidence.append(EvidenceRef(
                        "fact", f"{subject} {relation} {object_text}",
                        source=sorted(fact.sources)[0] if fact.sources else None,
                        detail={"negative": True, "qualifiers": qualifiers,
                                "object": object_text,
                                "fact": asdict(fact),
                                "sources": sorted(fact.sources)}))
                return StepResult(
                    step.id, "failed", evidence=tuple(evidence),
                    reason_code="conflict",
                    metadata={"conflict_value": value, "checks": checks},
                    detail=(f"relation evidence for {subject} {relation} "
                            f"{object_text} is {inference.status}"))
            if inferred_conflict(inference):
                return StepResult(
                    step.id, "failed", evidence=tuple(evidence),
                    reason_code="conflict",
                    metadata={"conflict_value": value, "checks": checks},
                    detail=(f"relation evidence for {subject} {relation} "
                            f"{object_text} conflicts"))
            if matched_negative:
                excluded.append(value)
                for fact in matched_negative:
                    evidence.append(EvidenceRef(
                        "fact", f"{subject} {relation} {object_text}",
                        source=sorted(fact.sources)[0] if fact.sources else None,
                        detail={"negative": True, "qualifiers": qualifiers,
                                "object": object_text,
                                "fact": asdict(fact),
                                "sources": sorted(fact.sources)}))
                continue
            if verified_proof is not None:
                selected.append(value)
                sources = sorted(_proof_leaf_sources(verified_proof))
                evidence.append(EvidenceRef(
                    "proof", f"{subject} {relation} {object_text}",
                    source=sources[0] if sources else None,
                    detail={
                        "subject": subject,
                        "relation": relation,
                        "object": object_text,
                        "qualifiers": qualifiers,
                        "proof": verified_proof,
                    }))
                continue
            if inference.complete:
                unknown.append(value)
            else:
                incomplete.append(value)

        if unknown or incomplete:
            parts = []
            if unknown:
                parts.append(f"unknown values: {unknown}")
            if incomplete:
                parts.append(f"incomplete relation search for values: {incomplete}")
            return StepResult(
                step.id, "failed", evidence=tuple(evidence),
                reason_code="unknown_values",
                metadata={
                    "included": list(selected),
                    "excluded": list(excluded),
                    "unresolved": list(unknown),
                    "incomplete": list(incomplete),
                    "checks": checks,
                },
                detail=("no partial selection is returned; " + "; ".join(parts)))
        return StepResult(
            step.id, "ok", output=selected, evidence=tuple(evidence),
            reason_code="selected",
            metadata={
                "included": list(selected),
                "excluded": list(excluded),
                "unresolved": [],
                "checks": checks,
            },
            detail=(f"selected {selected}; excluded {excluded}; "
                    f"scope {qualifiers or 'unqualified'}"))

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        if not isinstance(result.output, list) or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in result.output):
            return Verification(False, "selection output must be a list of integers")
        values = [int(value) for value in inputs["values"]]
        subject = str(inputs["subject"]).strip()
        relation = str(inputs["relation"]).strip()
        qualifiers = dict(inputs.get("qualifiers", {}))
        selected = set(result.output)
        expected_order = [value for value in values if value in selected]
        if result.output != expected_order:
            return Verification(
                False, "selection output does not preserve input order or "
                       "contains an unrequested value")

        facts = [asdict(fact) for fact in self.knowledge.facts()]
        negatives = [asdict(fact) for fact in self.knowledge.negative_facts()]
        rules = [asdict(rule) for rule in self.knowledge._inference_rules.values()]
        proof_objects: set[str] = set()
        negative_objects: set[str] = set()
        for ref in result.evidence:
            detail = dict(ref.detail)
            if ref.kind == "proof":
                proof = detail.get("proof")
                object_text = str(detail.get("object", ""))
                checked = verify_inference_proof(
                    proof, facts + negatives, rules,
                    expected_conclusion={
                        "subject": subject,
                        "relation": relation,
                        "object": object_text,
                    },
                    expected_qualifiers=qualifiers)
                if not checked.valid:
                    return Verification(
                        False, f"selection proof for {object_text} is invalid: "
                               f"{checked.reason}")
                proof_objects.add(object_text)
            elif ref.kind == "fact" and detail.get("negative"):
                object_text = str(detail.get("object", ""))
                match = any(
                    _same_endpoint(fact["subject"], subject)
                    and _same_endpoint(fact["relation"], relation)
                    and _same_endpoint(fact["object"], object_text)
                    and _qualifier_key(dict(fact.get("qualifiers", ())))
                    == _qualifier_key(qualifiers)
                    for fact in negatives)
                if not match:
                    return Verification(
                        False, f"negative evidence for {object_text} is not present")
                negative_objects.add(object_text)
        for value in result.output:
            if str(value) not in proof_objects:
                return Verification(
                    False, f"selected value {value} has no verified proof")
            if str(value) in negative_objects:
                return Verification(
                    False, f"selected value {value} also has negative evidence")
        for value in values:
            if value not in selected and str(value) not in negative_objects:
                return Verification(
                    False, f"value {value} was dropped without negative evidence")
        return Verification(True)


class ApplyLearnedProcedureAction(Action):
    """Apply one learned integer-list procedure to a selected list."""

    name = "apply-learned-procedure"

    def __init__(self, model: CRMSModel,
                 resolver: Callable[[str, list[int], bool],
                                    tuple[str, Any, str | None]]
                 | None = None) -> None:
        self.model = model
        self.resolver = resolver

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        values = inputs.get("values")
        instruction = inputs.get("instruction")
        return (
            isinstance(values, (list, tuple))
            and len(values) <= 10_000
            and all(isinstance(value, int) and not isinstance(value, bool)
                    for value in values)
            and isinstance(instruction, str) and bool(instruction.strip())
        )

    def _resolve(self, instruction: str, values: list[int],
                 record_use: bool) -> tuple[str, Any, str | None]:
        if self.resolver is not None:
            return self.resolver(instruction, values, record_use)
        return instruction, self.model.predict(
            instruction, values, record_use=record_use), None

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        instruction = str(inputs["instruction"]).strip()
        values = [int(value) for value in inputs["values"]]
        licensed, prediction, morphology_note = self._resolve(
            instruction, values, True)
        if prediction.status != "ok" or prediction.output is None:
            return StepResult(
                step.id, "failed",
                reason_code="procedure_unresolved",
                metadata={"surface_instruction": instruction},
                detail=(prediction.request or prediction.message
                        or f"procedure did not resolve: {prediction.status}"))
        phrases = sorted(set(prediction.evidence_phrases or ()))
        records = [
            record
            for phrase in phrases
            for record in self.model.example_records(phrase)
        ]
        evidence = EvidenceRef(
            "procedure", licensed,
            detail={
                "surface_instruction": instruction,
                "licensed_instruction": licensed,
                "morphology_note": morphology_note,
                "procedure": prediction.procedure,
                "evidence_phrases": phrases,
                "examples": records,
            })
        detail = f"applied learned procedure {licensed!r}"
        if licensed != instruction:
            detail += f" for the surface form {instruction!r}"
        if morphology_note:
            detail += f" (licensed morphology: {morphology_note})"
        return StepResult(
            step.id, "ok", output=list(prediction.output),
            evidence=(evidence,),
            reason_code="procedure_applied",
            metadata={
                "surface_instruction": instruction,
                "licensed_instruction": licensed,
                "morphology_note": morphology_note,
            },
            detail=detail)

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        instruction = str(inputs["instruction"]).strip()
        values = [int(value) for value in inputs["values"]]
        licensed, replay, morphology_note = self._resolve(
            instruction, values, False)
        if replay.status != "ok":
            return Verification(
                False, f"stored procedure no longer resolves: {replay.status}")
        if replay.output != result.output:
            return Verification(
                False, f"procedure parity failed: {result.output!r} != "
                       f"{replay.output!r}")
        recorded = next(
            (ref for ref in result.evidence if ref.kind == "procedure"), None)
        if recorded is None:
            return Verification(False, "procedure evidence is missing")
        if recorded.detail.get("procedure") != replay.procedure:
            return Verification(
                False, "procedure changed between execution and verification")
        if recorded.detail.get("licensed_instruction") != licensed:
            return Verification(
                False, "licensed procedure changed between execution and "
                       "verification")
        if recorded.detail.get("morphology_note") != morphology_note:
            return Verification(
                False, "procedure morphology changed between execution and "
                       "verification")
        return Verification(True)


def inferred_conflict(inference: Any) -> bool:
    """True when inference reports an integrity conflict rather than absence."""

    reason = str(getattr(inference, "reason_code", "") or "")
    failure = str(getattr(inference, "failure_kind", "") or "")
    return reason == "integrity_conflict" or failure == "integrity_conflict"


def _proof_leaf_sources(proof: Mapping[str, Any]) -> set[str]:
    sources: set[str] = set()

    def visit(node: Any) -> None:
        if not isinstance(node, Mapping):
            return
        fact = node.get("fact")
        if isinstance(fact, Mapping):
            sources.update(str(source) for source in fact.get("sources", ())
                           if source)
        for premise in node.get("premises", ()) or ():
            visit(premise)

    visit(proof)
    return sources
