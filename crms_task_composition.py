"""Bounded composition of proof-checked relation results and learned procedures.

The parser accepts a deliberately explicit finite-set request. Relation claims
are proved against the knowledge base; only complete independently verified
positive proofs are passed to the learned list procedure. Unknown or conflicting
members prevent a final result.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from typing import Any

from crms_knowledge import (
    CRMSKnowledgeBase, _analyze_predicate_spelling,
)
from crms_model import CRMSModel
from crms_rule_proof import verify_inference_proof
from crms_request_frames import RequestFrameStore
from crms_actions import (
    ApplyLearnedProcedureAction, SelectVerifiedPositiveAction,
)
from crms_planner import (
    ActionRegistry, ExecutionContext, PlanExecutor, Verification, check_for,
)
from crms_tasks import Plan, Step, TaskRequest, request_id


_INTEGER_LIST = (
    r"-?\d+(?:\s*,\s*-?\d+)*(?:\s*,?\s+and\s+-?\d+)?")
_FILTER_AND_SUM_QUESTION = re.compile(
    rf"^\s*Which\s+values?\s+in\s+(?P<values>{_INTEGER_LIST})\s+"
    r"does\s+(?P<claim>.+?),\s*and\s+what\s+do\s+they\s+"
    r"sum\s+to\s*[.!?]*\s*$", re.IGNORECASE)
_WH_TOTAL_QUESTION = re.compile(
    rf"^\s*What\s+is\s+the\s+total\s+of\s+(?:the\s+)?values?\s+"
    r"(?:that\s+|which\s+)?(?P<claim>.+?)\s+among\s+"
    rf"(?P<values>{_INTEGER_LIST})\s*[.!?]*\s*$", re.IGNORECASE)
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


def is_explicit_aggregate_question(message: str) -> bool:
    """Identify a linked natural-language aggregate request kept as one task."""
    return any(pattern.fullmatch(message) is not None for pattern in (
        _FILTER_AND_SUM_QUESTION, _WH_TOTAL_QUESTION))


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


def _canonicalize_procedure_phrase(procedures: CRMSModel,
                                   instruction: str) -> str:
    """Use the stored spelling of a learned phrase when one matches exactly."""
    text = _normalize_procedure_sequence(instruction)
    learned = {
        " ".join(phrase.casefold().split()): phrase
        for phrase in procedures.learned_procedure_phrases()
    }
    parts = re.split(r"\s+then\s+", text, flags=re.IGNORECASE)
    canonical = []
    for part in parts:
        key = " ".join(part.casefold().split())
        canonical.append(learned.get(key, part.strip()))
    return " then ".join(canonical)


def _predict_licensed_procedure(procedures: CRMSModel, instruction: str,
                                values: list[int], *,
                                record_use: bool = True
                                ) -> tuple[str, Any, str | None]:
    """Use a licensed phrase, allowing a checked gerund-to-base-form mapping.

    Each morphology candidate is still passed through the ordinary procedure
    learner. This changes only the grammatical form of an operation token; it
    cannot authorize a procedure the model does not already support.
    """
    direct = procedures.predict(instruction, values, record_use=False)
    if direct.status == "ok":
        if record_use:
            procedures.predict(instruction, values, record_use=True)
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

    licensed = [(candidate, procedures.predict(
        candidate, values, record_use=False))
                for candidate in sorted(candidates)]
    licensed = [(candidate, prediction)
                for candidate, prediction in licensed
                if prediction.status == "ok" and prediction.output is not None]
    if len(licensed) != 1:
        return instruction, direct, None
    candidate, prediction = licensed[0]
    if record_use:
        procedures.predict(candidate, values, record_use=True)
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
    request_frame_id: str | None = None


@dataclass(frozen=True)
class VerifiedFilterRequest:
    values: tuple[int, ...]
    procedure: str
    subject: str
    relation: str
    language_evidence: tuple[dict[str, Any], ...] = ()


def _parse_verified_filter_request(
        instruction: str, knowledge: CRMSKnowledgeBase,
        procedures: CRMSModel
        ) -> tuple[VerifiedFilterRequest | None, ReasonedListComposition | None]:
    """Resolve the explicit request frame without executing it."""
    linked_aggregate = next((pattern.fullmatch(instruction)
                             for pattern in (_FILTER_AND_SUM_QUESTION,
                                             _WH_TOTAL_QUESTION)
                             if pattern.fullmatch(instruction) is not None),
                            None)
    if linked_aggregate is not None:
        values_text = linked_aggregate.group("values")
        claim_text = linked_aggregate.group("claim")
        procedure_text = "sum every value"
    else:
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
                return None, None
            values_text, claim_text, procedure_text = generic_parts
    values = tuple(int(value) for value in
                   re.findall(r"-?\d+", values_text))
    if not values or len(values) > 32:
        return None, ReasonedListComposition(
            "unsupported", "I can check a finite list of 1 to 32 integer values.")
    language_evidence: tuple[dict[str, Any], ...] = ()
    learned_match = knowledge.match_fact_pattern_relation_claim(claim_text)
    if learned_match is not None:
        parsed = (learned_match["subject"], learned_match["relation"])
        language_evidence = (learned_match,)
    else:
        parsed = _relation_and_subject(claim_text, knowledge)
    if parsed is None:
        return None, ReasonedListComposition(
            "unsupported", "I couldn't identify one unambiguous stored relation and subject.")
    subject, relation = parsed
    procedure = _canonicalize_procedure_phrase(procedures, procedure_text)
    return VerifiedFilterRequest(
        values=values,
        procedure=procedure,
        subject=subject,
        relation=relation,
        language_evidence=language_evidence,
    ), None


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
        "request_frame_id": result.request_frame_id,
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
        procedures: CRMSModel,
        frames: RequestFrameStore | None = None) -> tuple[str, str]:
    """Re-run the exact request before presenting a stored composition as current."""
    request = record.get("request", "")
    frame_id = record.get("request_frame_id")
    if frames is not None and frame_id:
        current = compose_verified_filter_via_frames(
            request, knowledge, procedures, frames)
        if current is None or current.request_frame_id != frame_id:
            return ("stale",
                    "the licensed request frame no longer matches this request")
    else:
        current = compose_verified_filter(request, knowledge, procedures)
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
    for relation in relations:
        relation_words = tuple(re.findall(r"\w+", relation.casefold()))
        suffix = r"\s+".join(re.escape(word) for word in relation_words)
        match = re.search(r"(?<!\w)" + suffix + r"\s*$", claim,
                          flags=re.IGNORECASE)
        if match is not None:
            subject = claim[:match.start()].strip()
            subject = re.sub(r"\s+is\s+(?:a|an)\s*$", "", subject,
                             flags=re.IGNORECASE).strip()
            if subject:
                matches.add((subject, relation))
            continue
        if len(relation_words) == 1:
            predicate = re.search(r"(?P<word>\w+)\s*$", claim)
            if predicate is None:
                continue
            surface = predicate.group("word").casefold()
            canonical = relation_words[0]
            inflected = (_analyze_predicate_spelling(surface, canonical)
                         or _analyze_predicate_spelling(canonical, surface))
            if inflected is None:
                continue
            subject = claim[:predicate.start()].strip()
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
    subject/relation pair already represented in the knowledge base, and a
    learned procedure or sequence of learned procedure phrases.
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
    def is_command_occurrence(phrase_match: re.Match[str]) -> bool:
        prefix = instruction[:phrase_match.start()].rstrip()
        return (not prefix
                or re.search(r"[,;:.!?]\s*$", prefix) is not None
                or re.search(r"\b(?:please|then|and|now|can you|could you|"
                             r"i need to|i want to)\s*$", prefix,
                             flags=re.IGNORECASE) is not None)

    matched_phrases: set[str] = set()
    phrase_occurrences: list[tuple[str, re.Match[str]]] = []
    command_occurrences: list[tuple[str, re.Match[str]]] = []
    for phrase in learned_phrases:
        words = re.escape(phrase).replace(r"\ ", r"\s+")
        for phrase_match in re.finditer(
                rf"(?<!\w){words}(?!\w)", instruction,
                flags=re.IGNORECASE):
            matched_phrases.add(phrase)
            phrase_occurrences.append((phrase, phrase_match))
            if is_command_occurrence(phrase_match):
                command_occurrences.append((phrase, phrase_match))
    if not matched_phrases or not command_occurrences:
        return None
    command_occurrences.sort(
        key=lambda item: (item[1].start(), -item[1].end(), -len(item[0])))
    procedure_start = command_occurrences[0][1].start()
    first_phrase = max(
        (phrase for phrase, match in phrase_occurrences
         if match.start() == procedure_start), key=len)
    first_phrase_end = max(
        match.end() for phrase, match in phrase_occurrences
        if phrase == first_phrase and match.start() == procedure_start)
    later_command_start = any(
        match.start() > procedure_start for _phrase, match in command_occurrences)
    trailing_text = instruction[first_phrase_end:].strip(" \t,;:.!?")
    trailing_connector = re.match(
        r"^(?:and|then|but|after)\b", trailing_text, flags=re.IGNORECASE)
    multiple_operations = later_command_start or trailing_connector is not None
    procedure_text = (
        instruction[procedure_start:].strip(" \t,;:.!?")
        if multiple_operations else first_phrase)

    # A relation phrase explicitly licensed from cited examples may appear
    # between the finite value set and the operation (for example, "Nia can
    # reach"). Recover it from that clause using the same grounded alignment
    # API used for direct relation claims. This does not admit a lexical
    # synonym: an unlicensed phrase still produces no claim and abstains.
    claim_region = instruction[value_span.end():procedure_start]
    claim_region = re.sub(
        r"^\s*(?:(?:to|keep|return)\s+)?(?:only\s+)?(?:the\s+)?"
        r"values?\s+(?:(?:that|which)\s+)?", "", claim_region,
        flags=re.IGNORECASE)
    claim_region = re.sub(
        r"\s*[,;]?\s*(?:(?:and\s+)?then|and)\s*$", "", claim_region,
        flags=re.IGNORECASE).strip(" \t,;:")
    licensed_claim = None
    if claim_region:
        aligned = knowledge.match_fact_pattern_relation_claim(claim_region)
        if (aligned is not None
                and aligned.get("subject") in mentioned_subjects):
            claims.add((aligned["subject"], aligned["relation"]))
            licensed_claim = claim_region
    if len(claims) != 1:
        return None
    subject, relation = next(iter(claims))
    # Keep the observed surface for the normal resolver to attach the
    # alignment's source evidence to the final composition record.
    claim_text = licensed_claim or f"{subject} {relation}"
    return values_text, claim_text, procedure_text


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


def _render_composition_text(
        *, subject: str, relation: str, included: list[int],
        negative: list[int], output: tuple[int, ...], procedure: str,
        surface_procedure: str, morphology_note: str | None,
        sources: set[str], procedure_records: tuple[dict[str, Any], ...],
        language_evidence: tuple[dict[str, Any], ...],
        prediction_procedure: list[dict[str, Any]] | None) -> str:
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
    if (prediction_procedure
            and prediction_procedure[-1].get("operation") == "sum_values"
            and len(output) == 1):
        answer_line = (f"Verified values satisfying the relation "
                       f"'{subject} {relation}': {included}{exclusions}. "
                       f"Their total is {output[0]}.")
    elif (prediction_procedure
          and prediction_procedure[-1].get("operation") == "count_values"
          and len(prediction_procedure) == 1 and len(output) == 1):
        answer_line = (f"There are {output[0]} listed entries satisfying "
                       f"the relation '{subject} {relation}'{exclusions}.")
    else:
        answer_line = (f"Verified values satisfying {subject} {relation}: "
                       f"{included}{exclusions}. After '{procedure}': "
                       f"{list(output)}.")
    return (f"{answer_line} Evidence sources: {evidence}.{support_note}"
            f"{language_note}{procedure_note}")


def compose_verified_filter(instruction: str, knowledge: CRMSKnowledgeBase,
                            procedures: CRMSModel) -> ReasonedListComposition | None:
    """Apply a learned list procedure to a finite, fully classified value set.

    Return ``None`` when the user input is outside this narrow request frame.
    Unknown, contradictory, incomplete, or unverifiable members cause an
    abstention rather than silently filtering away a possible value.
    """
    request, early = _parse_verified_filter_request(
        instruction, knowledge, procedures)
    if early is not None:
        return early
    if request is None:
        return None
    values = request.values
    subject, relation = request.subject, request.relation
    procedure = request.procedure
    language_evidence = request.language_evidence
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
    text = _render_composition_text(
        subject=subject, relation=relation, included=included,
        negative=negative, output=output, procedure=procedure,
        surface_procedure=surface_procedure,
        morphology_note=morphology_note, sources=sources,
        procedure_records=procedure_records,
        language_evidence=language_evidence,
        prediction_procedure=prediction.procedure)
    return ReasonedListComposition(
        "answered", text, subject, relation, values, tuple(included),
        tuple(negative), (), output, procedure, tuple(sorted(sources)), checks,
        tuple(negative_evidence), tuple(verified_proofs),
        procedure_records, language_evidence)


def _select_evidence_parts(evidence):
    """Extract proofs, negative facts, and sources from selection evidence."""
    proofs: list[dict[str, Any]] = []
    negative_facts: list[dict[str, Any]] = []
    sources: set[str] = set()
    for ref in evidence:
        if ref.kind == "proof":
            proof = ref.detail.get("proof")
            if isinstance(proof, dict):
                if proof not in proofs:
                    proofs.append(proof)
                sources.update(_proof_sources(proof))
            if ref.source:
                sources.add(str(ref.source))
        elif ref.kind == "fact" and ref.detail.get("negative"):
            fact = ref.detail.get("fact")
            if isinstance(fact, dict):
                if fact not in negative_facts:
                    negative_facts.append(fact)
                sources.update(str(source) for source in fact.get("sources", ())
                               if source)
            if ref.source:
                sources.add(str(ref.source))
    return tuple(proofs), tuple(negative_facts), sources


def _procedure_evidence_parts(evidence, sources: set[str]):
    ref = next((item for item in evidence if item.kind == "procedure"), None)
    if ref is None:
        return None, ()
    records = tuple(ref.detail.get("examples", ()) or ())
    for record in records:
        for key in ("source_id", "instruction_source_id"):
            value = str(record.get(key) or "")
            if value:
                sources.add(value)
    return ref, records


def _composition_from_plan(
        request: VerifiedFilterRequest, result,
        ) -> ReasonedListComposition:
    """Translate a typed plan result back into the chat-facing record."""
    subject, relation = request.subject, request.relation
    sources: set[str] = set()
    for row in request.language_evidence:
        sources.update(str(source) for source in row.get("sources", ())
                       if source)

    if result.status == "ok":
        select_step, procedure_step = result.steps[0], result.steps[1]
        included = list(select_step.output or ())
        negative = list(select_step.metadata.get("excluded", ()))
        proofs, negative_facts, select_sources = _select_evidence_parts(
            select_step.evidence)
        sources.update(select_sources)
        procedure_ref, procedure_records = _procedure_evidence_parts(
            procedure_step.evidence, sources)
        if procedure_ref is None:
            return ReasonedListComposition(
                "unsupported",
                "The procedure step produced no evidence record.",
                subject, relation, request.values, tuple(included),
                tuple(negative), procedure=request.procedure,
                evidence_sources=tuple(sorted(sources)),
                proof_checks=int(select_step.metadata.get("checks", 0)),
                evidence=negative_facts, inference_proofs=proofs,
                language_evidence=request.language_evidence)
        licensed = str(procedure_ref.detail.get(
            "licensed_instruction") or request.procedure)
        morphology_note = procedure_ref.detail.get("morphology_note")
        output = tuple(procedure_step.output or ())
        text = _render_composition_text(
            subject=subject, relation=relation, included=included,
            negative=negative, output=output, procedure=licensed,
            surface_procedure=request.procedure,
            morphology_note=morphology_note, sources=sources,
            procedure_records=procedure_records,
            language_evidence=request.language_evidence,
            prediction_procedure=procedure_ref.detail.get("procedure"))
        return ReasonedListComposition(
            "answered", text, subject, relation, request.values,
            tuple(included), tuple(negative), (), output, licensed,
            tuple(sorted(sources)),
            int(select_step.metadata.get("checks", 0)),
            negative_facts, proofs, procedure_records,
            request.language_evidence)

    failed = result.steps[-1] if result.steps else None
    select_step = (
        failed if failed is not None and failed.step_id == "select"
        else next((step for step in result.steps
                   if step.step_id == "select" and step.status == "ok"), None)
    )
    evidence_step = (
        failed if failed is not None
        and failed.reason_code in {"unknown_values", "conflict"}
        else select_step
    )
    if evidence_step is not None:
        proofs, negative_facts, select_sources = _select_evidence_parts(
            evidence_step.evidence)
        sources.update(select_sources)
        checks = int(evidence_step.metadata.get("checks", 0))
        included = tuple(evidence_step.metadata.get("included", ()))
        negative = tuple(evidence_step.metadata.get("excluded", ()))
    else:
        proofs, negative_facts, checks = (), (), 0
        included, negative = (), ()

    if failed is not None and failed.reason_code == "unknown_values":
        unresolved = tuple(failed.metadata.get("unresolved", ()))
        incomplete = tuple(failed.metadata.get("incomplete", ()))
        unresolved = (*unresolved, *incomplete)
        rendered = ", ".join(map(str, sorted(set(unresolved))))
        return ReasonedListComposition(
            "unknown",
            f"I can't determine whether {rendered} satisfy {subject} "
            f"{relation}; I did not run the procedure on a partial set.",
            subject, relation, request.values, included, negative,
            unresolved, procedure=request.procedure,
            evidence_sources=tuple(sorted(sources)), proof_checks=checks,
            evidence=negative_facts, inference_proofs=proofs,
            language_evidence=request.language_evidence)

    if failed is not None and failed.reason_code == "conflict":
        value = failed.metadata.get("conflict_value")
        rendered = "" if value is None else f" {value}"
        return ReasonedListComposition(
            "conflict",
            f"I found both positive and negative support for {subject} "
            f"{relation}{rendered}; I did not run the procedure. Evidence "
            f"sources: {', '.join(sorted(sources))}.",
            subject, relation, request.values,
            unresolved_values=(value,) if value is not None else (),
            procedure=request.procedure,
            evidence_sources=tuple(sorted(sources)), proof_checks=checks,
            evidence=negative_facts, inference_proofs=proofs,
            language_evidence=request.language_evidence)

    if failed is not None and failed.reason_code == "procedure_unresolved":
        return ReasonedListComposition(
            "unsupported_procedure",
            failed.detail or "I couldn't verify that learned list procedure.",
            subject, relation, request.values, included, negative,
            procedure=request.procedure,
            evidence_sources=tuple(sorted(sources)), proof_checks=checks,
            evidence=negative_facts, inference_proofs=proofs,
            language_evidence=request.language_evidence)

    reason = "; ".join(result.failures) or result.status
    return ReasonedListComposition(
        "unsupported", f"I couldn't verify this request: {reason}.",
        subject, relation, request.values, included, negative,
        procedure=request.procedure,
        evidence_sources=tuple(sorted(sources)), proof_checks=checks,
        evidence=negative_facts, inference_proofs=proofs,
        language_evidence=request.language_evidence)


def _execute_verified_filter_request(
        instruction: str, request: VerifiedFilterRequest,
        knowledge: CRMSKnowledgeBase, procedures: CRMSModel, *,
        goal: str = "select-then-procedure",
        provenance: dict[str, Any] | None = None,
        ) -> ReasonedListComposition:
    """Build and execute the typed plan for one resolved request."""
    select_step = Step(
        id="select",
        action="select-verified-positive",
        inputs={
            "subject": request.subject,
            "relation": request.relation,
            "values": list(request.values),
        },
        output_type="integer-list",
        check=check_for("proof"),
    )
    procedure_step = Step(
        id="procedure",
        action="apply-learned-procedure",
        inputs={
            "values": "select.output",
            "instruction": request.procedure,
        },
        output_type="integer-list",
        check=check_for("parity", ref=request.procedure),
        depends_on=("select",),
    )
    plan = Plan(
        request=TaskRequest(
            id=request_id(instruction, "verified-filter"),
            text=instruction,
            goal=goal,
            slots={
                "subject": request.subject,
                "relation": request.relation,
                "values": list(request.values),
                "procedure": request.procedure,
            },
            provenance=dict(provenance or {"parser": "explicit-frame"}),
        ),
        steps=(select_step, procedure_step),
        verification=check_for("oracle", ref="integer-list-output"),
    )

    def resolver(text: str, values: list[int], record_use: bool):
        return _predict_licensed_procedure(
            procedures, text, values, record_use=record_use)

    registry = ActionRegistry()
    registry.register(SelectVerifiedPositiveAction(knowledge))
    registry.register(ApplyLearnedProcedureAction(
        procedures, resolver=resolver))

    def check_output(plan, outputs, context):
        output = outputs.get("procedure")
        passed = (isinstance(output, list)
                  and all(isinstance(value, int)
                          and not isinstance(value, bool)
                          for value in output))
        return Verification(
            passed, "" if passed else "procedure output is not an integer list")

    result = PlanExecutor(
        registry, plan_verifier=check_output).execute(
            plan, ExecutionContext({"instruction": instruction}))
    return _composition_from_plan(request, result)


def compose_verified_filter_via_plan(
        instruction: str, knowledge: CRMSKnowledgeBase,
        procedures: CRMSModel) -> ReasonedListComposition | None:
    """Execute the explicit regex-compiled frame through the typed planner.

    Kept as the reference path for parity tests and direct diagnostics; chat
    routes composition through learned request frames.
    """
    request, early = _parse_verified_filter_request(
        instruction, knowledge, procedures)
    if early is not None:
        return early
    if request is None:
        return None
    return _execute_verified_filter_request(
        instruction, request, knowledge, procedures,
        provenance={"parser": "explicit-regex-frame"})


def compose_verified_filter_via_frames(
        instruction: str, knowledge: CRMSKnowledgeBase,
        procedures: CRMSModel, frames: RequestFrameStore,
        ) -> ReasonedListComposition | None:
    """Execute a request only when a licensed frame binds typed slots.

    Unknown wording returns ``None`` so the caller can abstain or use another
    route. Ambiguous frames never execute.
    """
    match_result = frames.match(
        instruction,
        procedure_phrases=procedures.learned_procedure_phrases())
    if match_result.status == "no_match":
        return None
    if match_result.status == "ambiguous":
        templates = "; ".join(
            match.frame.template_text() for match in match_result.matches[:3])
        return ReasonedListComposition(
            "ambiguous",
            "I found more than one licensed request frame for this wording. "
            "Please rephrase, or teach a narrower frame. Candidates: "
            + templates + ".")
    match = match_result.match
    if match is None:
        return None
    values = match.slots.get("values")
    claim = match.slots.get("claim")
    if not isinstance(values, tuple) or not isinstance(claim, str):
        return replace(
            ReasonedListComposition(
                "unsupported",
                "The licensed request frame did not bind the required values "
                "and claim slots."),
            request_frame_id=match.frame.frame_id)
    procedure_slot = match.slots.get("procedure")
    procedure_text = (match.frame.fixed_procedure
                      if match.frame.fixed_procedure is not None
                      else procedure_slot)
    if not isinstance(procedure_text, str) or not procedure_text.strip():
        return replace(
            ReasonedListComposition(
                "unsupported",
                "The licensed request frame did not bind a procedure."),
            request_frame_id=match.frame.frame_id)

    language_evidence: tuple[dict[str, Any], ...] = ()
    learned_match = knowledge.match_fact_pattern_relation_claim(claim)
    if learned_match is not None:
        parsed = (learned_match["subject"], learned_match["relation"])
        language_evidence = (learned_match,)
    else:
        parsed = _relation_and_subject(claim, knowledge)
    if parsed is None:
        return replace(
            ReasonedListComposition(
                "unsupported",
                "I couldn't identify one unambiguous stored relation and "
                "subject."),
            request_frame_id=match.frame.frame_id,
            input_values=values)
    subject, relation = parsed
    request = VerifiedFilterRequest(
        values=values,
        procedure=_canonicalize_procedure_phrase(procedures, procedure_text),
        subject=subject,
        relation=relation,
        language_evidence=language_evidence,
    )
    result = _execute_verified_filter_request(
        instruction, request, knowledge, procedures,
        goal=match.frame.goal,
        provenance={
            "parser": "learned-request-frame",
            "frame_id": match.frame.frame_id,
            "frame_template": match.frame.template_text(),
        })
    return replace(result, request_frame_id=match.frame.frame_id)
