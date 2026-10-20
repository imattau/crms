"""Bounded composition of proof-checked relation results and learned procedures.

The parser accepts a deliberately explicit finite-set request. Relation claims
are proved against the knowledge base; only complete independently verified
positive proofs are passed to the learned list procedure. Unknown or conflicting
members prevent a final result.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_rule_proof import verify_inference_proof


_INTEGER_LIST = (
    r"-?\d+(?:\s*,\s*-?\d+)*(?:\s*,?\s+and\s+-?\d+)?")
_REQUESTS = (
    re.compile(
        rf"^\s*(?P<procedure>sum\s+every\s+value)\s+in\s+"
        rf"(?P<values>{_INTEGER_LIST})\s+that\s+"
        r"(?P<claim>.+?)\s*[.!?]*\s*$", re.IGNORECASE),
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
    re.compile(
        rf"^\s*(?:Please\s+)?Filter\s+\[(?P<values>{_INTEGER_LIST})\]"
        r"\s+to\s+(?:the\s+)?values\s+(?:that\s+|which\s+)?"
        r"(?P<claim>.+?),\s*(?:and\s+)?then\s+"
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


def _predict_licensed_procedure(procedures: CRMSModel, instruction: str,
                                values: list[int]
                                ) -> tuple[str, Any, str | None]:
    """Use a licensed phrase, allowing a checked gerund-to-base-form mapping.

    Each morphology candidate is still passed through the ordinary procedure
    learner. This changes only the grammatical form of an operation token; it
    cannot authorize a procedure the model does not already support.
    """
    direct = procedures.predict(instruction, values)
    if direct.status == "ok":
        return instruction, direct, None

    parts = instruction.split(" then ")
    candidates: set[str] = set()
    for index, part in enumerate(parts):
        match = re.match(r"^(?P<verb>[a-z]+ing)(?P<rest>\b.*)$", part,
                         flags=re.IGNORECASE)
        if match is None:
            continue
        verb = match.group("verb")
        stem = verb[:-3]
        bases = {stem, stem + "e"}
        if len(stem) > 2 and stem[-1] == stem[-2]:
            bases.add(stem[:-1])
        for base in bases:
            rewritten = list(parts)
            rewritten[index] = base + match.group("rest")
            candidate = " then ".join(rewritten)
            if candidate != instruction:
                candidates.add(candidate)

    licensed = [(candidate, procedures.predict(candidate, values))
                for candidate in sorted(candidates)]
    licensed = [(candidate, prediction)
                for candidate, prediction in licensed
                if prediction.status == "ok" and prediction.output is not None]
    if len(licensed) != 1:
        return instruction, direct, None
    candidate, prediction = licensed[0]
    changed = next((
        f"{original.split()[0]} → {normalized.split()[0]}"
        for original, normalized in zip(parts, candidate.split(" then "))
        if original != normalized), None)
    return candidate, prediction, changed


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


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def create_derived_composition_record(
        request: str, result: ReasonedListComposition,
        knowledge: CRMSKnowledgeBase) -> dict[str, Any] | None:
    """Build a content-addressed artifact from a freshly verified composition."""
    if (result.status != "answered" or result.subject is None
            or result.relation is None or result.procedure is None
            or not result.inference_proofs or not result.procedure_records):
        return None
    knowledge_fingerprint, _facts, _negatives, _rules = (
        knowledge._inference_snapshot_fingerprint(result.relation, ()))
    proofs = [dict(proof) for proof in result.inference_proofs]
    procedure_records = [dict(record) for record in result.procedure_records]
    rule_ids: set[str] = set()

    def collect_rules(value: Any) -> None:
        if isinstance(value, dict):
            rule = value.get("rule")
            if isinstance(rule, dict) and isinstance(rule.get("rule_id"), str):
                rule_ids.add(rule["rule_id"])
            for child in value.values():
                if isinstance(child, (dict, list, tuple)):
                    collect_rules(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect_rules(child)

    collect_rules(proofs)
    sources = set(result.evidence_sources)
    for record in procedure_records:
        for key in ("source_id", "instruction_source_id"):
            source = record.get(key)
            if isinstance(source, str) and source:
                sources.add(source)
    record = {
        "format_version": 1,
        "request": request,
        "subject": result.subject,
        "relation": result.relation,
        "input_values": list(result.input_values),
        "included_values": list(result.included_values),
        "excluded_negative": list(result.excluded_negative),
        "output_values": list(result.output_values),
        "procedure": result.procedure,
        "procedure_records": procedure_records,
        "procedure_fingerprint": _fingerprint(procedure_records),
        "inference_proofs": proofs,
        "proof_fingerprint": _fingerprint(proofs),
        "negative_evidence": [dict(item) for item in result.evidence],
        "language_evidence": [dict(item) for item in result.language_evidence],
        "knowledge_fingerprint": knowledge_fingerprint,
        "lineage": {
            "sources": sorted(sources),
            "rule_ids": sorted(rule_ids),
            "procedure_phrases": sorted({
                str(item.get("phrase")) for item in procedure_records
                if item.get("phrase")}),
        },
    }
    record["artifact_id"] = CRMSKnowledgeBase.derived_composition_artifact_id(
        record)
    return record


def revalidate_derived_composition(
        record: dict[str, Any], knowledge: CRMSKnowledgeBase,
        procedures: CRMSModel) -> tuple[str, str]:
    """Re-run the exact request before presenting a stored composition as current."""
    current = compose_verified_filter(record.get("request", ""),
                                      knowledge, procedures)
    if current is None or current.status != "answered":
        return "stale", "the current evidence no longer proves a complete result"
    rebuilt = create_derived_composition_record(
        record["request"], current, knowledge)
    if rebuilt is None:
        return "stale", "the current proof or procedure evidence is incomplete"
    if rebuilt["knowledge_fingerprint"] != record["knowledge_fingerprint"]:
        return "stale", "the supporting knowledge or rule state changed"
    if rebuilt["proof_fingerprint"] != record["proof_fingerprint"]:
        return "stale", "the verified proof set changed"
    if rebuilt["procedure_fingerprint"] != record["procedure_fingerprint"]:
        return "stale", "the supporting procedure examples changed"
    if rebuilt["artifact_id"] != record["artifact_id"]:
        return "stale", "the composed result or its recorded lineage changed"
    return "current", "the evidence, proofs, procedures, and output still match"


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


def _generic_request_parts(
        instruction: str, knowledge: CRMSKnowledgeBase,
        procedures: CRMSModel) -> tuple[str, str, str] | None:
    """Resolve a bounded composition from explicit, independently licensed parts.

    This does not infer operation synonyms or relation paraphrases. It accepts
    a request only when the text contains one unambiguous integer set, one
    subject/relation pair already represented in the knowledge base, and one
    learned procedure phrase.
    """
    learned_phrases = procedures.learned_procedure_phrases()
    if not any(re.search(
            rf"(?<!\w){re.escape(phrase).replace(r'\ ', r'\s+')}(?!\w)",
            instruction, flags=re.IGNORECASE)
            for phrase in learned_phrases):
        return None

    value_spans = list(re.finditer(_INTEGER_LIST, instruction,
                                   flags=re.IGNORECASE))
    if len(value_spans) != 1:
        return None
    value_span = value_spans[0]
    values_text = value_span.group(0)
    values = re.findall(r"-?\d+", values_text)
    all_numbers = re.findall(r"-?\d+", instruction)
    if not values or len(values) > 32 or len(values) != len(all_numbers):
        return None

    claims: set[tuple[str, str]] = set()
    facts = (*knowledge.facts(), *knowledge.negative_facts())
    folded_instruction = instruction.casefold()
    mentioned_subjects = {
        fact.subject for fact in facts
        if fact.subject.casefold() in folded_instruction
    }
    claims.update((fact.subject, fact.relation) for fact in facts
                  if fact.subject in mentioned_subjects)
    for rule in knowledge._inference_rules.values():
        claims.update((subject, rule.conclusion_relation)
                      for subject in mentioned_subjects)
    claims = {
        (subject, relation) for subject, relation in claims
        if re.search(
            rf"(?<!\w){re.escape(f'{subject} {relation}').replace(r'\ ', r'\s+')}(?!\w)",
            instruction, flags=re.IGNORECASE)
    }
    if len(claims) != 1:
        return None

    matched_phrases: set[str] = set()
    for phrase in learned_phrases:
        words = re.escape(phrase).replace(r"\ ", r"\s+")
        if re.search(rf"(?<!\w){words}(?!\w)", instruction,
                     flags=re.IGNORECASE):
            matched_phrases.add(phrase)
    if not matched_phrases:
        return None
    longest = max(len(phrase) for phrase in matched_phrases)
    selected = sorted(phrase for phrase in matched_phrases
                      if len(phrase) == longest)
    if len(selected) != 1:
        return None
    selected_phrase = selected[0]
    words = re.escape(selected_phrase).replace(r"\ ", r"\s+")
    command_occurrences = []
    for phrase_match in re.finditer(rf"(?<!\w){words}(?!\w)", instruction,
                                    flags=re.IGNORECASE):
        prefix = instruction[:phrase_match.start()].rstrip()
        if (not prefix
                or re.search(r"[,;:.!?]\s*$", prefix)
                or re.search(r"\b(?:please|then|and|now|can you|could you|"
                             r"i need to|i want to)\s*$", prefix,
                             flags=re.IGNORECASE)):
            command_occurrences.append(phrase_match)
    if not command_occurrences:
        return None
    subject, relation = next(iter(claims))
    return values_text, f"{subject} {relation}", selected_phrase


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
    if match is not None:
        values_text = match.group("values")
        claim_text = match.group("claim")
        procedure_text = match.group("procedure")
    else:
        generic_parts = _generic_request_parts(
            instruction, knowledge, procedures)
        if generic_parts is None:
            return None
        values_text, claim_text, procedure_text = generic_parts
    values = tuple(int(value) for value in
                   re.findall(r"-?\d+", values_text))
    if not values or len(values) > 32:
        return ReasonedListComposition(
            "unsupported", "I can check a finite list of 1 to 32 integer values.")
    parsed = _relation_and_subject(claim_text, knowledge)
    language_evidence: tuple[dict[str, Any], ...] = ()
    if parsed is None:
        learned_match = knowledge.match_fact_pattern_relation_claim(
            claim_text)
        if learned_match is not None:
            parsed = (learned_match["subject"], learned_match["relation"])
            language_evidence = (learned_match,)
    if parsed is None:
        return ReasonedListComposition(
            "unsupported", "I couldn't identify one unambiguous stored relation and subject.")
    subject, relation = parsed
    procedure = _normalize_procedure_sequence(procedure_text)
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

    surface_procedure = procedure
    procedure, prediction, morphology_note = _predict_licensed_procedure(
        procedures, procedure, included)
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
    procedure_note = (
        f" Recognized the grammatical form '{morphology_note}' in "
        f"'{surface_procedure}' using the licensed procedure '{procedure}'."
        if morphology_note else "")
    if (prediction.procedure
            and prediction.procedure[-1].get("operation") == "sum_values"
            and len(output) == 1):
        answer_line = (f"Verified values satisfying the relation "
                       f"'{subject} {relation}': {included}{exclusions}. "
                       f"Their total is {output[0]}.")
    else:
        answer_line = (f"Verified values satisfying {subject} {relation}: "
                       f"{included}{exclusions}. After '{procedure}': "
                       f"{list(output)}.")
    text = (f"{answer_line} Evidence sources: {evidence}.{support_note}"
            f"{language_note}{procedure_note}")
    return ReasonedListComposition(
        "answered", text, subject, relation, values, tuple(included),
        tuple(negative), (), output, procedure, tuple(sorted(sources)), checks,
        tuple(negative_evidence), tuple(verified_proofs),
        procedure_records, language_evidence)
