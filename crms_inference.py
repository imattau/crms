"""Bounded backward chaining over explicit rules and typed relation schemas.

Rules have the form ``x -first-> y`` and ``y -second-> z`` therefore
``x -conclusion-> z``. Search is goal-directed and returns a proof tree whose
leaves are stored facts. A fixed transitivity schema is instantiated only for
relations with an explicit type assertion. No derived conclusion is inserted
into the source fact store.
"""

from __future__ import annotations

from collections import deque
import re
import json
from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Iterable, Mapping
from crms_text import tokens as normalized_tokens


def _key(value: str) -> tuple[str, ...]:
    return normalized_tokens(value)


def _qualifier_key(value: Any) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    if value is None:
        return ()
    pairs = value.items() if isinstance(value, Mapping) else value
    normalized = []
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError("qualifiers must be name/value pairs")
        name, qualifier_value = pair
        if not isinstance(name, str) or not isinstance(qualifier_value, str):
            raise ValueError("qualifier names and values must be text")
        key = (_key(name), _key(qualifier_value))
        if not all(key):
            raise ValueError("qualifier names and values must be searchable")
        normalized.append(key)
    if len(set(name for name, _ in normalized)) != len(normalized):
        raise ValueError("qualifier names must be unique ignoring case")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class InferenceRule:
    rule_id: str
    first_relation: str
    second_relation: str
    conclusion_relation: str
    third_relation: str | None = None
    middle_kind: str | None = None
    second_middle_kind: str | None = None


@dataclass(frozen=True)
class InferenceResult:
    status: str
    conclusion: dict[str, str] | None = None
    proofs: tuple[dict[str, Any], ...] = ()
    request: str | None = None
    expansions: int = 0
    complete: bool = True
    reason_code: str | None = None
    language_evidence: tuple[dict[str, Any], ...] = ()
    support_class: str = "none"
    lineage_count: int = 0
    source_count: int = 0
    source_documents: tuple[str, ...] = ()
    failure_kind: str | None = None
    missing_premises: tuple[dict[str, Any], ...] = ()
    limit_kind: str | None = None
    memo_hits: int = 0


