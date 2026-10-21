"""Visible generation rules for the Phase 10 rule-only generation stack.

The rule file is data, not code. It defines genre schemas, clause
constructions, transitions, clarity substitutions, and style profiles. The
generator in :mod:`crms_generation` selects facts and composes clauses from
these rules; it does not store whole-answer templates.

No LLM or model weights are loaded here. The offline teacher may propose new
rules in a later slice, but every active rule is reviewed and versioned like
the other CRMS rule families.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

PROJECT = Path(__file__).resolve().parent
DEFAULT_RULES_PATH = PROJECT / "crms_generation_rules.json"
SUPPORTED_FORMAT = "crms-generation-rules"
SUPPORTED_VERSION = 1


class GenerationRuleError(ValueError):
    """A generation rule file or rule reference is malformed."""


@dataclass(frozen=True)
class MoveRule:
    name: str
    required: bool
    roles: tuple[str, ...]
    max_facts: int
    transition: str | None = None

    def validate(self) -> None:
        if not self.name:
            raise GenerationRuleError("move name is empty")
        if not self.roles:
            raise GenerationRuleError(f"move {self.name!r} has no roles")
        if self.max_facts < 1:
            raise GenerationRuleError(
                f"move {self.name!r} has invalid max_facts")
        if self.transition is not None and not self.transition.strip():
            raise GenerationRuleError(
                f"move {self.name!r} has an empty transition")


@dataclass(frozen=True)
class GenreRule:
    name: str
    moves: tuple[MoveRule, ...]
    paragraph_breaks_after: tuple[str, ...]

    def validate(self) -> None:
        if not self.moves:
            raise GenerationRuleError(f"genre {self.name!r} has no moves")
        seen: set[str] = set()
        for move in self.moves:
            move.validate()
            if move.name in seen:
                raise GenerationRuleError(
                    f"genre {self.name!r} repeats move {move.name!r}")
            seen.add(move.name)
        for move_name in self.paragraph_breaks_after:
            if move_name not in seen:
                raise GenerationRuleError(
                    f"genre {self.name!r} breaks after unknown move "
                    f"{move_name!r}")


@dataclass(frozen=True)
class GenerationRules:
    path: Path
    digest: str
    genres: Mapping[str, GenreRule]
    constructions: Mapping[str, str]
    transitions: Mapping[str, str]
    clarity: Mapping[str, Any]
    styles: Mapping[str, Mapping[str, Any]]

    def genre(self, name: str) -> GenreRule:
        try:
            return self.genres[name]
        except KeyError as error:
            raise GenerationRuleError(
                f"unknown generation genre: {name!r}") from error

    def construction(self, name: str) -> str:
        try:
            return self.constructions[name]
        except KeyError as error:
            raise GenerationRuleError(
                f"unknown generation construction: {name!r}") from error

    def transition(self, name: str) -> str:
        return self.transitions.get(name, name)

    def style(self, name: str) -> Mapping[str, Any]:
        try:
            return self.styles[name]
        except KeyError as error:
            raise GenerationRuleError(
                f"unknown generation style: {name!r}") from error

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "digest": self.digest,
            "genres": sorted(self.genres),
            "constructions": sorted(self.constructions),
            "transitions": sorted(self.transitions),
            "styles": sorted(self.styles),
        }


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise GenerationRuleError(f"{label} must be an object")
    return value


def _move(raw: Any, genre: str) -> MoveRule:
    item = _require_mapping(raw, f"genre {genre!r} move")
    name = str(item.get("name", "")).strip()
    required = item.get("required", False)
    roles = item.get("roles")
    max_facts = item.get("max_facts", 1)
    transition = item.get("transition")
    if not isinstance(required, bool):
        raise GenerationRuleError(
            f"move {name!r} required must be a bool")
    if not isinstance(roles, list) or not roles:
        raise GenerationRuleError(f"move {name!r} roles must be a list")
    if not isinstance(max_facts, int):
        raise GenerationRuleError(
            f"move {name!r} max_facts must be an integer")
    if transition is not None and not isinstance(transition, str):
        raise GenerationRuleError(
            f"move {name!r} transition must be text")
    move = MoveRule(
        name=name,
        required=required,
        roles=tuple(str(role).strip() for role in roles if str(role).strip()),
        max_facts=max_facts,
        transition=(transition.strip() if transition else None),
    )
    move.validate()
    return move


def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> GenerationRules:
    """Load and validate a visible generation rule file."""
    rule_path = Path(path)
    raw_bytes = rule_path.read_bytes()
    raw = json.loads(raw_bytes.decode("utf-8"))
    return rules_from_mapping(
        raw, path=rule_path,
        digest=hashlib.sha256(raw_bytes).hexdigest())


def rules_from_mapping(raw: Mapping[str, Any], *,
                       path: str | Path = "<memory>",
                       digest: str | None = None) -> GenerationRules:
    """Validate and construct rules from an in-memory JSON-compatible map."""
    rule_path = Path(path)
    if raw.get("format") != SUPPORTED_FORMAT:
        raise GenerationRuleError("unsupported generation rule format")
    if raw.get("version") != SUPPORTED_VERSION:
        raise GenerationRuleError("unsupported generation rule version")

    genres_raw = _require_mapping(raw.get("genres"), "genres")
    genres: dict[str, GenreRule] = {}
    for name, item in genres_raw.items():
        body = _require_mapping(item, f"genre {name!r}")
        moves_raw = body.get("moves")
        if not isinstance(moves_raw, list):
            raise GenerationRuleError(
                f"genre {name!r} moves must be a list")
        breaks = body.get("paragraph_breaks_after", [])
        if not isinstance(breaks, list):
            raise GenerationRuleError(
                f"genre {name!r} paragraph_breaks_after must be a list")
        genre = GenreRule(
            name=str(name),
            moves=tuple(_move(move, str(name)) for move in moves_raw),
            paragraph_breaks_after=tuple(str(item) for item in breaks),
        )
        genre.validate()
        genres[genre.name] = genre

    constructions = _require_mapping(
        raw.get("constructions"), "constructions")
    if not constructions:
        raise GenerationRuleError("constructions cannot be empty")
    for name, pattern in constructions.items():
        if not isinstance(pattern, str) or "{" not in pattern:
            raise GenerationRuleError(
                f"construction {name!r} must be a format pattern")

    transitions = _require_mapping(raw.get("transitions"), "transitions")
    for name, value in transitions.items():
        if not isinstance(value, str) or not value.strip():
            raise GenerationRuleError(
                f"transition {name!r} must be non-empty text")

    clarity = _require_mapping(raw.get("clarity"), "clarity")
    replacements = clarity.get("replacements", {})
    if not isinstance(replacements, dict):
        raise GenerationRuleError("clarity replacements must be an object")
    if not isinstance(clarity.get("max_sentence_words"), int):
        raise GenerationRuleError(
            "clarity max_sentence_words must be an integer")
    if not isinstance(clarity.get("jargon_terms", []), list):
        raise GenerationRuleError("clarity jargon_terms must be a list")

    styles = _require_mapping(raw.get("styles"), "styles")
    for name, profile in styles.items():
        item = _require_mapping(profile, f"style {name!r}")
        if not isinstance(item.get("max_sentence_words"), int):
            raise GenerationRuleError(
                f"style {name!r} max_sentence_words must be an integer")
        if not isinstance(item.get("include_transitions"), bool):
            raise GenerationRuleError(
                f"style {name!r} include_transitions must be a bool")
        if not isinstance(item.get("fuse"), bool):
            raise GenerationRuleError(
                f"style {name!r} fuse must be a bool")

    if digest is None:
        digest = hashlib.sha256(
            json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    return GenerationRules(
        path=rule_path,
        digest=digest,
        genres=genres,
        constructions={str(k): str(v) for k, v in constructions.items()},
        transitions={str(k): str(v) for k, v in transitions.items()},
        clarity=dict(clarity),
        styles={str(k): dict(v) for k, v in styles.items()},
    )
