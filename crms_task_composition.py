"""Bounded composition of proof-checked relation results and learned procedures.

The parser accepts a deliberately explicit finite-set request. Relation claims
are proved against the knowledge base; only complete independently verified
positive proofs are passed to the learned list procedure. Unknown or conflicting
members prevent a final result.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_rule_proof import verify_inference_proof


_INTEGER_LIST = (
    r"-?\d+(?:\s*,\s*-?\d+)*(?:\s*,?\s+and\s+-?\d+)?")
_REQUESTS = (
    re.compile(
        r"^\s*From\s+(?:the\s+)?(?:values?\s+)?"
        rf"(?P<values>{_INTEGER_LIST})"
        r",\s*keep\s+(?:only\s+)?(?:the\s+)?values\s+"
        r"(?:that\s+|which\s+)?(?P<claim>.+?),\s*then\s+"
        r"(?P<procedure>.+?)\s*[.!?]*\s*$", re.IGNORECASE),
    re.compile(
        rf"^\s*Filter\s+(?P<values>{_INTEGER_LIST})\s+to\s+"
        r"(?:the\s+)?values\s+(?:that\s+|which\s+)?"
        r"(?P<claim>.+?)[,;]\s*(?:and\s+)?then\s+"
        r"(?P<procedure>.+?)\s*[.!?]*\s*$", re.IGNORECASE),
    re.compile(
        rf"^\s*Given\s+(?P<values>{_INTEGER_LIST}),\s*keep\s+"
        r"(?:only\s+)?(?:the\s+)?values\s+(?:that\s+|which\s+)?"
        r"(?P<claim>.+?),\s*and\s+then\s+"
        r"(?P<procedure>.+?)\s*[.!?]*\s*$", re.IGNORECASE),
    re.compile(
        rf"^\s*From\s+\[(?P<values>{_INTEGER_LIST})\],\s*return\s+"
        r"(?:the\s+)?values\s+(?:that\s+|which\s+)?"
        r"(?P<claim>.+?),\s*then\s+"
        r"(?P<procedure>.+?)\s*[.!?]*\s*$", re.IGNORECASE),
)


def _normalize_procedure_sequence(instruction: str) -> str:
    """Normalize explicit sequence connectives without inventing operations."""
    text = " ".join(instruction.strip().rstrip(".!?").split())
    text = re.sub(r"\s+and\s+then\s+", " then ", text, flags=re.IGNORECASE)
    after = re.fullmatch(r"(.+?)\s+after\s+(.+)", text,
                         flags=re.IGNORECASE)
    if after is not None:
        # 'A after B' explicitly orders B before A.
        text = f"{after.group(2).strip()} then {after.group(1).strip()}"
    return text


@dataclass(frozen=True)
class ReasonedListComposition:
    status: str
    text: str
    subject: str | None = None
    relation: str | None = None
    input_values: tuple[int, ...] = ()
    included_values: tuple[int, ...] = ()
    excluded_negative: tuple[int, ...] = ()
    unresolved_values: tuple[int, ...] = ()
    output_values: tuple[int, ...] = ()
    procedure: str | None = None
    evidence_sources: tuple[str, ...] = ()
    proof_checks: int = 0
    evidence: tuple[dict[str, Any], ...] = ()
    inference_proofs: tuple[dict[str, Any], ...] = ()
    procedure_records: tuple[dict[str, Any], ...] = ()
    language_evidence: tuple[dict[str, Any], ...] = ()


def _relation_and_subject(claim: str, knowledge: CRMSKnowledgeBase
                          ) -> tuple[str, str] | None:
    relations = {fact.relation for fact in
                 (*knowledge.facts(), *knowledge.negative_facts())}
    relations.update(rule.conclusion_relation
                     for rule in knowledge._inference_rules.values())
    matches: set[tuple[str, str]] = set()
    folded = " ".join(claim.casefold().split())
    for relation in relations:
        suffix = " ".join(relation.casefold().split())
        if folded.endswith(" " + suffix):
            subject = claim[:len(claim) - len(relation)].strip()
            subject = re.sub(r"\s+is\s+(?:a|an)\s*$", "", subject,
                             flags=re.IGNORECASE).strip()
            if subject:
                matches.add((subject, relation))
    if len(matches) != 1:
        return None
    return next(iter(matches))


def _proof_sources(proof: dict[str, Any]) -> set[str]:
    sources: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("fact", "relation_type_fact"):
                fact = node.get(key)
                if isinstance(fact, dict):
                    sources.update(str(source) for source in fact.get("sources", ()))
            for value in node.values():
                if isinstance(value, (dict, list, tuple)):
                    visit(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                visit(value)

    visit(proof)
    return sources


def compose_verified_filter(instruction: str, knowledge: CRMSKnowledgeBase,
                            procedures: CRMSModel) -> ReasonedListComposition | None:
    """Apply a learned list procedure to a finite, fully classified value set.

    Return ``None`` when the user input is outside this narrow request frame.
    Unknown, contradictory, incomplete, or unverifiable members cause an
    abstention rather than silently filtering away a possible value.
    """
    match = None
    for candidate in _REQUESTS:
        match = candidate.fullmatch(instruction)
        if match is not None:
            break
    if match is None:
        return None
    values = tuple(int(value) for value in
                   re.findall(r"-?\d+", match.group("values")))
    if not values or len(values) > 32:
        return ReasonedListComposition(
            "unsupported", "I can check a finite list of 1 to 32 integer values.")
    parsed = _relation_and_subject(match.group("claim"), knowledge)
    language_evidence: tuple[dict[str, Any], ...] = ()
    if parsed is None:
        learned_match = knowledge.match_fact_pattern_relation_claim(
            match.group("claim"))
        if learned_match is not None:
            parsed = (learned_match["subject"], learned_match["relation"])
            language_evidence = (learned_match,)
    if parsed is None:
        return ReasonedListComposition(
            "unsupported", "I couldn't identify one unambiguous stored relation and subject.")
    subject, relation = parsed
    procedure = _normalize_procedure_sequence(match.group("procedure"))
    positive_facts = knowledge.facts()
    negative_facts = knowledge.negative_facts()
    fact_records = [asdict(fact) for fact in positive_facts]
    fact_records.extend(asdict(fact) for fact in negative_facts)
    rule_records = [asdict(rule)
                    for rule in knowledge._inference_rules.values()]
    included: list[int] = []
    negative: list[int] = []
    unresolved: list[int] = []
    sources: set[str] = set()
    for row in language_evidence:
        sources.update(str(source) for source in row.get("sources", ()) if source)
    verified_proofs: list[dict[str, Any]] = []
    negative_evidence: list[dict[str, Any]] = []
    checks = 0

    def same_endpoint(left: str, right: str) -> bool:
        return " ".join(left.casefold().split()) == " ".join(right.casefold().split())

    for value in values:
        object_text = str(value)
        explicit_negative = any(
            same_endpoint(fact.subject, subject)
            and same_endpoint(fact.relation, relation)
            and same_endpoint(fact.object, object_text)
            for fact in negative_facts)
        inference = knowledge.infer_relation(subject, relation, object_text)
        verified_proof = None
        if inference.complete:
            for proof in inference.proofs:
                checked = verify_inference_proof(
                    proof, fact_records, rule_records,
                    expected_conclusion={
                        "subject": subject, "relation": relation,
                        "object": object_text})
                checks += 1
                if checked.valid:
                    verified_proof = proof
                    break
        matched_negative_facts = [
            fact for fact in negative_facts
            if same_endpoint(fact.subject, subject)
            and same_endpoint(fact.relation, relation)
            and same_endpoint(fact.object, object_text)]
        if explicit_negative:
            negative_evidence.extend(asdict(fact)
                                     for fact in matched_negative_facts)
            for fact in matched_negative_facts:
                sources.update(fact.sources)
        if (inference.status in {"ambiguous", "contradicted"}
                or explicit_negative and verified_proof is not None):
            if verified_proof is not None:
                if verified_proof not in verified_proofs:
                    verified_proofs.append(verified_proof)
                sources.update(_proof_sources(verified_proof))
            return ReasonedListComposition(
                "conflict", f"I found both positive and negative support for {subject} {relation} {value}; I did not run the procedure. Evidence sources: {', '.join(sorted(sources))}.",
                subject, relation, values, unresolved_values=(value,),
                procedure=procedure, evidence_sources=tuple(sorted(sources)),
                proof_checks=checks, evidence=tuple(negative_evidence),
                inference_proofs=tuple(verified_proofs),
                language_evidence=language_evidence)
        if explicit_negative:
            negative.append(value)
        elif inference.status == "answered" and verified_proof is not None:
            included.append(value)
            if verified_proof not in verified_proofs:
                verified_proofs.append(verified_proof)
            sources.update(_proof_sources(verified_proof))
        else:
            unresolved.append(value)

    if unresolved:
        rendered = ", ".join(map(str, sorted(set(unresolved))))
        return ReasonedListComposition(
            "unknown", f"I can't determine whether {rendered} satisfy {subject} {relation}; I did not run the procedure on a partial set.",
            subject, relation, values, tuple(included), tuple(negative),
            tuple(unresolved), procedure=procedure,
            evidence_sources=tuple(sorted(sources)), proof_checks=checks,
            evidence=tuple(negative_evidence),
            inference_proofs=tuple(verified_proofs),
            language_evidence=language_evidence)

    prediction = procedures.predict(procedure, included)
    if prediction.status != "ok" or prediction.output is None:
        return ReasonedListComposition(
            "unsupported_procedure",
            prediction.request or "I couldn't verify that learned list procedure.",
            subject, relation, values, tuple(included), tuple(negative),
            procedure=procedure, evidence_sources=tuple(sorted(sources)),
            proof_checks=checks, evidence=tuple(negative_evidence),
            inference_proofs=tuple(verified_proofs),
            language_evidence=language_evidence)
    output = tuple(prediction.output)
    procedure_phrases = set(prediction.evidence_phrases or ())
    procedure_records = tuple(
        record
        for phrase in sorted(procedure_phrases)
        for record in procedures.example_records(phrase))
    for record in procedure_records:
        refs = [str(record.get("source_id") or ""),
                str(record.get("instruction_source_id") or "")]
        sources.update(value for value in refs if value)
    exclusions = (f"; excluded explicitly negative values {negative}"
                  if negative else "")
    evidence = ", ".join(sorted(sources)) or "verified stored proofs"
    labelers = sorted({str(record.get("labeler_id"))
                       for record in procedure_records
                       if record.get("labeler_id")})
    support_note = (f" Procedure examples: {len(procedure_records)}"
                    + (f" (labeler: {', '.join(labelers)})" if labelers else "")
                    + ".")
    language_note = ""
    if language_evidence:
        alignments = "; ".join(
            f"'{row['surface_phrase']}' → '{row['relation']}'"
            for row in language_evidence)
        language_note = (f" Taught relation wording: {alignments}; sources: "
                         + ", ".join(sorted({source
                                              for row in language_evidence
                                              for source in row.get("sources", ())}))
                         + ".")
    text = (f"Verified values satisfying {subject} {relation}: {included}"
            f"{exclusions}. After '{procedure}': {list(output)}. "
            f"Evidence sources: {evidence}.{support_note}{language_note}")
    return ReasonedListComposition(
        "answered", text, subject, relation, values, tuple(included),
        tuple(negative), (), output, procedure, tuple(sorted(sources)), checks,
        tuple(negative_evidence), tuple(verified_proofs),
        procedure_records, language_evidence)