def _proof_support(proofs: Iterable[Mapping[str, Any]], *,
                   contested: bool = False
                   ) -> tuple[str, int, int, tuple[str, ...]]:
    """Summarize distinct proof trees and their distinct leaf sources.

    Lineages are structural proof records, not statistical independence claims.
    """
    serialized: set[str] = set()
    sources: set[str] = set()

    def collect(node: Mapping[str, Any]) -> None:
        if node.get("kind") == "fact":
            fact = node.get("fact", {})
            if isinstance(fact, Mapping):
                raw = fact.get("sources", ())
                if isinstance(raw, (list, tuple, set)):
                    sources.update(str(item) for item in raw if str(item))
            return
        premises = node.get("premises", ())
        if isinstance(premises, (list, tuple)):
            for premise in premises:
                if isinstance(premise, Mapping):
                    collect(premise)
        kind_fact = node.get("middle_kind_fact")
        kind_facts = ([kind_fact] if isinstance(kind_fact, Mapping) else [])
        kind_facts.extend(fact for fact in node.get("middle_kind_facts", [])
                          if isinstance(fact, Mapping))
        relation_type_fact = node.get("relation_type_fact")
        if isinstance(relation_type_fact, Mapping):
            kind_facts.append(relation_type_fact)
        for fact in kind_facts:
            raw = fact.get("sources", ())
            if isinstance(raw, (list, tuple, set)):
                sources.update(str(item) for item in raw if str(item))

    for proof in proofs:
        serialized.add(json.dumps(
            proof, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
        collect(proof)
    lineage_count = len(serialized)
    support_class = ("contested" if contested else
                     "redundant" if lineage_count >= 2 else
                     "unique" if lineage_count == 1 else "none")
    source_documents = tuple(sorted(sources))
    return support_class, lineage_count, len(source_documents), source_documents


@dataclass(frozen=True)
class RuleCandidate:
    first_relation: str
    second_relation: str
    conclusion_relation: str
    positive_examples: tuple[dict[str, Any], ...]
    negative_examples: tuple[dict[str, Any], ...]
    status: str
    independent_sources: tuple[str, ...] = ()
    third_relation: str | None = None
    middle_kind: str | None = None
    second_middle_kind: str | None = None


@dataclass(frozen=True)
class RuleDiscoveryResult:
    complete: bool
    candidates: tuple[RuleCandidate, ...]
    expansions: int


@dataclass(frozen=True)
class RuleValidation:
    status: str
    positive_examples: tuple[dict[str, Any], ...]
    negative_examples: tuple[dict[str, Any], ...]
    unknown_endpoint_pairs: int
    complete: bool
    expansions: int
    independent_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleReview:
    candidate: RuleCandidate
    validation: RuleValidation | None


@dataclass(frozen=True)
class RuleReviewResult:
    complete: bool
    reviews: tuple[RuleReview, ...]
    expansions: int


@dataclass(frozen=True)
class RuleAcceptanceResult:
    accepted: bool
    review: RuleReview | None
    rule: InferenceRule | None
    request: str | None = None


def infer_relation(
        facts: Iterable[Mapping[str, Any]], rules: Iterable[InferenceRule], *,
        subject: str, relation: str, obj: str,
        negative_facts: Iterable[Mapping[str, Any]] = (),
        qualifiers: Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        verified_derived_proofs: Mapping[
            tuple[tuple[str, ...], ...], Iterable[Mapping[str, Any]]] | None = None,
        max_expansions: int = 10_000, max_depth: int = 8) -> InferenceResult:
    """Backward-chain a specified triple with proof, depth, and work bounds.

    Only facts in the exact requested qualifier scope can be proof leaves.
    Facts from different scopes are never combined.
    A verified positive proof remains usable if later alternative-proof search
    reaches a bound. Such a result is marked incomplete and cannot enter
    persistent practice memory.
    """
    for name, value in (("subject", subject), ("relation", relation), ("object", obj)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty text")
    for name, value in (("max_expansions", max_expansions), ("max_depth", max_depth)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")

    qualifier_scope = _qualifier_key(qualifiers)
    positive = [dict(fact) for fact in facts
                if _qualifier_key(fact.get("qualifiers", ())) == qualifier_scope]
    negatives = [dict(fact) for fact in negative_facts
                 if _qualifier_key(fact.get("qualifiers", ())) == qualifier_scope]
    rules = list(rules)
    for rule in rules:
        if not isinstance(rule, InferenceRule):
            raise ValueError("rules must be InferenceRule records")
        if not all(_key(value) for value in (rule.rule_id, rule.first_relation,
                                              rule.second_relation, rule.conclusion_relation)):
            raise ValueError("rule fields must be non-empty")
        if rule.middle_kind is not None and not _key(rule.middle_kind):
            raise ValueError("middle kind must be non-empty searchable text")
        if rule.third_relation is not None and not _key(rule.third_relation):
            raise ValueError("third relation must be non-empty searchable text")
        if rule.second_middle_kind is not None and not _key(rule.second_middle_kind):
            raise ValueError("second middle kind must be non-empty searchable text")
        if rule.third_relation is None:
            if rule.second_middle_kind is not None:
                raise ValueError("second middle kind requires a third relation")
        elif rule.middle_kind is None or rule.second_middle_kind is None:
            raise ValueError("three-premise rules require kinds for both middle entities")

    goal = (_key(subject), _key(relation), _key(obj))
    if not all(goal):
        raise ValueError("subject, relation, and object must contain searchable text")
    fact_index: dict[tuple[tuple[str, ...], ...], list[dict[str, Any]]] = {}
    entities: dict[tuple[str, ...], str] = {}
    relation_displays: dict[tuple[str, ...], str] = {}
    for fact in positive:
        triple = _triple_key(fact)
        fact_index.setdefault(triple, []).append(fact)
        relation_displays.setdefault(triple[1], str(fact["relation"]))
        # Relation-type annotations license schemas; their labels are metadata,
        # not candidate domain entities for variable enumeration.
        if triple[1] == _key("has relation type"):
            continue
        entities.setdefault(triple[0], str(fact["subject"]))
        entities.setdefault(triple[2], str(fact["object"]))
    for rows in fact_index.values():
        rows.sort(key=lambda row: tuple(sorted(str(s) for s in row.get("sources", []))))
    candidates = sorted(entities)
    derived_proofs = verified_derived_proofs or {}
    known_outgoing: dict[tuple[tuple[str, ...], tuple[str, ...]], set[tuple[str, ...]]] = {}
    known_incoming: dict[tuple[tuple[str, ...], tuple[str, ...]], set[tuple[str, ...]]] = {}
    for triple in fact_index:
        known_outgoing.setdefault((triple[0], triple[1]), set()).add(triple[2])
        known_incoming.setdefault((triple[1], triple[2]), set()).add(triple[0])
    for triple in derived_proofs:
        known_outgoing.setdefault((triple[0], triple[1]), set()).add(triple[2])
        known_incoming.setdefault((triple[1], triple[2]), set()).add(triple[0])
    kind_index: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for fact in positive:
        triple = _triple_key(fact)
        if triple[1] == _key("is-a"):
            kind_index.setdefault(triple[0], []).append(fact)
    transitive_type_facts: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    symmetric_type_facts: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    integrity_type_facts: dict[
        tuple[str, ...], dict[str, list[dict[str, Any]]]
    ] = {}
    for fact in positive:
        triple = _triple_key(fact)
        if triple[1] != _key("has relation type"):
            continue
        if triple[2] == _key("transitive"):
            transitive_type_facts.setdefault(triple[0], []).append(fact)
        elif triple[2] == _key("symmetric"):
            symmetric_type_facts.setdefault(triple[0], []).append(fact)
        elif triple[2] in {_key("irreflexive"), _key("asymmetric"),
                           _key("functional")}:
            integrity_type_facts.setdefault(triple[0], {}).setdefault(
                " ".join(triple[2]), []).append(fact)
    for triple in fact_index:
        if triple[1] in symmetric_type_facts:
            known_outgoing.setdefault((triple[2], triple[1]), set()).add(triple[0])
            known_incoming.setdefault((triple[1], triple[0]), set()).add(triple[2])
    for triple in derived_proofs:
        if triple[1] in symmetric_type_facts:
            known_outgoing.setdefault((triple[2], triple[1]), set()).add(triple[0])
            known_incoming.setdefault((triple[1], triple[0]), set()).add(triple[2])
    rules_by_conclusion: dict[tuple[str, ...], list[InferenceRule]] = {}
    for rule in rules:
        rules_by_conclusion.setdefault(_key(rule.conclusion_relation), []).append(rule)
        relation_displays.setdefault(_key(rule.first_relation), rule.first_relation)
        relation_displays.setdefault(_key(rule.second_relation), rule.second_relation)
        if rule.third_relation is not None:
            relation_displays.setdefault(_key(rule.third_relation), rule.third_relation)
        relation_displays.setdefault(_key(rule.conclusion_relation),
                                     rule.conclusion_relation)
    def relation_is_derivable(relation_key: tuple[str, ...]) -> bool:
        return bool(rules_by_conclusion.get(relation_key)
                    or transitive_type_facts.get(relation_key)
                    or symmetric_type_facts.get(relation_key))

    derivable_relations = (set(rules_by_conclusion)
                           | set(transitive_type_facts)
                           | set(symmetric_type_facts))

    def display_atom(atom: tuple[tuple[str, ...], ...]) -> dict[str, str]:
        return {
            "subject": entities.get(atom[0], " ".join(atom[0])),
            "relation": relation_displays.get(atom[1], " ".join(atom[1])),
            "object": entities.get(atom[2], " ".join(atom[2])),
        }

    missing_premises: dict[str, dict[str, Any]] = {}

    def premise_support(atom: tuple[tuple[str, ...], ...]
                        ) -> list[dict[str, Any]]:
        """Return direct or verified support for a concrete premise atom."""
        rows = [{"kind": "fact", "fact": fact}
                for fact in fact_index.get(atom, ())]
        rows.extend(derived_proofs.get(atom, ()))
        return rows

    def note_missing_premise(parent: tuple[tuple[str, ...], ...],
                             premise: tuple[tuple[str, ...], ...],
                             rule_id: str, premise_index: int,
                             supported: Iterable[Mapping[str, Any]] = ()) -> None:
        supported_premises = []
        for proof in supported:
            fact = proof.get("fact") if proof.get("kind") == "fact" else None
            conclusion = fact or proof.get("conclusion")
            if isinstance(conclusion, Mapping):
                supported_premises.append({
                    key: conclusion[key] for key in ("subject", "relation", "object")
                    if key in conclusion
                })
        # Do not turn an arbitrary value considered during variable search
        # into a claimed missing link. A concrete suggestion is useful only
        # when another premise or verified derivation anchors that path.
        if not supported_premises:
            return
        detail = {
            "conclusion": display_atom(parent),
            "rule_id": rule_id,
            "premise_index": premise_index,
            "missing_premise": display_atom(premise),
            "supported_premises": supported_premises,
        }
        missing_premises[repr(detail)] = detail

    expansions = 0
    exhausted = False
    proofs_truncated = False
    limit_kind: str | None = None
    max_proofs_per_goal = 64
    def proof_height(proof: Mapping[str, Any]) -> int:
        premises = proof.get("premises", [])
        if not isinstance(premises, list) or not premises:
            return 0
        heights = [proof_height(item) for item in premises
                   if isinstance(item, Mapping)]
        return 1 + max(heights) if heights else 0

    transitive_edge_index: dict[
        tuple[str, ...], dict[tuple[str, ...], list[tuple[tuple[str, ...], dict[str, Any]]]]
    ] = {}
    for triple, fact_rows in fact_index.items():
        if triple[1] not in transitive_type_facts:
            continue
        edge_proofs = [{"kind": "fact", "conclusion": display_atom(triple),
                        "fact": fact} for fact in fact_rows]
        transitive_edge_index.setdefault(triple[1], {}).setdefault(
            triple[0], []).extend((triple[2], proof) for proof in edge_proofs)
    for triple, cached_proofs in derived_proofs.items():
        if (triple[1] not in transitive_type_facts or fact_index.get(triple)
                or not cached_proofs):
            continue
        transitive_edge_index.setdefault(triple[1], {}).setdefault(
            triple[0], []).extend((triple[2], dict(proof)) for proof in cached_proofs)
    for outgoing in transitive_edge_index.values():
        for rows in outgoing.values():
            rows.sort(key=lambda item: (item[0], repr(item[1])))

    def spend() -> bool:
        nonlocal expansions, exhausted, limit_kind
        if expansions >= max_expansions:
            exhausted = True
            limit_kind = "expansion_limit"
            return False
        expansions += 1
        return True

    def prove_transitive(atom: tuple[tuple[str, ...], ...],
                         relation_type_fact: Mapping[str, Any],
                         depth: int, active: frozenset) -> list[dict[str, Any]]:
        """Join same-relation edges and emit a flat, independently checked proof."""
        nonlocal proofs_truncated
        result: list[dict[str, Any]] = []
        relation_key = atom[1]
        outgoing = transitive_edge_index.get(relation_key, {})

        derived_edge_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            list[dict[str, Any]],
        ] = {}

        def indexed_rule_targets(current: tuple[str, ...]
                                 ) -> tuple[set[tuple[str, ...]], bool]:
            targets: set[tuple[str, ...]] = set()
            requires_recursive_search = False
            for rule in rules_by_conclusion.get(relation_key, ()):
                first_relation = _key(rule.first_relation)
                second_relation = _key(rule.second_relation)
                premise_relations = [first_relation, second_relation]
                if rule.third_relation is not None:
                    premise_relations.append(_key(rule.third_relation))
                if any(relation_is_derivable(item)
                       for item in premise_relations):
                    requires_recursive_search = True
                    continue
                first_middles = known_outgoing.get(
                    (current, first_relation), set())
                if rule.middle_kind is not None:
                    required_kind = _key(rule.middle_kind)
                    first_middles = {
                        middle for middle in first_middles
                        if any(_triple_key(fact)[2] == required_kind
                               for fact in kind_index.get(middle, ()))
                    }
                if rule.third_relation is None:
                    for middle in first_middles:
                        targets.update(known_outgoing.get(
                            (middle, second_relation), set()))
                    continue
                second_relation = _key(rule.second_relation)
                third_relation = _key(rule.third_relation)
                second_kind = _key(rule.second_middle_kind or "")
                for first_middle in first_middles:
                    second_middles = known_outgoing.get(
                        (first_middle, second_relation), set())
                    for second_middle in second_middles:
                        if not any(_triple_key(fact)[2] == second_kind
                                   for fact in kind_index.get(second_middle, ())):
                            continue
                        targets.update(known_outgoing.get(
                            (second_middle, third_relation), set()))
            return targets, requires_recursive_search

        def edges_from(current: tuple[str, ...],
                       visited: frozenset[tuple[str, ...]]
                       ) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
            rows = list(outgoing.get(current, ()))
            if not rules_by_conclusion.get(relation_key):
                return rows
            indexed_targets, recursive_search = indexed_rule_targets(current)
            targets = (set(candidates) | {atom[2]}
                       if recursive_search else indexed_targets)
            indexed_targets = {target for target, _proof in rows}
            for target in sorted(targets):
                if target in visited or target in indexed_targets:
                    continue
                edge = (current, relation_key, target)
                if edge not in derived_edge_cache:
                    if not spend():
                        return rows
                    derived_edge_cache[edge] = prove(
                        edge, active, depth + 1)
                    if exhausted:
                        return rows
                rows.extend((target, proof)
                            for proof in derived_edge_cache[edge])
            return rows

        queue = deque([(atom[0], [], frozenset({atom[0]}))])
        shortest_path_length: int | None = None
        while queue:
            current, edge_proofs, visited = queue.popleft()
            if (shortest_path_length is not None
                    and len(edge_proofs) >= shortest_path_length):
                continue
            for next_entity, edge_proof in edges_from(current, visited):
                if exhausted:
                    break
                if next_entity in visited:
                    continue
                if not spend():
                    break
                next_edges = [*edge_proofs, edge_proof]
                if next_entity == atom[2] and len(next_edges) >= 2:
                    if shortest_path_length is None:
                        shortest_path_length = len(next_edges)
                    if len(next_edges) != shortest_path_length:
                        continue
                    result.append({
                        "kind": "schema",
                        "schema": {
                            "schema_id": "transitivity-v1",
                            "schema_type": "transitive",
                            "relation": relation_displays.get(
                                relation_key, " ".join(relation_key)),
                            "validation": {
                                "status": "validated",
                                "validator": "builtin-schema-check-v1",
                            },
                        },
                        "proof_form": "flat-chain-v1",
                        "relation_type_fact": relation_type_fact,
                        "conclusion": display_atom((atom[0], relation_key, next_entity)),
                        "premises": next_edges,
                    })
                    if len(result) >= max_proofs_per_goal:
                        proofs_truncated = True
                        return result
                    continue
                if (shortest_path_length is None
                        or len(next_edges) < shortest_path_length):
                    queue.append((next_entity, next_edges,
                                  visited | {next_entity}))

        return result

    def prove_symmetric(atom: tuple[tuple[str, ...], ...],
                        relation_type_fact: Mapping[str, Any],
                        depth: int, active: frozenset) -> list[dict[str, Any]]:
        """Reverse direct, cached, or independently rule-proved edges."""
        nonlocal exhausted, proofs_truncated, limit_kind
        reverse = (atom[2], atom[1], atom[0])
        premises = [
            {"kind": "fact", "conclusion": display_atom(reverse), "fact": fact}
            for fact in fact_index.get(reverse, ())
        ]
        premises.extend(dict(proof) for proof in derived_proofs.get(reverse, ()))
        # A symmetric schema can consume any supported proof of the reverse
        # edge, including one composed by ordinary rules. The active-goal set
        # prevents this lookup from proving the original goal by cycling back
        # through symmetry.
        premises.extend(prove(reverse, active, depth + 1))
        premises = list({repr(premise): premise for premise in premises}.values())
        if len(premises) > max_proofs_per_goal:
            premises = premises[:max_proofs_per_goal]
            proofs_truncated = True
        result = []
        for premise in sorted(premises, key=repr):
            if not spend():
                return result
            proof = {
                "kind": "schema",
                "schema": {
                    "schema_id": "symmetry-v1",
                    "schema_type": "symmetric",
                    "relation": relation_displays.get(atom[1], " ".join(atom[1])),
                    "validation": {
                        "status": "validated",
                        "validator": "builtin-schema-check-v1",
                    },
                },
                "relation_type_fact": relation_type_fact,
                "conclusion": display_atom(atom),
                "premises": [premise],
            }
            if depth + proof_height(proof) > max_depth:
                exhausted = True
                limit_kind = "depth_limit"
                return result
            result.append(proof)
            if len(result) >= max_proofs_per_goal:
                proofs_truncated = True
                return result
        return result

    proof_cache: dict[
        tuple[tuple[tuple[str, ...], ...], int], list[dict[str, Any]]
    ] = {}
    memo_hits = 0

    def prove(atom: tuple[tuple[str, ...], ...], active: frozenset,
              depth: int) -> list[dict[str, Any]]:
        """Reuse only complete, positive proof sets at an equal remaining depth."""
        nonlocal memo_hits, exhausted, limit_kind
        if depth > max_depth:
            exhausted = True
            limit_kind = "depth_limit"
            return []
        cache_key = (atom, max_depth - depth)
        cached = proof_cache.get(cache_key)
        if cached is not None:
            memo_hits += 1
            return [dict(proof) for proof in cached]
        was_exhausted = exhausted
        was_truncated = proofs_truncated
        proofs = prove_uncached(atom, active, depth)
        if (proofs and not was_exhausted and not was_truncated
                and not exhausted and not proofs_truncated):
            proof_cache[cache_key] = [dict(proof) for proof in proofs]
        return proofs

    def prove_uncached(atom: tuple[tuple[str, ...], ...], active: frozenset,
                       depth: int) -> list[dict[str, Any]]:
        nonlocal exhausted, proofs_truncated, limit_kind
        direct = fact_index.get(atom, [])
        proofs = [{"kind": "fact", "conclusion": display_atom(atom),
                   "fact": fact} for fact in direct]
        if direct:
            if len(proofs) > max_proofs_per_goal:
                proofs_truncated = True
                return proofs[:max_proofs_per_goal]
            return proofs
        reusable = [dict(proof) for proof in derived_proofs.get(atom, ())
                    if proof_height(proof) <= max_depth - depth]
        if reusable:
            if len(reusable) > max_proofs_per_goal:
                proofs_truncated = True
                return reusable[:max_proofs_per_goal]
            return reusable
        if atom in active:
            return []
        if exhausted:
            return proofs
        new_active = active | {atom}
        applications: list[tuple[InferenceRule, Mapping[str, Any] | None]] = [
            (rule, None) for rule in rules_by_conclusion.get(atom[1], [])]
        # Explore grounded base rules before recursive alternatives. An
        # unproductive recursive branch must not exhaust the shared bound
        # before a shorter proof is assembled.
        applications.sort(key=lambda item: (
            sum(_key(relation) in derivable_relations for relation in (
                item[0].first_relation, item[0].second_relation,
                *((item[0].third_relation,) if item[0].third_relation else ()))),
            item[0].rule_id))
        applications.extend((InferenceRule(
            "transitivity-v1", " ".join(relation_key), " ".join(relation_key),
            " ".join(relation_key)), type_fact)
            for relation_key, facts_for_type in transitive_type_facts.items()
            if relation_key == atom[1]
            for type_fact in facts_for_type)
        applications.extend((InferenceRule(
            "symmetry-v1", " ".join(relation_key), " ".join(relation_key),
            " ".join(relation_key)), type_fact)
            for relation_key, facts_for_type in symmetric_type_facts.items()
            if relation_key == atom[1]
            for type_fact in facts_for_type)
        for rule, relation_type_fact in applications:
            if relation_type_fact is not None:
                if rule.rule_id == "transitivity-v1":
                    proofs.extend(prove_transitive(
                        atom, relation_type_fact, depth, new_active))
                else:
                    proofs.extend(prove_symmetric(
                        atom, relation_type_fact, depth, new_active))
                if len(proofs) > max_proofs_per_goal:
                    proofs = proofs[:max_proofs_per_goal]
                    proofs_truncated = True
                if proofs_truncated and len(proofs) >= max_proofs_per_goal:
                    return proofs
                if exhausted:
                    return proofs
                continue
            first_relation = _key(rule.first_relation)
            second_relation = _key(rule.second_relation)
            if rule.third_relation is None:
                # When a premise relation cannot be recursively derived, its
                # middle entities must occur in direct or verified cached
                # evidence. Intersect both endpoint indexes where possible.
                eligible = candidates
                constraints = []
                if not relation_is_derivable(first_relation):
                    constraints.append(known_outgoing.get((atom[0], first_relation), set()))
                if not relation_is_derivable(second_relation):
                    constraints.append(known_incoming.get((second_relation, atom[2]), set()))
                if constraints:
                    possible = set.intersection(*(set(items) for items in constraints))
                    eligible = [candidate for candidate in candidates if candidate in possible]
                    if not eligible and atom == goal and len(constraints) == 2:
                        first_middles = constraints[0]
                        second_middles = constraints[1]
                        if first_middles and not second_middles:
                            for middle in sorted(first_middles)[:4]:
                                note_missing_premise(
                                    atom, (middle, second_relation, atom[2]),
                                    rule.rule_id, 2,
                                    premise_support((atom[0], first_relation,
                                                     middle)))
                        elif second_middles and not first_middles:
                            for middle in sorted(second_middles)[:4]:
                                note_missing_premise(
                                    atom, (atom[0], first_relation, middle),
                                    rule.rule_id, 1,
                                    premise_support((middle, second_relation,
                                                     atom[2])))
                        elif first_middles and second_middles:
                            for middle in sorted(first_middles - second_middles)[:4]:
                                note_missing_premise(
                                    atom, (middle, second_relation, atom[2]),
                                    rule.rule_id, 2,
                                    premise_support((atom[0], first_relation,
                                                     middle)))
                            for middle in sorted(second_middles - first_middles)[:4]:
                                note_missing_premise(
                                    atom, (atom[0], first_relation, middle),
                                    rule.rule_id, 1,
                                    premise_support((middle, second_relation,
                                                     atom[2])))
                if rule.middle_kind is not None:
                    required_kind = _key(rule.middle_kind)
                    eligible_set = set(eligible)
                    eligible = [candidate for candidate in candidates
                                if candidate in eligible_set
                                and any(_triple_key(fact)[2] == required_kind
                                        for fact in kind_index.get(candidate, ()))]
                for middle_key in eligible:
                    if not spend():
                        return proofs
                    goals = [(atom[0], first_relation, middle_key),
                             (middle_key, second_relation, atom[2])]
                    premise_proofs = []
                    for premise_index, premise_goal in enumerate(goals, start=1):
                        premise_proofs.append(prove(premise_goal, new_active, depth + 1))
                        if exhausted and not premise_proofs[-1]:
                            return proofs
                        if not premise_proofs[-1]:
                            note_missing_premise(atom, premise_goal,
                                                 rule.rule_id, premise_index,
                                                 (alternatives[0]
                                                  for alternatives in premise_proofs[:-1]
                                                  if alternatives))
                            break
                    if len(premise_proofs) != 2 or not all(premise_proofs):
                        continue
                    kind_options = ([fact for fact in kind_index.get(middle_key, ())
                                    if _triple_key(fact)[2] == _key(rule.middle_kind)]
                                   if rule.middle_kind is not None else [None])
                    for premise_set in product(*premise_proofs):
                        for kind_fact in kind_options:
                            if not spend():
                                return proofs
                            if relation_type_fact is None:
                                proof = {
                                    "kind": "rule", "rule": asdict(rule),
                                    "conclusion": display_atom(atom),
                                    "premises": list(premise_set),
                                }
                            else:
                                proof = {
                                    "kind": "schema",
                                    "schema": {
                                        "schema_id": "transitivity-v1",
                                        "schema_type": "transitive",
                                        "relation": rule.conclusion_relation,
                                        "validation": {
                                            "status": "validated",
                                            "validator": "builtin-schema-check-v1",
                                        },
                                    },
                                    "relation_type_fact": relation_type_fact,
                                    "conclusion": display_atom(atom),
                                    "premises": list(premise_set),
                                }
                            if kind_fact is not None:
                                proof["middle_kind_fact"] = kind_fact
                            proofs.append(proof)
                            if len(proofs) >= max_proofs_per_goal:
                                proofs_truncated = True
                                return proofs
                continue

            third_relation = _key(rule.third_relation)
            first_kind = _key(rule.middle_kind or "")
            second_kind = _key(rule.second_middle_kind or "")
            first_middles = [candidate for candidate in candidates
                             if any(_triple_key(fact)[2] == first_kind
                                    for fact in kind_index.get(candidate, ()))]
            second_middles = [candidate for candidate in candidates
                              if any(_triple_key(fact)[2] == second_kind
                                     for fact in kind_index.get(candidate, ()))]
            if not relation_is_derivable(first_relation):
                possible_first = known_outgoing.get((atom[0], first_relation), set())
                first_middles = [candidate for candidate in first_middles
                                 if candidate in possible_first]
            if not relation_is_derivable(third_relation):
                possible_last = known_incoming.get((third_relation, atom[2]), set())
                second_middles = [candidate for candidate in second_middles
                                  if candidate in possible_last]
            middle_relation_recursive = relation_is_derivable(second_relation)
            for first_middle in first_middles:
                second_candidates = second_middles
                if not middle_relation_recursive:
                    possible_second = known_outgoing.get(
                        (first_middle, second_relation), set())
                    second_candidates = [candidate for candidate in second_middles
                                         if candidate in possible_second]
                for second_middle in second_candidates:
                    if not spend():
                        return proofs
                    goals = [(atom[0], first_relation, first_middle),
                             (first_middle, second_relation, second_middle),
                             (second_middle, third_relation, atom[2])]
                    premise_proofs = []
                    for premise_index, premise_goal in enumerate(goals, start=1):
                        premise_proofs.append(prove(premise_goal, new_active, depth + 1))
                        if exhausted and not premise_proofs[-1]:
                            return proofs
                        if not premise_proofs[-1]:
                            note_missing_premise(atom, premise_goal,
                                                 rule.rule_id, premise_index,
                                                 (alternatives[0]
                                                  for alternatives in premise_proofs[:-1]
                                                  if alternatives))
                            break
                    if len(premise_proofs) != 3 or not all(premise_proofs):
                        continue
                    first_kind_facts = [fact for fact in kind_index.get(first_middle, ())
                                        if _triple_key(fact)[2] == first_kind]
                    second_kind_facts = [fact for fact in kind_index.get(second_middle, ())
                                         if _triple_key(fact)[2] == second_kind]
                    for premise_set in product(*premise_proofs):
                        for kind_facts in product(first_kind_facts, second_kind_facts):
                            if not spend():
                                return proofs
                            proofs.append({
                                "kind": "rule", "rule": asdict(rule),
                                "conclusion": display_atom(atom),
                                "premises": list(premise_set),
                                "middle_kind_facts": list(kind_facts),
                            })
                            if len(proofs) >= max_proofs_per_goal:
                                proofs_truncated = True
                                return proofs
        return proofs

    found = prove(goal, frozenset(), 0)
    incomplete_search = exhausted or proofs_truncated
    if incomplete_search and limit_kind is None:
        limit_kind = "proof_limit"
    if incomplete_search and not found:
        limit_labels = {
            "depth_limit": "rule-depth limit",
            "expansion_limit": "candidate-expansion limit",
            "proof_limit": "proof-list limit",
        }
        limit_reason = (f"Inference reached its {limit_labels[limit_kind]}; "
                        "no complete conclusion was established.")
        return InferenceResult(
            "unknown", request=limit_reason,
            expansions=expansions, complete=False, reason_code="search_limit",
            failure_kind="search_limit", limit_kind=limit_kind)
    if not found:
        root_relation = goal[1]
        root_has_rule = bool(
            rules_by_conclusion.get(root_relation)
            or transitive_type_facts.get(root_relation)
            or symmetric_type_facts.get(root_relation))
        missing = tuple(missing_premises[key]
                        for key in sorted(missing_premises)[:8])
        failure_kind = ("missing_premise" if root_has_rule else
                        "no_applicable_rule")
        return InferenceResult("unknown", request="No explicit rule proof supports this conclusion.",
                               expansions=expansions, reason_code="no_proof",
                               failure_kind=failure_kind,
                               missing_premises=missing)

    integrity_conflicts: list[tuple[str, dict[str, Any]]] = []
    relation_constraints = integrity_type_facts.get(goal[1], {})
    if incomplete_search and ("asymmetric" in relation_constraints
                              or "functional" in relation_constraints):
        return InferenceResult(
            "unknown", request=("A proof was found, but the search limit prevented "
                                "checking the declared relation integrity constraint."),
            expansions=expansions, complete=False, reason_code="search_limit",
            failure_kind="search_limit", limit_kind=limit_kind)
    if goal[0] == goal[2]:
        for constraint in ("irreflexive", "asymmetric"):
            declarations = relation_constraints.get(constraint, [])
            if declarations:
                integrity_conflicts.append((constraint, declarations[0]))
    if goal[0] != goal[2]:
        declarations = relation_constraints.get("asymmetric", [])
        if declarations:
            reverse_goal = (goal[2], goal[1], goal[0])
            reverse_found = prove(reverse_goal, frozenset(), 0)
            if exhausted or proofs_truncated:
                return InferenceResult(
                    "unknown", request=("Integrity check for asymmetric relation "
                                        "reached the inference search limit."),
                    expansions=expansions, complete=False,
                    reason_code="search_limit", failure_kind="search_limit",
                    limit_kind=limit_kind)
            if reverse_found:
                integrity_conflicts.append(("asymmetric", declarations[0]))
    if not incomplete_search:
        declarations = relation_constraints.get("functional", [])
        if declarations:
            for candidate_object in candidates:
                if candidate_object == goal[2]:
                    continue
                alternative = prove(
                    (goal[0], goal[1], candidate_object), frozenset(), 0)
                if exhausted:
                    return InferenceResult(
                        "unknown", request=("Integrity check for functional relation "
                                            "reached the inference search limit."),
                        expansions=expansions, complete=False,
                        reason_code="search_limit", failure_kind="search_limit",
                        limit_kind=limit_kind)
                if alternative:
                    integrity_conflicts.append(("functional", declarations[0]))
                    break

    negative_triples = {_triple_key(fact) for fact in negatives}
    conflicting = [proof for proof in found
                   if goal in negative_triples or _proof_has_conflict(proof, negative_triples)]
    found.sort(key=repr)
    conclusion = {"subject": subject, "relation": relation, "object": obj}
    support = _proof_support(found, contested=bool(conflicting))
    if integrity_conflicts:
        constraint, declaration = integrity_conflicts[0]
        sources = ", ".join(sorted(str(source) for source
                                   in declaration.get("sources", [])))
        return InferenceResult(
            "ambiguous", conclusion, tuple(found),
            (f"The derived conclusion conflicts with the declared "
             f"'{constraint}' integrity constraint for this relation"
             + (f" (schema source: {sources})." if sources else ".")),
            expansions, support_class=support[0],
            lineage_count=support[1], source_count=support[2],
            source_documents=support[3], reason_code="integrity_conflict",
            failure_kind="integrity_conflict")
    if conflicting:
        return InferenceResult(
            "ambiguous", conclusion, tuple(found),
            "A positive proof depends on explicit negative evidence.", expansions,
            support_class=support[0], lineage_count=support[1],
            source_count=support[2], source_documents=support[3],
            reason_code="contradiction", failure_kind="contradiction")
    return InferenceResult(
        "answered", conclusion, tuple(found),
        request=("A verified proof was found, but the search limit prevented "
                 f"enumerating all supporting proofs ({limit_kind})." if exhausted else
                 f"A verified proof was found; support listing was capped at "
                 f"{max_proofs_per_goal} proofs." if proofs_truncated else None),
        expansions=expansions, complete=not incomplete_search,
        reason_code="search_limit" if incomplete_search else None,
        failure_kind="search_limit" if incomplete_search else None,
        limit_kind=limit_kind,
        support_class=("partial" if incomplete_search else support[0]),
        lineage_count=support[1],
        source_count=support[2], source_documents=support[3],
        memo_hits=memo_hits)


def discover_rule_candidates(
        facts: Iterable[Mapping[str, Any]], *,
        negative_facts: Iterable[Mapping[str, Any]] = (),
        min_support: int = 2,
        max_expansions: int = 100_000,
        max_arity: int = 2) -> RuleDiscoveryResult:
    """Find bounded two- or explicitly typed three-edge chain rules.

    A candidate is emitted only with ``min_support`` distinct endpoint pairs.
    Matching explicit negative conclusions are retained as counterexamples.
    Discovery is descriptive only: it never installs a rule. Candidate chains
    require both premises and their labeled conclusion to share an exact
    qualifier scope. Contextual inference still requires an exact-scope query.
    """
    for name, value in (("min_support", min_support),
                        ("max_expansions", max_expansions)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if type(max_arity) is not int or max_arity not in {2, 3}:
        raise ValueError("max_arity must be 2 or 3")
    positives = [fact if isinstance(fact, dict) else dict(fact)
                 for fact in facts]
    negatives = [fact if isinstance(fact, dict) else dict(fact)
                 for fact in negative_facts]

    # Discovery revisits facts while building indexes, joining chains, and
    # attaching counterexamples. Normalize each immutable input row once;
    # tokenization otherwise dominates sparse large-store searches even when
    # the join itself has almost no expansions.
    fact_key_cache: dict[
        int,
        tuple[tuple[tuple[str, ...], ...],
              tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
    ] = {}

    def normalized_keys(fact: Mapping[str, Any]):
        identity = id(fact)
        value = fact_key_cache.get(identity)
        if value is None:
            value = (_triple_key(fact),
                     _qualifier_key(fact.get("qualifiers", ())))
            fact_key_cache[identity] = value
        return value

    def triple_key(fact: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
        return normalized_keys(fact)[0]

    def scope_key(fact: Mapping[str, Any]
                  ) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
        return normalized_keys(fact)[1]

    positive_by_endpoint: dict[
        tuple[tuple[str, ...], tuple[str, ...],
              tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
        list[dict[str, Any]],
    ] = {}
    negative_by_endpoint: dict[
        tuple[tuple[str, ...], tuple[str, ...],
              tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
        list[dict[str, Any]],
    ] = {}
    positive_outgoing: dict[
        tuple[tuple[str, ...],
              tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
        list[dict[str, Any]],
    ] = {}
    for fact in positives:
        triple = triple_key(fact)
        scope = scope_key(fact)
        positive_by_endpoint.setdefault((triple[0], triple[2], scope), []).append(fact)
        positive_outgoing.setdefault(
            (triple[0], scope), []).append(fact)
    for fact in negatives:
        triple = triple_key(fact)
        scope = scope_key(fact)
        negative_by_endpoint.setdefault((triple[0], triple[2], scope), []).append(fact)

    support: dict[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
                  dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]]] = {}
    counterexamples: dict[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
                          dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]]] = {}
    displays: dict[tuple[str, ...], str] = {}
    for fact in positives + negatives:
        triple = triple_key(fact)
        displays.setdefault(triple[1], str(fact["relation"]))

    expansions = 0
    complete = True
    stop = False
    for first in positives:
        first_key = triple_key(first)
        first_scope = scope_key(first)
        for second in positive_outgoing.get((first_key[2], first_scope), ()):
            second_key = triple_key(second)
            if expansions >= max_expansions:
                complete = False
                stop = True
                break
            expansions += 1
            endpoints = (first_key[0], second_key[2])
            binding = (first_key[0], first_key[2], second_key[2])
            conclusion_key = (endpoints[0], endpoints[1], first_scope)
            for conclusion in positive_by_endpoint.get(conclusion_key, []):
                conclusion_relation = triple_key(conclusion)[1]
                key = (first_key[1], second_key[1], conclusion_relation)
                support.setdefault(key, {})[(binding[0], binding[2])] = {
                    "first": first, "second": second, "conclusion": conclusion}
            for conclusion in negative_by_endpoint.get(conclusion_key, []):
                conclusion_relation = triple_key(conclusion)[1]
                key = (first_key[1], second_key[1], conclusion_relation)
                counterexamples.setdefault(key, {})[(binding[0], binding[2])] = {
                    "first": first, "second": second, "conclusion": conclusion}
        if stop:
            break

    typed_support: dict[
        tuple[tuple[str, ...], ...],
        dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]],
    ] = {}
    typed_counterexamples: dict[
        tuple[tuple[str, ...], ...],
        dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]],
    ] = {}
    if max_arity == 3 and complete:
        outgoing: dict[tuple[tuple[str, ...], tuple[str, ...]], list[dict[str, Any]]] = {}
        kinds: dict[
            tuple[tuple[str, ...],
                  tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
            list[dict[str, Any]],
        ] = {}
        kind_displays: dict[tuple[str, ...], str] = {}
        for row in positives:
            triple = triple_key(row)
            if triple[1] == _key("is-a"):
                kinds.setdefault((triple[0],
                                  scope_key(row)), []).append(row)
                kind_displays.setdefault(triple[2], str(row["object"]))
                continue
            outgoing.setdefault((triple[0],
                                 scope_key(row)), []).append(row)
        for rows in outgoing.values():
            rows.sort(key=lambda row: tuple(triple_key(row)))
        for first in positives:
            first_key = triple_key(first)
            first_scope = scope_key(first)
            if first_key[1] == _key("is-a"):
                continue
            for second in outgoing.get((first_key[2], first_scope), ()):
                second_key = triple_key(second)
                if second_key[1] == _key("is-a"):
                    continue
                if expansions >= max_expansions:
                    complete = False
                    stop = True
                    break
                expansions += 1
                for third in outgoing.get((second_key[2], first_scope), ()):
                    third_key = triple_key(third)
                    if third_key[1] == _key("is-a"):
                        continue
                    if expansions >= max_expansions:
                        complete = False
                        stop = True
                        break
                    expansions += 1
                    first_kind_rows = kinds.get((first_key[2], first_scope), ())
                    second_kind_rows = kinds.get((second_key[2], first_scope), ())
                    if not first_kind_rows or not second_kind_rows:
                        continue
                    for first_kind_fact in first_kind_rows:
                        first_kind_key = triple_key(first_kind_fact)[2]
                        for second_kind_fact in second_kind_rows:
                            if expansions >= max_expansions:
                                complete = False
                                stop = True
                                break
                            expansions += 1
                            second_kind_key = triple_key(second_kind_fact)[2]
                            key = (first_key[1], second_key[1], third_key[1],
                                   first_kind_key, second_kind_key)
                            example = {
                                "first": first, "second": second, "third": third,
                                "first_kind": first_kind_fact,
                                "second_kind": second_kind_fact,
                            }
                            endpoints = (first_key[0], third_key[2])
                            conclusion_key = (endpoints[0], endpoints[1], first_scope)
                            for conclusion in positive_by_endpoint.get(conclusion_key, ()):
                                conclusion_relation = triple_key(conclusion)[1]
                                typed_key = (*key, conclusion_relation)
                                typed_support.setdefault(typed_key, {})[endpoints] = {
                                    **example, "conclusion": conclusion}
                            for conclusion in negative_by_endpoint.get(conclusion_key, ()):
                                conclusion_relation = triple_key(conclusion)[1]
                                typed_key = (*key, conclusion_relation)
                                typed_counterexamples.setdefault(typed_key, {})[endpoints] = {
                                    **example, "conclusion": conclusion}
                        if stop:
                            break
                    if stop:
                        break
                if stop:
                    break
            if stop:
                break

    candidates: list[RuleCandidate] = []
    keys = set(support)
    for key in keys:
        supported = support[key]
        if len(supported) < min_support:
            continue
        ordered_support = tuple(supported[pair] for pair in sorted(supported))
        ordered_negative = tuple(counterexamples.get(key, {})[pair]
                                 for pair in sorted(counterexamples.get(key, {})))
        independent_sources = tuple(sorted({
            str(source).split("#", 1)[0]
            for example in ordered_support
            for source in example["conclusion"].get("sources", [])
            if str(source).strip()
        }))
        status = ("incomplete" if not complete else
                  "contradicted" if ordered_negative else
                  "insufficient-independent-sources"
                  if len(independent_sources) < min_support else
                  "uncontradicted")
        candidates.append(RuleCandidate(
            displays.get(key[0], " ".join(key[0])),
            displays.get(key[1], " ".join(key[1])),
            displays.get(key[2], " ".join(key[2])),
            ordered_support, ordered_negative, status, independent_sources))
    for key, supported in typed_support.items():
        if len(supported) < min_support:
            continue
        ordered_support = tuple(supported[pair] for pair in sorted(supported))
        negative_rows = typed_counterexamples.get(key, {})
        ordered_negative = tuple(negative_rows[pair] for pair in sorted(negative_rows))
        independent_sources = tuple(sorted({
            str(source).split("#", 1)[0]
            for example in ordered_support
            for source in example["conclusion"].get("sources", [])
            if str(source).strip()
        }))
        status = ("incomplete" if not complete else
                  "contradicted" if ordered_negative else
                  "insufficient-independent-sources"
                  if len(independent_sources) < min_support else
                  "uncontradicted")
        candidates.append(RuleCandidate(
            displays.get(key[0], " ".join(key[0])),
            displays.get(key[1], " ".join(key[1])),
            displays.get(key[-1], " ".join(key[-1])),
            ordered_support, ordered_negative, status, independent_sources,
            third_relation=displays.get(key[2], " ".join(key[2])),
            middle_kind=kind_displays.get(key[3], " ".join(key[3])),
            second_middle_kind=kind_displays.get(key[4], " ".join(key[4]))))
    candidates.sort(key=lambda candidate: tuple(
        _key(value) for value in (candidate.first_relation,
                                  candidate.second_relation,
                                  candidate.third_relation or "",
                                  candidate.middle_kind or "",
                                  candidate.second_middle_kind or "",
                                  candidate.conclusion_relation)))
    return RuleDiscoveryResult(complete, tuple(candidates), expansions)


def _validate_three_premise_rule_candidate(
        candidate: RuleCandidate, *,
        validation_facts: list[dict[str, Any]],
        validation_negative_facts: list[dict[str, Any]],
        min_positive_examples: int,
        max_expansions: int) -> RuleValidation:
    if (candidate.third_relation is None or candidate.middle_kind is None
            or candidate.second_middle_kind is None):
        return RuleValidation("malformed-candidate", (), (), 0, True, 0)
    r1, r2, r3 = (_key(candidate.first_relation),
                  _key(candidate.second_relation),
                  _key(candidate.third_relation))
    conclusion_relation = _key(candidate.conclusion_relation)
    first_kind, second_kind = (_key(candidate.middle_kind),
                               _key(candidate.second_middle_kind))
    type_index: dict[
        tuple[tuple[str, ...], tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
        set[tuple[str, ...]],
    ] = {}
    type_facts: dict[
        tuple[tuple[str, ...], tuple[str, ...],
              tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
        dict[str, Any],
    ] = {}
    outgoing: dict[
        tuple[tuple[str, ...], tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
        list[dict[str, Any]],
    ] = {}
    positive_labels: dict[
        tuple[tuple[str, ...], tuple[str, ...],
              tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
        list[dict[str, Any]],
    ] = {}
    negative_labels: dict[
        tuple[tuple[str, ...], tuple[str, ...],
              tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
        list[dict[str, Any]],
    ] = {}
    for row in validation_facts:
        triple = _triple_key(row)
        scope = _qualifier_key(row.get("qualifiers", ()))
        if triple[1] == _key("is-a"):
            type_index.setdefault((triple[0], scope), set()).add(triple[2])
            type_facts.setdefault((triple[0], triple[2], scope), row)
        else:
            if triple[1] in {r1, r2, r3}:
                outgoing.setdefault((triple[0], scope), []).append(row)
            if triple[1] == conclusion_relation:
                positive_labels.setdefault((triple[0], triple[2], scope), []).append(row)
    for row in validation_negative_facts:
        triple = _triple_key(row)
        if triple[1] == conclusion_relation:
            negative_labels.setdefault((triple[0], triple[2],
                                        _qualifier_key(row.get("qualifiers", ()))), []).append(row)

    positives: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    negatives: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    unknown: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    independent_sources: set[str] = set()
    expansions = 0
    complete = True
    for first in validation_facts:
        first_key = _triple_key(first)
        if first_key[1] != r1:
            continue
        scope = _qualifier_key(first.get("qualifiers", ()))
        for second in outgoing.get((first_key[2], scope), ()):
            second_key = _triple_key(second)
            if second_key[1] != r2:
                continue
            if expansions >= max_expansions:
                complete = False
                break
            expansions += 1
            if first_kind not in type_index.get((first_key[2], scope), set()):
                continue
            for third in outgoing.get((second_key[2], scope), ()):
                third_key = _triple_key(third)
                if third_key[1] != r3:
                    continue
                if expansions >= max_expansions:
                    complete = False
                    break
                expansions += 1
                if second_kind not in type_index.get((second_key[2], scope), set()):
                    continue
                endpoints = (first_key[0], third_key[2])
                labels_key = (endpoints[0], endpoints[1], scope)
                positive = positive_labels.get(labels_key, ())
                negative = negative_labels.get(labels_key, ())
                example = {"first": first, "second": second, "third": third,
                           "first_kind": type_facts[(first_key[2], first_kind, scope)],
                           "second_kind": type_facts[(second_key[2], second_kind, scope)]}
                if positive:
                    positives[endpoints] = {**example, "conclusion": positive[0]}
                    independent_sources.update(
                        str(source).split("#", 1)[0]
                        for row in positive for source in row.get("sources", [])
                        if str(source).strip())
                if negative:
                    negatives[endpoints] = {**example, "conclusion": negative[0]}
                if not positive and not negative:
                    unknown.add(endpoints)
            if not complete:
                break
        if not complete:
            break

    ordered_positive = tuple(positives[key] for key in sorted(positives))
    ordered_negative = tuple(negatives[key] for key in sorted(negatives))
    if not complete:
        status = "incomplete"
    elif ordered_negative:
        status = "contradicted"
    elif (len(ordered_positive) >= min_positive_examples
          and len(independent_sources) >= min_positive_examples):
        status = "validated"
    elif len(ordered_positive) >= min_positive_examples:
        status = "insufficient-independent-sources"
    else:
        status = "insufficient"
    return RuleValidation(status, ordered_positive, ordered_negative,
                          len(unknown), complete, expansions,
                          tuple(sorted(independent_sources)))


def validate_rule_candidate(
        candidate: RuleCandidate, *,
        training_facts: Iterable[Mapping[str, Any]],
        training_negative_facts: Iterable[Mapping[str, Any]],
        validation_facts: Iterable[Mapping[str, Any]],
        validation_negative_facts: Iterable[Mapping[str, Any]],
        min_positive_examples: int = 2,
        max_expansions: int = 100_000) -> RuleValidation:
    """Evaluate a proposed chain on a disjoint, labeled validation partition."""
    for name, value in (("min_positive_examples", min_positive_examples),
                        ("max_expansions", max_expansions)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    train_rows = [dict(row) for row in
                  list(training_facts) + list(training_negative_facts)]
    valid_positive = [dict(row) for row in validation_facts]
    valid_negative = [dict(row) for row in validation_negative_facts]
    train_triples = {_triple_key(row) for row in train_rows}
    validation_triples = {_triple_key(row) for row in valid_positive + valid_negative}
    if train_triples & validation_triples:
        return RuleValidation("overlap", (), (), 0, True, 0)
    if candidate.status == "contradicted":
        return RuleValidation("training-contradicted", (), (), 0, True, 0)
    if candidate.status == "incomplete":
        return RuleValidation("incomplete", (), (), 0, False, 0)
    if candidate.status == "insufficient-independent-sources":
        return RuleValidation("insufficient-independent-sources", (), (), 0,
                              True, 0)
    if candidate.third_relation is not None:
        return _validate_three_premise_rule_candidate(
            candidate, validation_facts=valid_positive,
            validation_negative_facts=valid_negative,
            min_positive_examples=min_positive_examples,
            max_expansions=max_expansions)

    first_relation = _key(candidate.first_relation)
    second_relation = _key(candidate.second_relation)
    conclusion_relation = _key(candidate.conclusion_relation)
    positives_by_endpoint: dict[tuple[tuple[str, ...], tuple[str, ...]], list[dict[str, Any]]] = {}
    negatives_by_endpoint: dict[tuple[tuple[str, ...], tuple[str, ...]], list[dict[str, Any]]] = {}
    for row in valid_positive:
        triple = _triple_key(row)
        if triple[1] == conclusion_relation:
            positives_by_endpoint.setdefault((triple[0], triple[2]), []).append(row)
    for row in valid_negative:
        triple = _triple_key(row)
        if triple[1] == conclusion_relation:
            negatives_by_endpoint.setdefault((triple[0], triple[2]), []).append(row)

    firsts = [row for row in valid_positive
              if _triple_key(row)[1] == first_relation]
    seconds = [row for row in valid_positive
               if _triple_key(row)[1] == second_relation]
    positive_examples: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    negative_examples: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    independent_sources: set[str] = set()
    unknown: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    expansions = 0
    complete = True
    for first in firsts:
        first_key = _triple_key(first)
        for second in seconds:
            second_key = _triple_key(second)
            first_scope = _qualifier_key(first.get("qualifiers", ()))
            if (first_key[2] != second_key[0]
                    or first_scope != _qualifier_key(second.get("qualifiers", ()))):
                continue
            if expansions >= max_expansions:
                complete = False
                break
            expansions += 1
            endpoints = first_key[0], second_key[2]
            positive_labels = [row for row in positives_by_endpoint.get(endpoints, [])
                               if _qualifier_key(row.get("qualifiers", ())) == first_scope]
            negative_labels = [row for row in negatives_by_endpoint.get(endpoints, [])
                               if _qualifier_key(row.get("qualifiers", ())) == first_scope]
            if positive_labels:
                positive_examples[endpoints] = {
                    "first": first, "second": second,
                    "conclusion": positive_labels[0]}
                independent_sources.update(
                    str(source).split("#", 1)[0]
                    for row in positive_labels
                    for source in row.get("sources", [])
                    if str(source).strip())
            if negative_labels:
                negative_examples[endpoints] = {
                    "first": first, "second": second,
                    "conclusion": negative_labels[0]}
            if not positive_labels and not negative_labels:
                unknown.add(endpoints)
        if not complete:
            break
    ordered_positive = tuple(positive_examples[key] for key in sorted(positive_examples))
    ordered_negative = tuple(negative_examples[key] for key in sorted(negative_examples))
    if not complete:
        status = "incomplete"
    elif ordered_negative:
        status = "contradicted"
    elif (len(ordered_positive) >= min_positive_examples
          and len(independent_sources) >= min_positive_examples):
        status = "validated"
    elif len(ordered_positive) >= min_positive_examples:
        status = "insufficient-independent-sources"
    else:
        status = "insufficient"
    return RuleValidation(status, ordered_positive, ordered_negative,
                          len(unknown), complete, expansions,
                          tuple(sorted(independent_sources)))


def _proof_has_conflict(proof: Mapping[str, Any], negatives: set) -> bool:
    if proof.get("kind") == "fact":
        return _triple_key(proof["fact"]) in negatives
    kind_fact = proof.get("middle_kind_fact")
    kind_facts = ([kind_fact] if isinstance(kind_fact, Mapping) else [])
    kind_facts.extend(fact for fact in proof.get("middle_kind_facts", [])
                      if isinstance(fact, Mapping))
    relation_type_fact = proof.get("relation_type_fact")
    if isinstance(relation_type_fact, Mapping):
        kind_facts.append(relation_type_fact)
    return (any(_triple_key(fact) in negatives for fact in kind_facts)
            or any(_proof_has_conflict(premise, negatives)
                   for premise in proof.get("premises", [])))


def _display_triple(atom: tuple[tuple[str, ...], ...]) -> dict[str, str]:
    return {"subject": " ".join(atom[0]), "relation": " ".join(atom[1]),
            "object": " ".join(atom[2])}


def _triple_key(fact: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    values = (fact.get("subject"), fact.get("relation"), fact.get("object"))
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("fact records require non-empty subject, relation, and object")
    triple = tuple(_key(value) for value in values)
    if not all(triple):
        raise ValueError("fact fields must contain searchable text")
    return triple  # type: ignore[return-value]
