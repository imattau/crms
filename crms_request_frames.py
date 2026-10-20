"""Learned request frames with typed slots.

A request frame is an exact token template learned from teacher-marked
examples. It is not a regex and it does not guess missing wording. Literal
tokens must match exactly; slot fillers are parsed by their declared type. A
frame is licensed only after at least two varied, grounded examples.

The store persists examples, not frames. Licensed frames are derived
deterministically, so a frame cannot outlive the evidence that licensed it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

FRAME_VERSION = 1
SLOT_KINDS = ("integer-list", "claim", "procedure", "text")
GOALS = (
    "select-then-procedure",
    "research-answer",
    "math-compute",
    "unit-convert",
    "translate",
    "generate-code",
    "write-story",
)
MAX_VALUES = 32
MAX_SLOT_TOKENS = 96
MAX_MATCHES = 64

_TOKEN = re.compile(r"-?\d+|[A-Za-z]+|[.!?]+")
_MARKER = re.compile(r"\{([a-z][a-z0-9_]*):([a-z][a-z0-9-]*):(.*?)\}")
_INTEGER = re.compile(r"-?\d+")


class RequestFrameError(ValueError):
    """A frame example or store is malformed."""


@dataclass(frozen=True)
class Token:
    text: str
    normalized: str
    start: int
    end: int


@dataclass(frozen=True)
class FrameSlot:
    name: str
    kind: str

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.name):
            raise RequestFrameError(f"invalid slot name: {self.name!r}")
        if self.kind not in SLOT_KINDS:
            raise RequestFrameError(f"invalid slot kind: {self.kind!r}")

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {"kind": "slot", "name": self.name, "slot_kind": self.kind}


@dataclass(frozen=True)
class FrameExample:
    text: str
    goal: str
    source_id: str
    fixed_procedure: str | None = None

    def validate(self) -> None:
        if not self.text.strip():
            raise RequestFrameError("frame example is empty")
        if self.goal not in GOALS:
            raise RequestFrameError(f"unsupported frame goal: {self.goal!r}")
        if not self.source_id.strip():
            raise RequestFrameError("frame example requires a source id")
        if self.fixed_procedure is not None and not self.fixed_procedure.strip():
            raise RequestFrameError("fixed procedure must be non-empty")
        parsed = parse_marked_example(self.text)
        if (self.fixed_procedure is not None
                and any(slot.kind == "procedure"
                        for slot in parsed.slot_order)):
            raise RequestFrameError(
                "a frame cannot have both a procedure slot and a fixed "
                "procedure")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "text": self.text,
            "goal": self.goal,
            "source_id": self.source_id,
            "fixed_procedure": self.fixed_procedure,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "FrameExample":
        item = cls(
            text=str(raw.get("text", "")),
            goal=str(raw.get("goal", "")),
            source_id=str(raw.get("source_id", "")),
            fixed_procedure=(str(raw["fixed_procedure"])
                             if raw.get("fixed_procedure") is not None
                             else None),
        )
        item.validate()
        return item


@dataclass(frozen=True)
class RequestFrame:
    frame_id: str
    goal: str
    parts: tuple[str | FrameSlot, ...]
    fixed_procedure: str | None
    examples: tuple[FrameExample, ...] = ()
    slot_bindings: tuple[tuple[str, str], ...] = ()

    def template_text(self) -> str:
        rendered = []
        for part in self.parts:
            if isinstance(part, FrameSlot):
                rendered.append(f"{{{part.name}:{part.kind}}}")
            else:
                rendered.append(part)
        return " ".join(rendered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "goal": self.goal,
            "fixed_procedure": self.fixed_procedure,
            "template": self.template_text(),
            "examples": [example.to_dict() for example in self.examples],
        }


@dataclass(frozen=True)
class FrameMatch:
    frame: RequestFrame
    slots: Mapping[str, Any]
    surface: Mapping[str, str]
    text: str
    procedure_anchored: bool = False

    def semantic_key(self) -> tuple[Any, ...]:
        return (
            self.frame.goal,
            self.frame.fixed_procedure,
            tuple(sorted(self.slots.items())),
        )


@dataclass(frozen=True)
class FrameMatchResult:
    status: str
    matches: tuple[FrameMatch, ...] = ()
    reason: str = ""

    @property
    def match(self) -> FrameMatch | None:
        return self.matches[0] if len(self.matches) == 1 else None


@dataclass(frozen=True)
class FrameLearningResult:
    status: str
    message: str
    frame: RequestFrame | None = None
    example_count: int = 0

    @property
    def licensed(self) -> bool:
        return self.status == "licensed"


def tokenize(text: str) -> tuple[Token, ...]:
    """Tokenize words, signed integers, and sentence boundaries.

    Punctuation is normally a boundary and is dropped. A run of ``.``, ``!``,
    or ``?`` becomes a single ``<end>`` token, so a sentence break can separate
    two otherwise adjacent slots without admitting arbitrary punctuation.
    """
    tokens = []
    for match in _TOKEN.finditer(text):
        surface = match.group(0)
        normalized = ("<end>" if surface[0] in ".!?"
                      else surface.casefold())
        tokens.append(Token(surface, normalized, match.start(), match.end()))
    return tuple(tokens)


def _normalized_text(text: str) -> str:
    return " ".join(token.normalized for token in tokenize(text))


def _strip_span(text: str, start: int, end: int) -> str:
    return text[start:end].strip(" \t\r\n,;:.!?\"'`")


@dataclass(frozen=True)
class _ParsedExample:
    parts: tuple[str | FrameSlot, ...]
    bindings: Mapping[str, str]
    slot_order: tuple[FrameSlot, ...]


def parse_marked_example(text: str) -> _ParsedExample:
    """Parse `{name:kind:filler}` markers into a literal/slot sequence.

    Adjacent free-text slots are rejected because their boundary is not
    independently decidable. A literal token or a narrow typed slot (integer
    list or procedure) must separate them.
    """
    if not text.strip():
        raise RequestFrameError("frame example is empty")
    parts: list[str | FrameSlot] = []
    bindings: dict[str, str] = {}
    order: list[FrameSlot] = []
    cursor = 0
    previous_was_slot = False
    for marker in _MARKER.finditer(text):
        literal = text[cursor:marker.start()]
        if "{" in literal or "}" in literal:
            raise RequestFrameError("unbalanced frame marker")
        literal_tokens = tokenize(literal)
        name, kind, filler = marker.group(1), marker.group(2), marker.group(3)
        slot = FrameSlot(name, kind)
        slot.validate()
        if previous_was_slot and not literal_tokens:
            previous = parts[-1]
            # Adjacent slots need a decidable boundary. Integer-list and
            # procedure slots have narrow grammars or a learned vocabulary;
            # two free-text slots with no literal boundary do not.
            narrow = {"integer-list", "procedure"}
            if not (isinstance(previous, FrameSlot)
                    and (previous.kind in narrow or slot.kind in narrow)):
                raise RequestFrameError(
                    "adjacent slots need a literal boundary between them")
        parts.extend(token.normalized for token in literal_tokens)
        if name in bindings:
            raise RequestFrameError(f"duplicate slot marker: {name!r}")
        if not filler.strip():
            raise RequestFrameError(f"slot {name!r} has an empty filler")
        parts.append(slot)
        order.append(slot)
        bindings[name] = _normalized_filler(filler)
        _validate_filler(slot, bindings[name])
        cursor = marker.end()
        previous_was_slot = True
    tail = text[cursor:]
    if "{" in tail or "}" in tail:
        raise RequestFrameError("unbalanced frame marker")
    tail_tokens = tokenize(tail)
    if previous_was_slot and not tail_tokens:
        # A trailing slot is fine; a trailing literal is optional.
        pass
    parts.extend(token.normalized for token in tail_tokens)
    if not order:
        raise RequestFrameError("frame example has no slot markers")
    if not bindings:
        raise RequestFrameError("frame example has no slot bindings")
    return _ParsedExample(tuple(parts), bindings, tuple(order))


def _normalized_filler(filler: str) -> str:
    return " ".join(token.normalized for token in tokenize(filler))


def _template_key(parts: Iterable[str | FrameSlot]) -> tuple[Any, ...]:
    key = []
    for part in parts:
        if isinstance(part, FrameSlot):
            key.append(("slot", part.name, part.kind))
        else:
            key.append(("literal", part))
    return tuple(key)


def _frame_id(goal: str, parts: tuple[str | FrameSlot, ...],
              fixed_procedure: str | None) -> str:
    payload = {
        "goal": goal,
        "parts": _template_key(parts),
        "fixed_procedure": fixed_procedure,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"frame-{digest}"


def _slot_names(parts: tuple[str | FrameSlot, ...]) -> tuple[str, ...]:
    return tuple(part.name for part in parts if isinstance(part, FrameSlot))


def _license_examples(examples: tuple[FrameExample, ...],
                      parts: tuple[str | FrameSlot, ...]
                      ) -> tuple[bool, str]:
    if len(examples) < 2:
        return False, "needs at least two grounded examples"
    if len({_normalized_text(example.text) for example in examples}) < 2:
        return False, "examples must use different wording or fillers"
    if any(not example.source_id.strip() for example in examples):
        return False, "every example needs a source id"
    slot_names = _slot_names(parts)
    parsed = [parse_marked_example(example.text) for example in examples]
    varied = False
    for name in slot_names:
        fillers = {parsed_example.bindings.get(name, "")
                   for parsed_example in parsed}
        if len(fillers) >= 2:
            varied = True
            break
    if not varied:
        return False, "at least one slot needs two distinct fillers"
    return True, ""


def _group_examples(examples: Iterable[FrameExample]
                    ) -> dict[tuple[Any, ...],
                              tuple[tuple[str | FrameSlot, ...],
                                    list[tuple[FrameExample,
                                               _ParsedExample]]]]:
    groups: dict[tuple[Any, ...],
                 tuple[tuple[str | FrameSlot, ...],
                       list[tuple[FrameExample, _ParsedExample]]]] = {}
    for example in examples:
        example.validate()
        parsed = parse_marked_example(example.text)
        key = (
            example.goal,
            _template_key(parsed.parts),
            example.fixed_procedure,
        )
        if key not in groups:
            groups[key] = (parsed.parts, [])
        groups[key][1].append((example, parsed))
    return groups


def _frame_from_group(goal: str, parts: tuple[str | FrameSlot, ...],
                      fixed_procedure: str | None,
                      members: list[tuple[FrameExample, _ParsedExample]]
                      ) -> RequestFrame:
    examples = tuple(member[0] for member in members)
    bindings = tuple(
        (example.source_id, example.text) for example in examples)
    return RequestFrame(
        frame_id=_frame_id(goal, parts, fixed_procedure),
        goal=goal,
        parts=parts,
        fixed_procedure=fixed_procedure,
        examples=examples,
        slot_bindings=bindings,
    )


def derived_frames(examples: Iterable[FrameExample]) -> tuple[RequestFrame, ...]:
    frames = []
    for (_goal, _parts_key, fixed), (parts, members) in (
            _group_examples(examples).items()):
        licensed, _reason = _license_examples(
            tuple(member[0] for member in members), parts)
        if licensed:
            frames.append(_frame_from_group(
                members[0][0].goal, parts, fixed, members))
    frames.sort(key=lambda frame: frame.frame_id)
    return tuple(frames)


def _match_parts(parts: tuple[str | FrameSlot, ...], text: str,
                  tokens: tuple[Token, ...]) -> list[dict[str, str]]:
    """Return all slot bindings that align the full token sequence."""
    results: list[dict[str, str]] = []

    def visit(index: int, position: int, bindings: dict[str, str]) -> None:
        if len(results) >= MAX_MATCHES:
            return
        if index == len(parts):
            if position == len(tokens):
                results.append(dict(bindings))
            elif (position == len(tokens) - 1
                  and tokens[position].normalized == "<end>"):
                # Final sentence punctuation is optional when the template
                # has no explicit trailing boundary.
                results.append(dict(bindings))
            return
        part = parts[index]
        if isinstance(part, str):
            if position < len(tokens) and tokens[position].normalized == part:
                visit(index + 1, position + 1, bindings)
            elif (part == "<end>" and position == len(tokens)
                  and index == len(parts) - 1):
                # A template that ends with sentence punctuation still
                # matches a request without a final full stop.
                visit(index + 1, position, bindings)
            return
        remaining = len(tokens) - position
        if remaining <= 0:
            return
        if index == len(parts) - 1:
            ends = (len(tokens),)
        else:
            next_part = parts[index + 1]
            if isinstance(next_part, FrameSlot):
                # The next slot needs at least one token. The procedure
                # vocabulary will later choose the licensed boundary.
                ends = tuple(range(position + 1, len(tokens)))
            else:
                ends = tuple(
                    end for end in range(position + 1, len(tokens))
                    if tokens[end].normalized == next_part)
            if not ends:
                return
        for end in ends:
            if end - position > MAX_SLOT_TOKENS:
                continue
            raw = _strip_span(text, tokens[position].start, tokens[end - 1].end)
            if not raw:
                continue
            bindings[part.name] = raw
            visit(index + 1, end, bindings)
            del bindings[part.name]

    visit(0, 0, {})
    return results


def _parse_integer_list(raw: str) -> tuple[int, ...] | None:
    tokens = tokenize(raw)
    if not tokens:
        return None
    values: list[int] = []
    expecting_value = True
    for token in tokens:
        if token.normalized == "and":
            if expecting_value:
                return None
            expecting_value = True
            continue
        if not _INTEGER.fullmatch(token.normalized):
            return None
        values.append(int(token.normalized))
        expecting_value = False
    if expecting_value or not values or len(values) > MAX_VALUES:
        return None
    return tuple(values)


def _validate_filler(slot: FrameSlot, filler: str) -> None:
    if slot.kind == "integer-list":
        if _parse_integer_list(filler) is None:
            raise RequestFrameError(
                f"slot {slot.name!r} needs a valid integer-list filler")
        return
    if slot.kind == "claim":
        words = [token.normalized for token in tokenize(filler)]
        if not words or any(_INTEGER.fullmatch(word) for word in words):
            raise RequestFrameError(
                f"slot {slot.name!r} needs a non-numeric claim filler")
        return
    if not filler.strip():
        raise RequestFrameError(f"slot {slot.name!r} has an empty filler")


def _bind_slots(frame: RequestFrame, raw: Mapping[str, str]
                ) -> Mapping[str, Any] | None:
    slots: dict[str, Any] = {}
    for part in frame.parts:
        if not isinstance(part, FrameSlot):
            continue
        value = raw.get(part.name, "")
        if part.kind == "integer-list":
            parsed = _parse_integer_list(value)
            if parsed is None:
                return None
            slots[part.name] = parsed
        elif part.kind in {"claim", "procedure", "text"}:
            if not value.strip():
                return None
            words = [token.normalized for token in tokenize(value)]
            if not words:
                return None
            if part.kind == "claim":
                # A relation claim is not a numeric span and cannot absorb a
                # sequence connective or a relative pronoun that belongs to
                # the template.
                if any(_INTEGER.fullmatch(word) for word in words):
                    return None
                if "then" in words:
                    return None
                if words[0] in {"then", "after", "that", "which", "who",
                                "whom", "whose", "and", "or"}:
                    return None
                if words[-1] in {"and", "then", "after"}:
                    return None
            if part.kind == "procedure":
                if words[0] in {"then", "and", "after"}:
                    return None
            if part.kind == "text":
                if "<end>" in words:
                    return None
                if any(left == "and" and right in {
                        "who", "what", "where", "when", "why", "how"}
                       for left, right in zip(words, words[1:])):
                    return None
            slots[part.name] = value.strip()
        else:
            return None
    return slots


def _normalize_procedure_for_vocabulary(text: str) -> str:
    text = " ".join(text.strip().rstrip(".!?").split())
    text = re.sub(r"\s+and\s+then\s+", " then ", text, flags=re.IGNORECASE)
    after = re.fullmatch(r"(.+?)\s+after\s+(.+)", text, flags=re.IGNORECASE)
    if after is not None:
        text = f"{after.group(2).strip()} then {after.group(1).strip()}"
    return text


def _procedure_is_anchored(frame: RequestFrame, raw: Mapping[str, str],
                           procedure_phrases: Iterable[str]) -> bool:
    """Whether every procedure slot is exactly a learned phrase sequence."""
    slots = [part for part in frame.parts
             if isinstance(part, FrameSlot) and part.kind == "procedure"]
    if not slots:
        return False
    phrases = {" ".join(phrase.casefold().split())
               for phrase in procedure_phrases}
    if not phrases:
        return False
    for slot in slots:
        text = _normalize_procedure_for_vocabulary(raw.get(slot.name, ""))
        folded = " ".join(text.casefold().split())
        if folded in phrases:
            continue
        parts = re.split(r"\s+(?:then|and)\s+", text, flags=re.IGNORECASE)
        if len(parts) < 2 or any(
                " ".join(part.casefold().split()) not in phrases
                for part in parts):
            return False
    return True


def _has_adjacent_procedure_slots(frame: RequestFrame) -> bool:
    for left, right in zip(frame.parts, frame.parts[1:]):
        if (isinstance(left, FrameSlot) and isinstance(right, FrameSlot)
                and "procedure" in {left.kind, right.kind}):
            return True
    return False


def match_frames(frames: Iterable[RequestFrame], text: str, *,
                 procedure_phrases: Iterable[str] = (),
                 allowed_frame_ids: Iterable[str] | None = None
                 ) -> FrameMatchResult:
    procedure_phrases = tuple(procedure_phrases)
    frame_list = list(frames)
    if allowed_frame_ids is not None:
        allowed = set(allowed_frame_ids)
        frame_list = [frame for frame in frame_list
                      if frame.frame_id in allowed]
    tokens = tokenize(text)
    if not tokens:
        return FrameMatchResult("no_match", reason="empty request")
    candidates: list[FrameMatch] = []
    for frame in frame_list:
        requires_anchor = _has_adjacent_procedure_slots(frame)
        for raw in _match_parts(frame.parts, text, tokens):
            slots = _bind_slots(frame, raw)
            if slots is None:
                continue
            anchored = _procedure_is_anchored(
                frame, raw, procedure_phrases)
            if requires_anchor and not anchored:
                continue
            candidates.append(FrameMatch(
                frame, slots, raw, text, anchored))
    if not candidates:
        return FrameMatchResult(
            "no_match", reason="no licensed frame matches this wording")
    # Collapse semantically identical matches produced by duplicate examples
    # or equivalent templates. Prefer the candidate whose procedure slot is
    # fully licensed by the learned procedure vocabulary.
    unique: dict[tuple[Any, ...], FrameMatch] = {}
    for candidate in candidates:
        key = candidate.semantic_key()
        existing = unique.get(key)
        if existing is None or (candidate.procedure_anchored
                                and not existing.procedure_anchored):
            unique[key] = candidate
    selected = list(unique.values())
    if len(selected) > 1:
        anchored = [candidate for candidate in selected
                    if candidate.procedure_anchored]
        if anchored:
            selected = anchored
    selected.sort(key=lambda item: (item.frame.frame_id, item.text))
    if len(selected) > 1:
        return FrameMatchResult(
            "ambiguous",
            tuple(selected),
            "more than one licensed frame matches this request")
    return FrameMatchResult("matched", (selected[0],))


@dataclass
class RequestFrameStore:
    examples: list[FrameExample] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "RequestFrameStore":
        path = Path(path)
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RequestFrameError(f"could not read frame store: {error}") from error
        if not isinstance(raw, Mapping):
            raise RequestFrameError("frame store must be a JSON object")
        try:
            version = int(raw.get("version", 0))
        except (TypeError, ValueError) as error:
            raise RequestFrameError("invalid frame store version") from error
        if version != FRAME_VERSION:
            raise RequestFrameError("unsupported frame store version")
        items = raw.get("examples", ())
        if not isinstance(items, list):
            raise RequestFrameError("frame examples must be a list")
        examples = []
        for item in items:
            if not isinstance(item, Mapping):
                raise RequestFrameError("frame example must be an object")
            examples.append(FrameExample.from_dict(item))
        return cls(examples)

    def add_seed_file(self, path: Path) -> int:
        path = Path(path)
        if not path.is_file():
            return 0
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RequestFrameError(f"could not read seed frames: {error}") from error
        if not isinstance(raw, Mapping):
            raise RequestFrameError("seed frame store must be a JSON object")
        added = 0
        items = raw.get("examples", ())
        if not isinstance(items, list):
            raise RequestFrameError("seed frame examples must be a list")
        for item in items:
            if not isinstance(item, Mapping):
                raise RequestFrameError("seed frame example must be an object")
            example = FrameExample.from_dict(item)
            if example not in self.examples:
                self.examples.append(example)
                added += 1
        return added

    def frames(self) -> tuple[RequestFrame, ...]:
        return derived_frames(self.examples)

    def match(self, text: str, *,
              procedure_phrases: Iterable[str] = (),
              allowed_frame_ids: Iterable[str] | None = None
              ) -> FrameMatchResult:
        return match_frames(self.frames(), text,
                            procedure_phrases=procedure_phrases,
                            allowed_frame_ids=allowed_frame_ids)

    def add_example(self, text: str, goal: str, source_id: str,
                    fixed_procedure: str | None = None
                    ) -> FrameLearningResult:
        example = FrameExample(text, goal, source_id, fixed_procedure)
        example.validate()
        parsed = parse_marked_example(text)
        if fixed_procedure is not None and any(
                isinstance(part, FrameSlot) and part.kind == "procedure"
                for part in parsed.parts):
            raise RequestFrameError(
                "a frame cannot have both a procedure slot and a fixed "
                "procedure")
        if example in self.examples:
            return self.learning_result_for(parsed.parts, goal,
                                            fixed_procedure,
                                            message="example already stored")
        self.examples.append(example)
        return self.learning_result_for(parsed.parts, goal, fixed_procedure)

    def learning_result_for(self, parts: tuple[str | FrameSlot, ...],
                            goal: str, fixed_procedure: str | None,
                            message: str = "") -> FrameLearningResult:
        key = (goal, _template_key(parts), fixed_procedure)
        group = _group_examples(self.examples).get(key)
        if group is None:
            examples = ()
            members = []
            actual_parts = parts
        else:
            actual_parts, members = group
            examples = tuple(member[0] for member in members)
        licensed, reason = _license_examples(examples, actual_parts)
        if licensed:
            frame = _frame_from_group(
                goal, actual_parts, fixed_procedure, members)
            return FrameLearningResult(
                "licensed",
                message or f"frame licensed from {len(examples)} examples",
                frame, len(examples))
        return FrameLearningResult(
            "need_more_examples",
            message or reason,
            None, len(examples))

    def describe(self) -> list[str]:
        lines = []
        for frame in self.frames():
            sample = frame.examples[0].text if frame.examples else ""
            lines.append(
                f"{frame.frame_id}  goal={frame.goal}  "
                f"examples={len(frame.examples)}  {frame.template_text()}")
            if sample:
                lines.append(f"  example: {sample}")
            if frame.fixed_procedure:
                lines.append(f"  fixed procedure: {frame.fixed_procedure}")
        return lines

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": FRAME_VERSION,
            "examples": [example.to_dict() for example in self.examples],
        }
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        temporary.replace(path)
