"""Production actions for the typed task planner.

The first two adapters cover Family A: select values with verified positive
relation evidence, then apply a learned integer-list procedure. Verification is
independent of search: inference proofs are rechecked with
``crms_rule_proof.verify_inference_proof`` and procedure execution is replayed
for parity with the stored procedure.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

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
                if checked.valid:
                    verified_proof = proof
                    break

            if matched_negative and verified_proof is not None:
                for fact in matched_negative:
                    evidence.append(EvidenceRef(
                        "fact", f"{subject} {relation} {object_text}",
                        source=sorted(fact.sources)[0] if fact.sources else None,
                        detail={"negative": True, "qualifiers": qualifiers,
                                "object": object_text}))
                return StepResult(
                    step.id, "failed", evidence=tuple(evidence),
                    detail=(f"both positive proof and explicit negative "
                            f"evidence exist for {subject} {relation} "
                            f"{object_text}"))
            if inference.status in {"ambiguous", "contradicted"}:
                return StepResult(
                    step.id, "failed", evidence=tuple(evidence),
                    detail=(f"relation evidence for {subject} {relation} "
                            f"{object_text} is {inference.status}"))
            if inferred_conflict(inference):
                return StepResult(
                    step.id, "failed", evidence=tuple(evidence),
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
                detail=("no partial selection is returned; " + "; ".join(parts)))
        return StepResult(
            step.id, "ok", output=selected, evidence=tuple(evidence),
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

    def __init__(self, model: CRMSModel) -> None:
        self.model = model

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

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        instruction = str(inputs["instruction"]).strip()
        values = [int(value) for value in inputs["values"]]
        prediction = self.model.predict(instruction, values)
        if prediction.status != "ok" or prediction.output is None:
            return StepResult(
                step.id, "failed",
                detail=(prediction.request or prediction.message
                        or f"procedure did not resolve: {prediction.status}"))
        evidence = EvidenceRef(
            "procedure", instruction,
            detail={
                "procedure": prediction.procedure,
                "evidence_phrases": list(prediction.evidence_phrases or ()),
                "examples": self.model.example_records(instruction)[:5],
            })
        return StepResult(
            step.id, "ok", output=list(prediction.output),
            evidence=(evidence,),
            detail=f"applied learned procedure {instruction!r}")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        instruction = str(inputs["instruction"]).strip()
        values = [int(value) for value in inputs["values"]]
        replay = self.model.predict(instruction, values, record_use=False)
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
