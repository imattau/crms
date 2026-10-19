"""Report-only discovery of relation-schema candidates from explicit facts.

This first pass proposes symmetry only when the store contains explicit reverse
positive evidence. Explicit negative reverse facts are counterexamples; missing
reverse facts remain unknown under the open-world policy. Candidates are never
installed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from crms_support_report import independent_origin_support
from crms_text import tokens


@dataclass(frozen=True)
class RelationSchemaCandidate:
    relation: str
    schema_type: str
    qualifiers: tuple[tuple[str, str], ...]
    positive_examples: tuple[dict[str, Any], ...]
    negative_examples: tuple[dict[str, Any], ...]
    unknown_reverse_pairs: int
    status: str
    independent_sources: tuple[str, ...] = ()
    source_basis: str = "source documents"


@dataclass(frozen=True)
class RelationSchemaDiscovery:
    complete: bool
    candidates: tuple[RelationSchemaCandidate, ...]
    expansions: int


@dataclass(frozen=True)
class RelationSchemaValidation:
    status: str
    positive_examples: tuple[dict[str, Any], ...]
    negative_examples: tuple[dict[str, Any], ...]
    unknown_reverse_pairs: int
    complete: bool
    expansions: int
    independent_sources: tuple[str, ...] = ()
    label_coverage: float | None = None
    precision_lower_bound: float | None = None


@dataclass(frozen=True)
class RelationSchemaReview:
    candidate: RelationSchemaCandidate
    validation: RelationSchemaValidation


@dataclass(frozen=True)
class RelationSchemaReviewResult:
    complete: bool
    reviews: tuple[RelationSchemaReview, ...]
    expansions: int


def _key(value: str) -> tuple[str, ...]:
    return tokens(re.sub(r"[-‐‑‒–—]", " ", value))


def _qualifiers(value: Any) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    pairs = value.items() if isinstance(value, Mapping) else value
    normalized = []
    if not isinstance(pairs, Iterable):
        return ()
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            continue
        name, qualifier_value = pair
        normalized.append((_key(str(name)), _key(str(qualifier_value))))
    return tuple(sorted(normalized))


def _fact(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (row.get("subject"), row.get("relation"), row.get("object"))
    if not all(isinstance(value, str) and value.strip() for value in fields):
        raise ValueError("schema discovery facts need non-empty triple fields")
    raw_sources = row.get("sources", ())
    if isinstance(raw_sources, str):
        sources = (raw_sources,) if raw_sources else ()
    elif isinstance(raw_sources, (tuple, list, set)):
        sources = tuple(sorted({str(source) for source in raw_sources
                                if str(source).strip()}))
    else:
        sources = ()
    raw_qualifiers = row.get("qualifiers", ())
    qualifier_pairs = (
        raw_qualifiers.items() if isinstance(raw_qualifiers, Mapping)
        else raw_qualifiers if isinstance(raw_qualifiers, (tuple, list))
        else ())
    qualifiers = tuple(sorted((str(name), str(value))
                              for name, value in qualifier_pairs))
    return {"subject": fields[0].strip(), "relation": fields[1].strip(),
            "object": fields[2].strip(), "sources": sources,
            "qualifiers": qualifiers}


def discover_relation_schema_candidates(
        facts: Iterable[Mapping[str, Any]], *,
        negative_facts: Iterable[Mapping[str, Any]] = (),
        min_support: int = 2, max_expansions: int = 100_000,
        research_index: Any | None = None,
        origin_map: Mapping[str, str] | None = None
        ) -> RelationSchemaDiscovery:
    """Find symmetric-relation hypotheses from explicit reciprocal evidence.

    Each support is one unordered entity pair with positive evidence in both
    directions. A counterexample is a positive direction paired with an
    explicit negative in the reverse direction. An absent reverse statement is
    counted as unknown, never as support or contradiction.
    """
    for name, value in (("min_support", min_support),
                        ("max_expansions", max_expansions)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")

    positives = [_fact(row) for row in facts]
    negatives = [_fact(row) for row in negative_facts]
    positives.sort(key=lambda row: (_key(row["relation"]),
                                    _key(row["subject"]),
                                    _key(row["object"]),
                                    _qualifiers(row["qualifiers"]),
                                    row["sources"]))
    negatives.sort(key=lambda row: (_key(row["relation"]),
                                    _key(row["subject"]),
                                    _key(row["object"]),
                                    _qualifiers(row["qualifiers"]),
                                    row["sources"]))

    positive_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    negative_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    displays: dict[tuple[str, ...], str] = {}
    for row, target in [(row, positive_index) for row in positives] + [
            (row, negative_index) for row in negatives]:
        relation = _key(row["relation"])
        subject = _key(row["subject"])
        obj = _key(row["object"])
        scope = _qualifiers(row["qualifiers"])
        displays.setdefault(relation, row["relation"])
        key = (subject, relation, obj, scope)
        previous = target.get(key)
        if previous is None:
            target[key] = row
        else:
            target[key] = dict(previous, sources=tuple(sorted(
                set(previous["sources"]) | set(row["sources"]))))

    groups: dict[tuple[tuple[str, ...], tuple[Any, ...]], dict[str, Any]] = {}
    expansions = 0
    complete = True
    processed_pairs: dict[tuple[tuple[str, ...], tuple[Any, ...]],
                          set[tuple[tuple[str, ...], tuple[str, ...]]]] = {}
    for subject, relation, obj, scope in sorted(positive_index):
        if subject == obj:
            continue
        group_key = (relation, scope)
        group = groups.setdefault(group_key, {
            "support": {}, "counterexamples": {}, "unknown": set()})
        pair = (min(subject, obj), max(subject, obj))
        seen = processed_pairs.setdefault(group_key, set())
        if pair in seen:
            continue
        if expansions >= max_expansions:
            complete = False
            break
        expansions += 1
        seen.add(pair)
        left, right = pair
        positive_left_right = positive_index.get(
            (left, relation, right, scope))
        positive_right_left = positive_index.get(
            (right, relation, left, scope))
        negative_left_right = negative_index.get(
            (left, relation, right, scope))
        negative_right_left = negative_index.get(
            (right, relation, left, scope))
        if positive_left_right is not None and positive_right_left is not None:
            group["support"][pair] = {
                "first": positive_left_right,
                "conclusion": positive_right_left}
        counterexamples = []
        if positive_left_right is not None and negative_right_left is not None:
            counterexamples.append({
                "first": positive_left_right,
                "conclusion": negative_right_left})
        if positive_right_left is not None and negative_left_right is not None:
            counterexamples.append({
                "first": positive_right_left,
                "conclusion": negative_left_right})
        if counterexamples:
            group["counterexamples"][pair] = counterexamples[0]
        if ((positive_left_right is not None) != (positive_right_left is not None)
                and ((positive_left_right is not None
                      and negative_right_left is None)
                     or (positive_right_left is not None
                         and negative_left_right is None))):
            group["unknown"].add(pair)

    candidates = []
    for (relation, scope), group in sorted(groups.items()):
        support = tuple(group["support"][key]
                        for key in sorted(group["support"]))
        if len(support) < min_support:
            continue
        counterexamples = tuple(group["counterexamples"][key]
                                for key in sorted(group["counterexamples"]))
        sources = [source for example in support
                   for field in ("first", "conclusion")
                   for source in example[field]["sources"]]
        independent, available, _copied = independent_origin_support(
            sources, research_index=research_index, origin_map=origin_map)
        if not complete:
            status = "incomplete"
        elif counterexamples:
            status = "contradicted"
        elif available and len(independent) >= min_support:
            status = "uncontradicted"
        else:
            status = "insufficient-independent-sources"
        try:
            index_has_documents = (research_index is not None
                                   and research_index.document_count() > 0)
        except (AttributeError, TypeError, ValueError, OSError):
            index_has_documents = research_index is not None
        source_basis = ("independent origins"
                        if origin_map is not None or index_has_documents
                        else "source documents")
        candidates.append(RelationSchemaCandidate(
            displays.get(relation, " ".join(relation)), "symmetric",
            tuple((" ".join(name), " ".join(value))
                  for name, value in scope), support, counterexamples,
            len(group["unknown"]), status, independent, source_basis))

    candidates.sort(key=lambda candidate: (
        _key(candidate.relation), candidate.qualifiers,
        candidate.status, -len(candidate.positive_examples)))
    return RelationSchemaDiscovery(complete, tuple(candidates), expansions)


def _wilson_lower_bound(successes: int, failures: int, *,
                        z: float = 1.96) -> float | None:
    total = successes + failures
    if total == 0:
        return None
    rate = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    center = rate + z2 / (2.0 * total)
    margin = z * ((rate * (1.0 - rate) / total)
                  + (z2 / (4.0 * total * total))) ** 0.5
    return max(0.0, (center - margin) / denominator)


def validate_relation_schema_candidate(
        candidate: RelationSchemaCandidate, *,
        validation_facts: Iterable[Mapping[str, Any]],
        validation_negative_facts: Iterable[Mapping[str, Any]],
        min_positive_examples: int = 2,
        min_label_coverage: float = 0.5,
        min_precision_lower_bound: float = 0.25,
        max_expansions: int = 100_000,
        research_index: Any | None = None,
        origin_map: Mapping[str, str] | None = None
        ) -> RelationSchemaValidation:
    """Validate a symmetric candidate only on a disjoint source partition."""
    for name, value in (("min_positive_examples", min_positive_examples),
                        ("max_expansions", max_expansions)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    for name, value in (("min_label_coverage", min_label_coverage),
                        ("min_precision_lower_bound",
                         min_precision_lower_bound)):
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not 0.0 <= value <= 1.0):
            raise ValueError(f"{name} must be between 0 and 1")
    if candidate.status == "incomplete":
        return RelationSchemaValidation("training-incomplete", (), (), 0,
                                        False, 0)
    if candidate.negative_examples:
        return RelationSchemaValidation("training-contradicted", (), (), 0,
                                        True, 0)
    if candidate.status != "uncontradicted":
        return RelationSchemaValidation(
            "training-insufficient-independent-sources", (), (), 0, True, 0)

    relation = _key(candidate.relation)
    scope = _qualifiers(candidate.qualifiers)
    train_keys = set()
    for example in candidate.positive_examples:
        for field in ("first", "conclusion"):
            row = _fact(example[field])
            train_keys.add((_key(row["subject"]), _key(row["relation"]),
                            _key(row["object"]), _qualifiers(row["qualifiers"])))
    positives = []
    negatives = []
    for raw in validation_facts:
        row = _fact(raw)
        key = (_key(row["subject"]), _key(row["relation"]),
               _key(row["object"]), _qualifiers(row["qualifiers"]))
        if key in train_keys:
            return RelationSchemaValidation("overlap", (), (), 0, True, 0)
        if key[1] == relation and key[3] == scope:
            positives.append(row)
    for raw in validation_negative_facts:
        row = _fact(raw)
        key = (_key(row["subject"]), _key(row["relation"]),
               _key(row["object"]), _qualifiers(row["qualifiers"]))
        if key in train_keys:
            return RelationSchemaValidation("overlap", (), (), 0, True, 0)
        if key[1] == relation and key[3] == scope:
            negatives.append(row)

    positive_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    negative_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row, target in ([(row, positive_index) for row in positives]
                        + [(row, negative_index) for row in negatives]):
        key = (_key(row["subject"]), _key(row["relation"]),
               _key(row["object"]), _qualifiers(row["qualifiers"]))
        target[key] = row

    positive_examples: dict[tuple[Any, ...], dict[str, Any]] = {}
    negative_examples: dict[tuple[Any, ...], dict[str, Any]] = {}
    unknown: set[tuple[Any, ...]] = set()
    seen: set[tuple[Any, ...]] = set()
    expansions = 0
    complete = True
    for subject, row_relation, obj, row_scope in sorted(positive_index):
        if subject == obj:
            continue
        pair = (min(subject, obj), max(subject, obj))
        if pair in seen:
            continue
        if expansions >= max_expansions:
            complete = False
            break
        expansions += 1
        seen.add(pair)
        left, right = pair
        positive_lr = positive_index.get((left, row_relation, right, row_scope))
        positive_rl = positive_index.get((right, row_relation, left, row_scope))
        negative_lr = negative_index.get((left, row_relation, right, row_scope))
        negative_rl = negative_index.get((right, row_relation, left, row_scope))
        if positive_lr is not None and positive_rl is not None:
            positive_examples[pair] = {
                "first": positive_lr, "conclusion": positive_rl}
        if positive_lr is not None and negative_rl is not None:
            negative_examples[pair] = {
                "first": positive_lr, "conclusion": negative_rl}
        elif positive_rl is not None and negative_lr is not None:
            negative_examples[pair] = {
                "first": positive_rl, "conclusion": negative_lr}
        if ((positive_lr is not None) != (positive_rl is not None)
                and ((positive_lr is not None and negative_rl is None)
                     or (positive_rl is not None and negative_lr is None))):
            unknown.add(pair)

    ordered_positive = tuple(positive_examples[key]
                             for key in sorted(positive_examples))
    ordered_negative = tuple(negative_examples[key]
                             for key in sorted(negative_examples))
    labeled_pairs = set(positive_examples) | set(negative_examples)
    label_total = len(labeled_pairs) + len(unknown)
    label_coverage = (len(labeled_pairs) / label_total if label_total else None)
    precision_lcb = _wilson_lower_bound(
        len(positive_examples), len(negative_examples))
    sources = [source for example in ordered_positive
               for field in ("first", "conclusion")
               for source in example[field]["sources"]]
    independent, available, _copied = independent_origin_support(
        sources, research_index=research_index, origin_map=origin_map)
    if not complete:
        status = "incomplete"
    elif ordered_negative:
        status = "contradicted"
    elif len(ordered_positive) < min_positive_examples:
        status = "insufficient"
    elif label_coverage is not None and label_coverage < min_label_coverage:
        status = "low-coverage"
    elif precision_lcb is None or precision_lcb < min_precision_lower_bound:
        status = "low-confidence"
    elif not available or len(independent) < min_positive_examples:
        status = "insufficient-independent-sources"
    else:
        status = "validated"
    return RelationSchemaValidation(
        status, ordered_positive, ordered_negative, len(unknown), complete,
        expansions, independent, label_coverage, precision_lcb)


def review_relation_schema_candidates(
        facts: Iterable[Mapping[str, Any]], *,
        negative_facts: Iterable[Mapping[str, Any]] = (),
        validation_source_prefix: str,
        min_support: int = 2, min_validation_support: int = 2,
        min_label_coverage: float = 0.5,
        min_precision_lower_bound: float = 0.25,
        max_expansions: int = 100_000,
        research_index: Any | None = None,
        origin_map: Mapping[str, str] | None = None
        ) -> RelationSchemaReviewResult:
    """Discover on non-holdout facts and report source-separated validation."""
    if not isinstance(validation_source_prefix, str) or not validation_source_prefix.strip():
        raise ValueError("validation_source_prefix must be non-empty")
    for name, value in (("min_support", min_support),
                        ("min_validation_support", min_validation_support),
                        ("max_expansions", max_expansions)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    for name, value in (("min_label_coverage", min_label_coverage),
                        ("min_precision_lower_bound",
                         min_precision_lower_bound)):
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not 0.0 <= value <= 1.0):
            raise ValueError(f"{name} must be between 0 and 1")
    prefix = validation_source_prefix.strip()
    all_positive = [_fact(row) for row in facts]
    all_negative = [_fact(row) for row in negative_facts]

    def partition(rows):
        training, validation = [], []
        for row in rows:
            heldout = any(source.startswith(prefix) for source in row["sources"])
            (validation if heldout else training).append(row)
        return training, validation

    training_positive, validation_positive = partition(all_positive)
    training_negative, validation_negative = partition(all_negative)
    discovery = discover_relation_schema_candidates(
        training_positive, negative_facts=training_negative,
        min_support=min_support, max_expansions=max_expansions,
        research_index=research_index, origin_map=origin_map)
    remaining = max_expansions - discovery.expansions
    reviews = []
    total_expansions = discovery.expansions
    complete = discovery.complete
    for candidate in discovery.candidates:
        if remaining < 1:
            validation = RelationSchemaValidation(
                "incomplete", (), (), 0, False, 0)
        else:
            validation = validate_relation_schema_candidate(
                candidate, validation_facts=validation_positive,
                validation_negative_facts=validation_negative,
                min_positive_examples=min_validation_support,
                min_label_coverage=min_label_coverage,
                min_precision_lower_bound=min_precision_lower_bound,
                max_expansions=remaining, research_index=research_index,
                origin_map=origin_map)
            remaining -= validation.expansions
            total_expansions += validation.expansions
        complete = complete and validation.complete
        reviews.append(RelationSchemaReview(candidate, validation))
    return RelationSchemaReviewResult(
        complete, tuple(reviews), total_expansions)
