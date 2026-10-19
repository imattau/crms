"""Independent verifier for recursive rule and typed-schema proof trees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping
from crms_text import tokens as normalized_tokens
from crms_schema import (
    CLOSED_WORLD_SCHEMA, PROOF_SCHEMA_SPECS, WITNESS_CONSTRAINT_DENIAL_TYPES,
)


def _key(value: str) -> tuple[str, ...]:
    return normalized_tokens(value)


def _qualifiers(value: Any) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    if value is None:
        return ()
    pairs = value.items() if isinstance(value, Mapping) else value
    normalized = []
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError("proof qualifiers are malformed")
        name, qualifier_value = pair
        if not isinstance(name, str) or not isinstance(qualifier_value, str):
            raise ValueError("proof qualifier names and values must be text")
        key = (_key(name), _key(qualifier_value))
        if not all(key):
            raise ValueError("proof qualifier names and values must be searchable")
        normalized.append(key)
    if len(set(name for name, _ in normalized)) != len(normalized):
        raise ValueError("proof qualifier names are duplicated")
    return tuple(sorted(normalized))


def _scope_is_within(fact_scope: Any, query_scope: Any) -> bool:
    """An unscoped assertion is general; scoped assertions need query coverage."""
    required = dict(_qualifiers(fact_scope))
    available = dict(query_scope)
    return all(available.get(name) == value for name, value in required.items())


@dataclass(frozen=True)
class RuleProofCheck:
    valid: bool
    reason: str


def verify_closed_world_denial(
        conclusion: Mapping[str, Any] | None,
        declaration: Mapping[str, Any] | None, *,
        expected_conclusion: Mapping[str, Any],
        expected_qualifiers: Any = (), complete: bool,
        proofs: Iterable[Mapping[str, Any]] = (),
        fact_lookup: Callable[[Mapping[str, Any]], bool] | None = None,
        facts: Iterable[Mapping[str, Any]] = ()) -> RuleProofCheck:
    """Check the evidence and completeness contract for a closed-world denial.

    Absence is not a proof tree. A denial is admissible only when inference
    reports a completed search with no positive proofs and cites a stored,
    scope-applicable closed-world declaration for the queried relation.
    """
    try:
        if complete is not True:
            return RuleProofCheck(False, "closed-world search was incomplete")
        if tuple(proofs):
            return RuleProofCheck(False, "a denial cannot contain positive proofs")
        if not isinstance(conclusion, Mapping) or (
                _triple(conclusion) != _triple(expected_conclusion)):
            return RuleProofCheck(False, "denial does not match the requested conclusion")
        if not isinstance(declaration, Mapping):
            return RuleProofCheck(False, "closed-world declaration is missing")
        if fact_lookup is not None:
            present = bool(fact_lookup(declaration))
        else:
            signatures = {_fact_signature(item) for item in facts}
            present = _fact_signature(declaration) in signatures
        if not present:
            return RuleProofCheck(False, "closed-world declaration is not in the fact snapshot")
        subject, relation, obj = _triple(expected_conclusion)
        if (_triple(declaration) != (relation, _key("has relation type"),
                                     _key(CLOSED_WORLD_SCHEMA.name))):
            return RuleProofCheck(False, "declaration does not close the queried relation")
        scope = _qualifiers(expected_qualifiers)
        if not _scope_is_within(declaration.get("qualifiers", ()), scope):
            return RuleProofCheck(False, "closed-world declaration is outside query scope")
        return RuleProofCheck(True, "valid complete closed-world denial")
    except (TypeError, ValueError, AttributeError) as error:
        return RuleProofCheck(False, str(error) or "malformed closed-world denial")


def verify_constraint_denial(
        conclusion: Mapping[str, Any] | None,
        evidence: Mapping[str, Any] | None, *,
        expected_conclusion: Mapping[str, Any],
        expected_qualifiers: Any = (), complete: bool,
        proofs: Iterable[Mapping[str, Any]] = (),
        fact_lookup: Callable[[Mapping[str, Any]], bool] | None = None,
        facts: Iterable[Mapping[str, Any]] = (),
        rules: Iterable[Mapping[str, Any]] = ()) -> RuleProofCheck:
    """Verify a negative conclusion from an explicit integrity constraint."""
    try:
        if complete is not True:
            return RuleProofCheck(False, "constraint search was incomplete")
        if tuple(proofs):
            return RuleProofCheck(False, "a denial cannot contain a positive proof")
        if not isinstance(conclusion, Mapping) or (
                _triple(conclusion) != _triple(expected_conclusion)):
            return RuleProofCheck(False, "denial does not match the requested conclusion")
        if not isinstance(evidence, Mapping):
            return RuleProofCheck(False, "constraint evidence is missing")
        constraint = evidence.get("constraint")
        if constraint not in WITNESS_CONSTRAINT_DENIAL_TYPES:
            return RuleProofCheck(False, "constraint type is unsupported")
        declaration = evidence.get("declaration")
        if not isinstance(declaration, Mapping):
            return RuleProofCheck(False, "constraint declaration is missing")
        if fact_lookup is not None:
            present = bool(fact_lookup(declaration))
        else:
            signatures = {_fact_signature(item) for item in facts}
            present = _fact_signature(declaration) in signatures
        if not present:
            return RuleProofCheck(False, "constraint declaration is not in the fact snapshot")
        subject, relation, obj = _triple(expected_conclusion)
        if (_triple(declaration) != (relation, _key("has relation type"),
                                     _key(constraint))):
            return RuleProofCheck(False, "declaration does not license this constraint")
        scope = _qualifiers(expected_qualifiers)
        if not _scope_is_within(declaration.get("qualifiers", ()), scope):
            return RuleProofCheck(False, "constraint declaration is outside query scope")
        witness = evidence.get("witness")
        if constraint == "irreflexive":
            if subject != obj or witness is not None:
                return RuleProofCheck(False, "irreflexive denial needs a self-relation query")
            return RuleProofCheck(True, "valid irreflexive denial")
        if not isinstance(witness, Mapping):
            return RuleProofCheck(False, "constraint denial is missing its witness proof")
        witness_conclusion = witness.get("conclusion")
        if not isinstance(witness_conclusion, Mapping):
            return RuleProofCheck(False, "constraint witness conclusion is malformed")
        ws, wr, wo = _triple(witness_conclusion)
        if wr != relation:
            return RuleProofCheck(False, "constraint witness uses a different relation")
        if constraint == "asymmetric":
            if (subject == obj or ws != obj or wo != subject):
                return RuleProofCheck(False, "asymmetric witness does not reverse the query")
        elif ws != subject or wo == obj:
            return RuleProofCheck(False, "functional witness does not establish another value")
        witness_check = verify_inference_proof(
            witness, facts, rules, expected_conclusion=witness_conclusion,
            expected_qualifiers=expected_qualifiers, fact_lookup=fact_lookup)
        if not witness_check.valid:
            return RuleProofCheck(False, "constraint witness failed verification: "
                                  + witness_check.reason)
        return RuleProofCheck(True, f"valid {constraint} denial with verified witness")
    except (TypeError, ValueError, AttributeError) as error:
        return RuleProofCheck(False, str(error) or "malformed constraint denial")


def verify_inference_proof(
        proof: Mapping[str, Any], facts: Iterable[Mapping[str, Any]],
        rules: Iterable[Mapping[str, Any]], *,
        expected_conclusion: Mapping[str, Any] | None = None,
        expected_qualifiers: Any = (),
        fact_lookup: Callable[[Mapping[str, Any]], bool] | None = None,
        max_depth: int = 64,
        max_nodes: int = 10_000) -> RuleProofCheck:
    """Validate fact leaves, explicit rules, and fixed schema instances independently."""
    try:
        if max_depth < 1 or max_nodes < 1:
            return RuleProofCheck(False, "verification bounds must be positive")
        fact_signatures = (None if fact_lookup is not None else
                           {_fact_signature(item) for item in facts})

        def fact_is_present(fact: Mapping[str, Any]) -> bool:
            if fact_lookup is not None:
                return bool(fact_lookup(fact))
            assert fact_signatures is not None
            return _fact_signature(fact) in fact_signatures

        trusted_rules = {_rule_key(item) for item in rules}
        expected_scope = _qualifiers(expected_qualifiers)
        nodes = 0

        def visit(node: Mapping[str, Any], depth: int
                  ) -> tuple[tuple[tuple[str, ...], ...],
                             tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]]:
            nonlocal nodes
            nodes += 1
            if nodes > max_nodes:
                raise ValueError("proof exceeds verifier node limit")
            if depth > max_depth:
                raise ValueError("proof exceeds verifier depth limit")
            conclusion = node.get("conclusion")
            if not isinstance(conclusion, Mapping):
                raise ValueError("proof conclusion is malformed")
            conclusion_key = _triple(conclusion)
            kind = node.get("kind")
            if kind == "fact":
                fact = node.get("fact")
                if not isinstance(fact, Mapping):
                    raise ValueError("fact proof leaf is malformed")
                if not fact_is_present(fact):
                    raise ValueError("proof fact is not present in the snapshot")
                if _triple(fact) != conclusion_key:
                    raise ValueError("fact leaf does not prove its stated conclusion")
                if not _scope_is_within(fact.get("qualifiers", ()), expected_scope):
                    raise ValueError("fact proof is outside the requested qualifier scope")
                # The leaf supports the requested context, even when the fact
                # itself is general and therefore carries no qualifier.
                return conclusion_key, expected_scope
            if kind == "schema":
                schema = node.get("schema")
                premises = node.get("premises")
                type_fact = node.get("relation_type_fact")
                if not isinstance(schema, Mapping) or not isinstance(premises, list) \
                        or not isinstance(type_fact, Mapping):
                    raise ValueError("schema proof is missing its declaration or premises")
                schema_id = schema.get("schema_id")
                schema_spec = PROOF_SCHEMA_SPECS.get(schema_id)
                proof_form = node.get("proof_form")
                if (schema_spec is None
                        or schema_spec.category != "derivation"
                        or schema.get("schema_type") != schema_spec.name
                        or schema.get("validation") != {
                            "status": schema_spec.validation_status,
                            "validator": schema_spec.validator}
                        or (proof_form is not None
                            and proof_form not in schema_spec.proof_forms)):
                    raise ValueError("schema declaration or proof form is unknown")
                if schema_spec.proof_premises is None:
                    raise ValueError("registered proof schema has no premise contract")
                flat_transitivity = (
                    schema_spec.name == "transitive"
                    and proof_form == "flat-chain-v1")
                if (len(premises) < 2 if flat_transitivity else
                        len(premises) != schema_spec.proof_premises):
                    raise ValueError("schema proof has the wrong number of premises")
                relation = schema.get("relation")
                if not isinstance(relation, str) or not relation.strip() or not _key(relation):
                    raise ValueError("schema relation instance is malformed")
                if not fact_is_present(type_fact):
                    raise ValueError("relation-type assertion is not in the fact snapshot")
                if (_triple(type_fact) != (_key(relation), _key("has relation type"),
                                           _key(schema_spec.name))
                        or not _scope_is_within(
                            type_fact.get("qualifiers", ()), expected_scope)):
                    raise ValueError("relation-type assertion does not license this schema")
                cs, cr, co = conclusion_key
                if schema_spec.name == "transitive":
                    if proof_form == "flat-chain-v1":
                        if len(premises) < 2 or cr != _key(relation):
                            raise ValueError("flat transitivity proof needs at least two matching edges")
                        visited = [visit(item, depth + 1) for item in premises]
                        triples = [item[0] for item in visited]
                        scopes = [item[1] for item in visited]
                        if any(triple[1] != _key(relation) for triple in triples):
                            raise ValueError("flat transitivity edge has a different relation")
                        if triples[0][0] != cs or triples[-1][2] != co:
                            raise ValueError("flat transitivity chain has the wrong endpoints")
                        if any(left[2] != right[0]
                               for left, right in zip(triples, triples[1:])):
                            raise ValueError("flat transitivity edges do not form a continuous chain")
                        if any(scope != expected_scope for scope in scopes):
                            raise ValueError("schema premises use a different qualifier scope")
                        return conclusion_key, expected_scope
                    if node.get("proof_form") is not None:
                        raise ValueError("transitivity proof form is unknown")
                    left, left_scope = visit(premises[0], depth + 1)
                    right, right_scope = visit(premises[1], depth + 1)
                    s1, r1, o1 = left
                    s2, r2, o2 = right
                    if (r1 != _key(relation) or r2 != _key(relation)
                            or cr != _key(relation)):
                        raise ValueError("transitivity schema relation does not match its instance")
                    if s1 != cs or o1 != s2 or o2 != co:
                        raise ValueError("transitivity premises do not form a continuous chain")
                    if left_scope != right_scope or left_scope != expected_scope:
                        raise ValueError("schema premises use a different qualifier scope")
                    return conclusion_key, left_scope
                premise, premise_scope = visit(premises[0], depth + 1)
                ps, pr, po = premise
                if (cr != _key(relation) or pr != _key(relation)
                        or ps != co or po != cs):
                    raise ValueError("symmetry premise does not reverse the conclusion")
                if premise_scope != expected_scope:
                    raise ValueError("symmetry premise uses a different qualifier scope")
                return conclusion_key, premise_scope
            if kind != "rule":
                raise ValueError("unknown proof step kind")
            rule = node.get("rule")
            premises = node.get("premises")
            if not isinstance(rule, Mapping) or not isinstance(premises, list):
                raise ValueError("rule proof step must contain a rule and premise proofs")
            key = _rule_key(rule)
            if key not in trusted_rules:
                raise ValueError("rule is not present in the trusted rule set")
            cs, cr, co = conclusion_key
            ternary = bool(key[3])
            expected_premise_count = 3 if ternary else 2
            if len(premises) != expected_premise_count:
                raise ValueError("rule proof has the wrong number of premise proofs")
            visited = [visit(item, depth + 1) for item in premises]
            triples = [item[0] for item in visited]
            scopes = [item[1] for item in visited]
            if any(scope != expected_scope for scope in scopes):
                raise ValueError("premise proofs use a different qualifier scope")
            if ternary:
                (s1, r1, o1), (s2, r2, o2), (s3, r3, o3) = triples
                if (r1 != _key(key[1]) or r2 != _key(key[2])
                        or r3 != _key(key[3]) or cr != _key(key[4])):
                    raise ValueError("premise or conclusion relation does not match the rule")
                if s1 != cs or o1 != s2 or o2 != s3 or o3 != co:
                    raise ValueError("three premise proofs do not form a continuous chain")
                kind_facts = node.get("middle_kind_facts")
                if not isinstance(kind_facts, list) or len(kind_facts) != 2:
                    raise ValueError("three-premise proof must cite both middle-kind facts")
                _verify_kind_fact(kind_facts[0], fact_is_present, o1, key[5], expected_scope)
                _verify_kind_fact(kind_facts[1], fact_is_present, o2, key[6], expected_scope)
                if node.get("middle_kind_fact") is not None:
                    raise ValueError("three-premise proof has malformed kind evidence")
            else:
                (s1, r1, o1), (s2, r2, o2) = triples
                if (r1 != _key(key[1]) or r2 != _key(key[2])
                        or cr != _key(key[4])):
                    raise ValueError("premise or conclusion relation does not match the rule")
                if s1 != cs or o1 != s2 or o2 != co:
                    raise ValueError("premise proofs do not join to the stated conclusion")
                middle_kind_fact = node.get("middle_kind_fact")
                if key[5]:
                    _verify_kind_fact(middle_kind_fact, fact_is_present, o1,
                                      key[5], expected_scope)
                elif middle_kind_fact is not None:
                    raise ValueError("untyped rule proof contains unexpected kind evidence")
                if node.get("middle_kind_facts") is not None:
                    raise ValueError("two-premise proof has malformed kind evidence")
            return conclusion_key, scopes[0]

        actual, actual_scope = visit(proof, 0)
        if expected_conclusion is not None and actual != _triple(expected_conclusion):
            return RuleProofCheck(False, "proof does not establish the requested conclusion")
        if actual_scope != expected_scope:
            return RuleProofCheck(False, "proof does not establish the requested qualifier scope")
        return RuleProofCheck(True, "valid recursive rule proof")
    except (TypeError, ValueError, AttributeError, RecursionError) as error:
        return RuleProofCheck(False, str(error) or "malformed inference proof")


def _triple(item: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    values = (item.get("subject"), item.get("relation"), item.get("object"))
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("triple fields must be non-empty text")
    triple = tuple(_key(value) for value in values)
    if not all(triple):
        raise ValueError("triple fields must contain searchable text")
    return triple  # type: ignore[return-value]


def _rule_key(rule: Mapping[str, Any]) -> tuple[str, ...]:
    fields = ("rule_id", "first_relation", "second_relation")
    values = tuple(rule.get(field) for field in fields)
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("rule fields must be non-empty text")
    conclusion = rule.get("conclusion_relation")
    if not isinstance(conclusion, str) or not conclusion.strip():
        raise ValueError("rule conclusion relation must be non-empty text")
    third_relation = rule.get("third_relation")
    if third_relation is not None and (not isinstance(third_relation, str)
                                       or not third_relation.strip()
                                       or not _key(third_relation)):
        raise ValueError("rule third relation must be non-empty searchable text")
    middle_kind = rule.get("middle_kind")
    if middle_kind is not None and (not isinstance(middle_kind, str)
                                    or not middle_kind.strip()
                                    or not _key(middle_kind)):
        raise ValueError("rule middle kind must be non-empty searchable text")
    second_middle_kind = rule.get("second_middle_kind")
    if second_middle_kind is not None and (
            not isinstance(second_middle_kind, str)
            or not second_middle_kind.strip() or not _key(second_middle_kind)):
        raise ValueError("rule second middle kind must be non-empty searchable text")
    if third_relation is None:
        if second_middle_kind is not None:
            raise ValueError("second middle kind requires a third relation")
    elif middle_kind is None or second_middle_kind is None:
        raise ValueError("three-premise rules require both middle kinds")
    return values + (third_relation or "", conclusion,
                     middle_kind or "", second_middle_kind or "")  # type: ignore[return-value]


def _verify_kind_fact(fact: Any,
                      fact_is_present: Callable[[Mapping[str, Any]], bool],
                      entity: tuple[str, ...], kind: str,
                      expected_scope: Any) -> None:
    if not isinstance(fact, Mapping):
        raise ValueError("typed rule proof is missing its middle-kind fact")
    if not fact_is_present(fact):
        raise ValueError("middle-kind fact is not present in the fact snapshot")
    if (_triple(fact) != (entity, _key("is-a"), _key(kind))
            or not _scope_is_within(fact.get("qualifiers", ()), expected_scope)):
        raise ValueError("middle-kind fact does not establish the declared kind")


def _fact_signature(fact: Mapping[str, Any]) -> tuple[Any, ...]:
    qualifiers = tuple(sorted((_key(str(name)), _key(str(value)))
                              for name, value in fact.get("qualifiers", [])))
    sources = tuple(sorted(str(source) for source in fact.get("sources", [])))
    return _triple(fact), sources, qualifiers
