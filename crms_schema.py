"""Shared vocabulary and metadata for declared relation schemas.

This registry describes schema names and their proof-facing metadata. It does
not accept declarations or verify evidence; callers must keep those checks in
their existing knowledge, inference, and independent-proof paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from crms_text import tokens as normalized_tokens


@dataclass(frozen=True)
class RelationSchemaSpec:
    name: str
    category: str
    surface_pattern: str
    proof_schema_id: str | None = None
    proof_premises: int | None = None
    validation_status: str | None = None
    validator: str | None = None
    proof_forms: tuple[str, ...] = ()
    integrity_mode: str | None = None


RELATION_SCHEMA_SPECS = (
    RelationSchemaSpec("transitive", "derivation", "transitive",
                       "transitivity-v1", 2, "validated",
                       "builtin-schema-check-v1", ("flat-chain-v1",)),
    RelationSchemaSpec("symmetric", "derivation", "symmetric",
                       "symmetry-v1", 1, "validated",
                       "builtin-schema-check-v1"),
    RelationSchemaSpec("irreflexive", "integrity", "irreflexive",
                       integrity_mode="self-edge-denial"),
    RelationSchemaSpec("asymmetric", "integrity", "asymmetric",
                       integrity_mode="reverse-edge-denial"),
    RelationSchemaSpec("functional", "integrity", "functional",
                       integrity_mode="alternative-edge-denial"),
    RelationSchemaSpec("closed-world", "integrity", r"closed[- ]world",
                       integrity_mode="closed-world-absence"),
)

RELATION_SCHEMA_BY_NAME = {spec.name: spec for spec in RELATION_SCHEMA_SPECS}
RELATION_SCHEMA_TYPES = frozenset(spec.name for spec in RELATION_SCHEMA_SPECS)
DERIVATION_SCHEMA_TYPES = frozenset(
    spec.name for spec in RELATION_SCHEMA_SPECS
    if spec.category == "derivation")
INTEGRITY_SCHEMA_TYPES = frozenset(
    spec.name for spec in RELATION_SCHEMA_SPECS
    if spec.category == "integrity")
WITNESS_CONSTRAINT_DENIAL_TYPES = frozenset(
    spec.name for spec in RELATION_SCHEMA_SPECS
    if spec.integrity_mode in {
        "self-edge-denial", "reverse-edge-denial", "alternative-edge-denial"})
PROOF_SCHEMA_SPECS = {
    spec.proof_schema_id: spec for spec in RELATION_SCHEMA_SPECS
    if spec.proof_schema_id is not None
}

TRANSITIVITY_SCHEMA = RELATION_SCHEMA_BY_NAME["transitive"]
SYMMETRY_SCHEMA = RELATION_SCHEMA_BY_NAME["symmetric"]
CLOSED_WORLD_SCHEMA = RELATION_SCHEMA_BY_NAME["closed-world"]

_SCHEMA_BY_KEY = {
    normalized_tokens(spec.name): spec for spec in RELATION_SCHEMA_SPECS
}


def relation_schema_spec(value: str | Iterable[str]
                         ) -> RelationSchemaSpec | None:
    """Resolve a canonical schema name or normalized token sequence."""
    key = normalized_tokens(value) if isinstance(value, str) else tuple(value)
    return _SCHEMA_BY_KEY.get(key)


def relation_schema_pattern() -> str:
    """Regex alternation for the explicit declaration extractor."""
    return "|".join(spec.surface_pattern for spec in RELATION_SCHEMA_SPECS)

