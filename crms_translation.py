"""Example-grounded translation and style rewrites over aligned sentence frames.

This prototype does not infer an open-ended bilingual lexicon. A reviewed
template pair states the exact supported frame and named slots; aligned
examples license either copied slots or exact source-to-target slot mappings.
Same-language rewrites use the same bounded mechanism and explicit register.
Unseen values for translated slots remain unknown unless the slot is copied.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from crms_research import (
    SearchHit, _is_code_source, _sentence_context_kind, _sentence_spans,
)
from crms_text import tokens


_SLOT_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")
_TRANSLATE_PREFIX = (
    r"(?:(?:please\s+)|(?:(?:can|could|would)\s+you"
    r"(?:\s+please)?\s+))?translate\s+")
_REQUEST_RE = re.compile(
    r"\s*" + _TRANSLATE_PREFIX +
    r"from\s+([^:]+?)\s+(?:to|into)\s+([^:]+?)"
    r"(?:\s+in\s+([^:]+?)\s+register)?\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_INLINE_REQUEST_RE = re.compile(
    r"\s*" + _TRANSLATE_PREFIX +
    r"(.+?)\s+from\s+(.+?)\s+"
    r"(?:to|into)\s+(.+?)"
    r"(?:\s+in\s+(.+?)\s+register)?\s*[.!?]*\s*\Z",
    re.IGNORECASE | re.DOTALL)
_TARGET_ONLY_REQUEST_RE = re.compile(
    r"\s*" + _TRANSLATE_PREFIX +
    r"(?:\"(.+?)\"|'(.+?)'|“(.+?)”|‘(.+?)’)\s+(?:to|into)\s+([^.!?]+?)"
    r"(?:\s+in\s+([^.!?]+?)\s+register)?\s*[.!?]*\s*\Z",
    re.IGNORECASE | re.DOTALL)
_HOW_SAY_REQUEST_RE = re.compile(
    r"\s*(?:please\s+)?how\s+(?:do\s+i|do\s+you|would\s+i|would\s+you)\s+say\s+"
    r"(?P<body>.+?)[!?]*\s*\Z", re.IGNORECASE | re.DOTALL)


def _how_say_parts(body: str, frames: dict) -> tuple[str, str, str | None] | None:
    """Split a how-do-you-say request using known language/register labels."""
    value = body.strip()
    # Prefer a suffix that is already a stored target language. This makes
    # unquoted source text containing the word "in" unambiguous.
    targets = sorted({(target, style)
                      for source, target, style, _template in frames},
                     key=lambda pair: (-len(pair[0]), -len(pair[1]), pair))
    candidates = []
    for target, style in targets:
        registered_suffix = f" in {target} in {style} register"
        if value.casefold().endswith(registered_suffix.casefold()):
            text = value[:-len(registered_suffix)].strip()
            candidates.append((text, target, style, 1))
        suffix = f" in {target}"
        if value.casefold().endswith(suffix.casefold()):
            text = value[:-len(suffix)].strip()
            candidates.append((text, target, None, 0))
    if candidates:
        text, target, register, _priority = sorted(
            candidates, key=lambda item: (-len(item[1]), -item[3], item[1], item[2] or ""))[0]
    else:
        registered = re.fullmatch(
            r"(.+)\s+in\s+([^.!?]+?)\s+in\s+([^.!?]+?)\s+register",
            value, flags=re.IGNORECASE | re.DOTALL)
        if registered is not None:
            text, target, register = (part.strip() for part in registered.groups())
        else:
            text, separator, target = value.rpartition(" in ")
            if not separator:
                return None
            text, target, register = text.strip(), target.strip(), None
    if (len(text) >= 2 and (text[0], text[-1]) in {
            ('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")}):
        text = text[1:-1].strip()
    if not text or not target:
        return None
    return text, target, register
_MAX_TEMPLATE_CHARS = 512
_MAX_TEXT_CHARS = 4096
_MAX_TEMPLATES = 1000


@dataclass(frozen=True)
class TranslationResult:
    status: str
    output: str | None = None
    request: str | None = None
    language_pair: tuple[str, str] | None = None
    register: str | None = None
    template: str | None = None
    evidence: tuple[dict[str, object], ...] = ()
    matched_registers: tuple[str, ...] = ()
    source_text: str | None = None
    target_language: str | None = None
    matched_source_languages: tuple[str, ...] = ()
    candidate_translations: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class RewriteFrameProposal:
    """A source-separated rewrite frame proposed for explicit review."""

    proposal_id: str
    source_template: str
    target_template: str
    examples: tuple[dict[str, str], ...]


def propose_source_rewrite_frames(
        research_index: Any, *, limit: int = 20,
        max_source_pairs: int = 200) -> tuple[list[RewriteFrameProposal], int]:
    """Find repeated rewrite frames explicitly marked in source prose.

    Only adjacent sentences where the second begins with ``In other words``
    are treated as aligned candidates. A frame is proposed only when the
    existing copied-slot inducer finds the same structure in two independent
    documents and the regular translation-memory validator accepts all pairs.
    This function never stores or accepts a proposal.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("rewrite proposal limit must be between 1 and 100")
    if type(max_source_pairs) is not int or not 2 <= max_source_pairs <= 1000:
        raise ValueError("source-pair bound must be between 2 and 1000")
    explicit_pairs: list[dict[str, str]] = []
    marker = re.compile(
        r"^\s*in\s+other\s+words\s*,\s*(.+?)\s*$", re.IGNORECASE)
    for document in research_index.documents():
        if _is_code_source(document.location):
            continue
        spans = _sentence_spans(document.text)
        sentences = [(start, end, document.text[start:end].strip())
                     for start, end in spans]
        for position in range(1, len(sentences)):
            source_start, source_end, source_text = sentences[position - 1]
            target_start, target_end, marked_target = sentences[position]
            match = marker.fullmatch(marked_target)
            if match is None:
                continue
            target_text = match.group(1).strip()
            if (len(source_text) < 16 or len(target_text) < 16
                    or len(source_text) > 512 or len(target_text) > 512
                    or _sentence_context_kind(
                        source_text, document.text, source_start) == "example"
                    or _sentence_context_kind(
                        marked_target, document.text, target_start) == "example"):
                continue
            source_terms = tokens(source_text)
            target_terms = tokens(target_text)
            if len(source_terms) < 4 or len(target_terms) < 4:
                continue

            def citation(start: int, end: int, text: str) -> str:
                match_start = start if end > start else None
                match_end = end if match_start is not None else None
                page_number = None
                if document.pages and match_start is not None:
                    offset = 0
                    for page, page_text in enumerate(document.pages, start=1):
                        if offset <= match_start < offset + len(page_text):
                            page_number = page
                            break
                        offset += len(page_text) + len("\n\f\n")
                hit = SearchHit(
                    document.document_id, document.title, document.location,
                    0.0, text, start, end,
                    tuple(sorted(set(tokens(text)))), page_number,
                    match_start, match_end)
                return research_index.citation(hit)

            try:
                source_citation = citation(source_start, source_end, source_text)
                target_citation = citation(target_start, target_end, marked_target)
            except (KeyError, TypeError, ValueError):
                continue
            explicit_pairs.append({
                "source": source_text, "target": target_text,
                "source_document_id": document.document_id,
                "target_document_id": document.document_id,
                "source_title": document.title,
                "target_title": document.title,
                "source_citation": source_citation,
                "target_citation": target_citation,
            })
            if len(explicit_pairs) >= max_source_pairs:
                break
        if len(explicit_pairs) >= max_source_pairs:
            break

    grouped: dict[tuple[str, str], dict[tuple[str, str], dict[str, str]]] = {}
    for first_index, first in enumerate(explicit_pairs):
        for second in explicit_pairs[first_index + 1:]:
            if first["source_document_id"] == second["source_document_id"]:
                continue
            examples = [(first["source"], first["target"]),
                        (second["source"], second["target"])]
            try:
                source_template, target_template = infer_shared_slot_templates(
                    examples)
                validator = CRMSTranslation()
                validator.teach_rewrite(
                    "English", "rephrase", source_template,
                    target_template, examples)
            except ValueError:
                continue
            key = (source_template, target_template)
            group = grouped.setdefault(key, {})
            for record in (first, second):
                group[(record["source"], record["target"])] = record

    proposals = []
    for (source_template, target_template), records in grouped.items():
        independent = {record["source_document_id"] for record in records.values()}
        if len(independent) < 2:
            continue
        selected = tuple(records[key] for key in sorted(records)[:8])
        example_pairs = [(record["source"], record["target"])
                         for record in selected]
        try:
            CRMSTranslation().teach_rewrite(
                "English", "rephrase", source_template,
                target_template, example_pairs)
        except ValueError:
            continue
        identity = "\n".join((source_template, target_template,
                              *sorted(independent)))
        proposal_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        proposals.append(RewriteFrameProposal(
            proposal_id, source_template, target_template, selected))
    proposals.sort(key=lambda proposal: (
        -len({example["source_document_id"] for example in proposal.examples}),
        -len(proposal.examples), proposal.proposal_id))
    return proposals[:limit], len(explicit_pairs)


def _label(value: str, field: str) -> str:
    normalized = " ".join(tokens(value))
    if not normalized or len(normalized) > 64:
        raise ValueError(f"{field} must be a nonempty label of at most 64 characters")
    return normalized


def _slots(template: str) -> tuple[str, ...]:
    if not isinstance(template, str) or not template.strip() or len(template) > _MAX_TEMPLATE_CHARS:
        raise ValueError("translation templates must contain 1 to 512 characters")
    stripped = _SLOT_RE.sub("", template)
    if "{" in stripped or "}" in stripped:
        raise ValueError("use named slots such as {person}; braces must be balanced")
    names = tuple(match.group(1) for match in _SLOT_RE.finditer(template))
    if len(set(names)) != len(names):
        # Repeated slots are allowed and checked for equality at match time.
        return names
    return names


def _compile_template(template: str) -> re.Pattern[str]:
    _slots(template)
    pieces: list[str] = []
    cursor = 0
    seen: set[str] = set()
    group_index = 0
    terminal_punctuation = template[-1:] if template[-1:] in ".!?" else ""
    for match in _SLOT_RE.finditer(template):
        literal = template[cursor:match.start()]
        pieces.append(_literal_pattern(literal))
        name = match.group(1)
        if name in seen:
            pieces.append(f"(?P={name})")
        else:
            pieces.append(f"(?P<{name}>.+?)")
            seen.add(name)
            group_index += 1
        cursor = match.end()
        if terminal_punctuation and match.end() == len(template) - 1:
            # Do not let the final slot absorb a different punctuation mark
            # when the expected mark is omitted.
            pieces.append(r"(?<![.!?])")
    literal_suffix = (template[cursor:-1] if terminal_punctuation
                      else template[cursor:])
    pieces.append(_literal_pattern(literal_suffix))
    if terminal_punctuation:
        # Final sentence punctuation may be omitted in ordinary input, but a
        # different mark is not silently treated as equivalent.
        pieces.append(re.escape(terminal_punctuation) + "?")
    # Names in the schema are safe Python group names. A slot must capture at
    # least one non-whitespace character; final punctuation remains template
    # evidence when supplied.
    trailing = r"\s*$" if terminal_punctuation else r"\s*[.!?]*\s*$"
    try:
        return re.compile(r"^\s*" + "".join(pieces) + trailing,
                          re.IGNORECASE | re.UNICODE)
    except re.error as error:
        raise ValueError("translation template is not a valid aligned pattern") from error


def _literal_pattern(value: str) -> str:
    return "".join(r"\s+" if part.isspace() else re.escape(part)
                   for part in re.split(r"(\s+)", value) if part)


def _match(template: str, text: str) -> dict[str, str] | None:
    if not isinstance(text, str) or len(text) > _MAX_TEXT_CHARS:
        return None
    match = _compile_template(template).fullmatch(text)
    if match is None:
        return None
    return {name: value.strip() for name, value in match.groupdict().items()}


def infer_shared_slot_templates(
        examples: Iterable[tuple[str, str]]) -> tuple[str, str]:
    """Infer copied slots from parallel pairs, rejecting weak alignments.

    Token-level common regions in the first two pairs anchor the alignment.
    Every differing region must be nonempty and identical across the source
    and target sides. All later pairs must fit that same alignment.
    """
    rows = list(examples)
    if len(rows) < 2 or len(rows) > 8:
        raise ValueError("provide 2 to 8 aligned sentence pairs")
    if (not all(isinstance(row, (tuple, list)) and len(row) == 2
                and all(isinstance(text, str) and text.strip() for text in row)
                for row in rows)):
        raise ValueError("each example must be a nonempty source/target sentence pair")

    def differing_template(first: str, second: str
                           ) -> tuple[str, list[str], list[str]]:
        pattern = re.compile(r"\s+|[^\W\s]+|[^\w\s]", re.UNICODE)
        first_tokens, second_tokens = pattern.findall(first), pattern.findall(second)
        matcher = SequenceMatcher(None, first_tokens, second_tokens,
                                   autojunk=False)
        pieces: list[str] = []
        first_slots: list[str] = []
        second_slots: list[str] = []
        for tag, first_start, first_end, second_start, second_end in matcher.get_opcodes():
            if tag == "equal":
                pieces.extend(first_tokens[first_start:first_end])
                continue
            first_slot = "".join(first_tokens[first_start:first_end])
            second_slot = "".join(second_tokens[second_start:second_end])
            if not first_slot.strip() or not second_slot.strip():
                raise ValueError(
                    "examples insert or delete text without an aligned copied slot")
            slot_index = len(first_slots) + 1
            pieces.append(f"{{value{slot_index}}}")
            first_slots.append(first_slot)
            second_slots.append(second_slot)
        if not first_slots or len(first_slots) > 8:
            raise ValueError("examples do not show 1 to 8 varying copied slots")
        return "".join(pieces), first_slots, second_slots

    source_template, source_first, source_second = differing_template(
        rows[0][0], rows[1][0])
    target_template, target_first, target_second = differing_template(
        rows[0][1], rows[1][1])
    if (len(source_first) != len(target_first)
            or any(source_first[index].casefold() != target_first[index].casefold()
                   or source_second[index].casefold() != target_second[index].casefold()
                   for index in range(len(source_first)))):
        raise ValueError(
            "the differing source and target spans are not identically aligned; "
            "provide explicit templates")
    source_first_bindings = _match(source_template, rows[0][0])
    source_second_bindings = _match(source_template, rows[1][0])
    target_first_bindings = _match(target_template, rows[0][1])
    target_second_bindings = _match(target_template, rows[1][1])
    if (any(value is None for value in (source_first_bindings,
                                        source_second_bindings,
                                        target_first_bindings,
                                        target_second_bindings))):
        raise ValueError("the inferred slots do not fit their examples")
    for name in source_first_bindings:
        if (source_first_bindings[name].casefold()
                != target_first_bindings[name].casefold()
                or source_second_bindings[name].casefold()
                != target_second_bindings[name].casefold()):
            raise ValueError("a source slot is not preserved on the target side")
    for source_text, target_text in rows[2:]:
        source_binding = _match(source_template, source_text)
        target_binding = _match(target_template, target_text)
        if (source_binding is None or target_binding is None
                or set(source_binding) != set(target_binding)
                or any(source_binding[name].casefold()
                       != target_binding[name].casefold()
                       for name in source_binding)):
            raise ValueError(
                "an example does not preserve all inferred slots; "
                "provide explicit templates")
    return source_template, target_template


class CRMSTranslation:
    """Learn sentence transformations licensed by aligned examples."""

    VERSION = 1

    def __init__(self) -> None:
        self._frames: dict[tuple[str, str, str, str], dict[str, object]] = {}

    def teach(self, source_language: str, target_language: str, register: str,
              source_template: str, target_template: str,
              examples: Iterable[tuple[str, str]]) -> TranslationResult:
        return self._teach(source_language, target_language, register,
                           source_template, target_template, examples,
                           allow_same_language=False)

    def teach_rewrite(self, language: str, register: str,
                      source_template: str, target_template: str,
                      examples: Iterable[tuple[str, str]]) -> TranslationResult:
        """License a same-language style transformation from aligned pairs."""
        return self._teach(language, language, register, source_template,
                           target_template, examples,
                           allow_same_language=True)

    def _teach(self, source_language: str, target_language: str, register: str,
               source_template: str, target_template: str,
               examples: Iterable[tuple[str, str]], *,
               allow_same_language: bool) -> TranslationResult:
        source_language = _label(source_language, "source language")
        target_language = _label(target_language, "target language")
        register = _label(register, "register")
        if source_language == target_language and not allow_same_language:
            raise ValueError("source and target languages must differ")
        source_slots = _slots(source_template)
        target_slots = _slots(target_template)
        if not source_slots or set(source_slots) != set(target_slots):
            raise ValueError("source and target templates need the same named slots")
        _compile_template(source_template)
        _compile_template(target_template)
        example_rows = list(examples)
        if not example_rows:
            raise ValueError("provide at least one aligned sentence pair")
        bindings_seen: set[tuple[tuple[str, str], ...]] = set()
        source_seen: set[str] = set()
        verified: list[dict[str, str]] = []
        for row in example_rows:
            if (not isinstance(row, (tuple, list)) or len(row) != 2
                    or not all(isinstance(text, str) and text.strip() for text in row)):
                raise ValueError("each translation example must be a source/target sentence pair")
            source_text, target_text = row
            source_bindings = _match(source_template, source_text)
            target_bindings = _match(target_template, target_text)
            if source_bindings is None or target_bindings is None:
                raise ValueError("an example does not fit its declared sentence template")
            if set(source_bindings) != set(target_bindings):
                raise ValueError("aligned examples do not expose matching named slots")
            key = tuple(sorted((name, value.casefold())
                               for name, value in source_bindings.items()))
            if key in bindings_seen or source_text.casefold() in source_seen:
                raise ValueError("examples must use distinct slot bindings and source sentences")
            bindings_seen.add(key)
            source_seen.add(source_text.casefold())
            verified.append({"source": source_text, "target": target_text})

        identity = (source_language, target_language, register,
                    " ".join(tokens(source_template)))
        prior = self._frames.get(identity)
        if prior is None and len(example_rows) < 2:
            raise ValueError("at least two aligned sentence pairs are required to license a new frame")
        record = {"source_template": source_template,
                  "target_template": target_template,
                  "examples": [] if prior is None else list(prior["examples"])}
        if prior is not None and prior["target_template"] != target_template:
            raise ValueError("this source frame already has a conflicting target frame")
        existing = {(item["source"].casefold(), item["target"].casefold())
                    for item in record["examples"]}
        if any((item["source"].casefold(), item["target"].casefold()) in existing
               for item in verified):
            raise ValueError("these aligned examples are already stored")
        record["examples"].extend(verified)
        mappings: dict[str, dict[str, str]] = {name: {} for name in source_slots}
        copy_slots = set(source_slots)
        for item in record["examples"]:
            source_bindings = _match(source_template, str(item["source"]))
            target_bindings = _match(target_template, str(item["target"]))
            if source_bindings is None or target_bindings is None:
                raise ValueError("stored examples no longer fit the aligned templates")
            for name in source_slots:
                source_value = source_bindings[name]
                target_value = target_bindings[name]
                key = source_value.casefold()
                prior_target = mappings[name].get(key)
                if (prior_target is not None
                        and prior_target.casefold() != target_value.casefold()):
                    raise ValueError(
                        f"source slot {{{name}}} has conflicting target translations")
                mappings[name].setdefault(key, target_value)
                if source_value.casefold() != target_value.casefold():
                    copy_slots.discard(name)
        record["slot_mappings"] = mappings
        record["copy_slots"] = sorted(copy_slots)
        if len(self._frames) >= _MAX_TEMPLATES and identity not in self._frames:
            raise ValueError("translation memory reached its template bound")
        self._frames[identity] = record
        return TranslationResult(
            "licensed", language_pair=(source_language, target_language),
            register=register, template=source_template,
            evidence=tuple(verified))

    def teach_additional_example(
            self, source_language: str, target_language: str, register: str,
            source_text: str, target_text: str) -> TranslationResult:
        """Extend one uniquely matching licensed frame with a new aligned pair."""
        source = _label(source_language, "source language")
        target = _label(target_language, "target language")
        style = _label(register, "register")
        if (not isinstance(source_text, str) or not source_text.strip()
                or not isinstance(target_text, str) or not target_text.strip()):
            raise ValueError("provide a nonempty aligned source and target sentence")
        matches = []
        for (frame_source, frame_target, frame_style, _), record in self._frames.items():
            if (frame_source, frame_target, frame_style) != (source, target, style):
                continue
            if _match(str(record["source_template"]), source_text) is not None:
                matches.append(record)
        if len(matches) != 1:
            if not matches:
                raise ValueError("no licensed frame in this language pair and register matches the source sentence")
            raise ValueError("more than one licensed frame matches; provide the exact frame templates")
        record = matches[0]
        if source == target:
            return self.teach_rewrite(
                source, style, str(record["source_template"]),
                str(record["target_template"]), [(source_text, target_text)])
        return self.teach(source, target, style,
                          str(record["source_template"]),
                          str(record["target_template"]),
                          [(source_text, target_text)])

    def rewrite(self, text: str, *, register: str = "plain"
                ) -> TranslationResult | None:
        """Apply one unambiguous, licensed same-language rewrite frame."""
        if not isinstance(text, str) or not text.strip():
            return None
        try:
            style = _label(register, "register")
        except ValueError:
            return None
        languages = sorted({source for (source, target, frame_style, _), record
                            in self._frames.items()
                            if source == target and frame_style == style
                            and _match(str(record["source_template"]), text) is not None})
        results = [self.translate(
            f"Translate from {language} to {language} in {style} register: {text}")
            for language in languages]
        translated = [result for result in results
                      if result is not None and result.status == "translated"]
        outputs = {result.output for result in translated}
        if len(outputs) == 1:
            return translated[0]
        if len(outputs) > 1:
            return TranslationResult(
                "ambiguous", register=style, source_text=text,
                request=("More than one learned plain-language frame matches "
                         "this sentence."),
                candidate_translations=tuple({
                    "register": style, "output": result.output,
                    "template": result.template,
                } for result in translated))
        return results[0] if results else None

    def _matching_candidates(
            self, source_language: str, target_language: str,
            register: str | None, text: str
            ) -> tuple[list[tuple[str, dict[str, object], dict[str, str], str]],
                       set[str]]:
        candidates: list[tuple[str, dict[str, object], dict[str, str], str]] = []
        unresolved_slots: set[str] = set()
        for (source, target, style, _), record in self._frames.items():
            if ((source, target) != (source_language, target_language)
                    or (register is not None and style != register)):
                continue
            bindings = _match(str(record["source_template"]), text)
            if bindings is None:
                continue
            slot_mappings = record.get("slot_mappings", {})
            copy_slots = set(record.get("copy_slots", []))
            target_bindings: dict[str, str] = {}
            for name, value in bindings.items():
                if name in copy_slots:
                    target_bindings[name] = value
                else:
                    mapped = slot_mappings.get(name, {}).get(value.casefold())
                    if mapped is None:
                        unresolved_slots.add(name)
                        break
                    target_bindings[name] = mapped
            else:
                candidates.append((str(record["target_template"]), record,
                                   target_bindings, style))
        return candidates, unresolved_slots

    def translate(self, request: str) -> TranslationResult | None:
        if not isinstance(request, str):
            return None
        how_say = _HOW_SAY_REQUEST_RE.fullmatch(request)
        if how_say is not None:
            parts = _how_say_parts(how_say.group("body"), self._frames)
            if parts is None:
                return TranslationResult(
                    "unknown", request="Specify a source sentence and target language.")
            source_text, target_language, register = parts
            # Reuse the target-only translation path so source-language
            # selection, ambiguity handling, and evidence checks stay shared.
            request = (f"Translate ‘{source_text}’ into "
                       f"{target_language}"
                       + (f" in {register} register" if register else "") + ".")
        match = _REQUEST_RE.fullmatch(request)
        if match is None:
            inline = _INLINE_REQUEST_RE.fullmatch(request)
            if inline is not None:
                source_text, source_label, target_label, register_label = inline.groups()
                source_text = source_text.strip()
                if (len(source_text) >= 2
                        and (source_text[0], source_text[-1]) in {
                            ('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")}):
                    source_text = source_text[1:-1].strip()
                fields = (source_label, target_label, register_label, source_text)
            else:
                target_only = _TARGET_ONLY_REQUEST_RE.fullmatch(request)
                if target_only is None:
                    return None
                quote_texts = target_only.groups()[:4]
                source_text = next(text for text in quote_texts if text is not None)
                target_label, register_label = target_only.groups()[4:]
                try:
                    target_language = _label(target_label, "target language")
                    register = (_label(register_label, "register")
                                if register_label else None)
                except ValueError:
                    return TranslationResult(
                        "unknown", request="Specify the target language and register.")
                possible_sources = {
                    source for (source, target, style, _), record in self._frames.items()
                    if target == target_language
                    and (register is None or style == register)
                    and _match(str(record["source_template"]), source_text) is not None
                }
                if not possible_sources:
                    return TranslationResult(
                        "unknown", register=register, target_language=target_language,
                        request=("No learned source frame matches this sentence "
                                 "for the target language."))
                translatable: dict[
                    str, list[tuple[str, dict[str, object], dict[str, str], str]]
                ] = {}
                unresolved_by_language: set[str] = set()
                for source in sorted(possible_sources):
                    source_candidates, unresolved = self._matching_candidates(
                        source, target_language, register, source_text)
                    unresolved_by_language.update(unresolved)
                    if source_candidates and not unresolved:
                        translatable[source] = source_candidates
                if not translatable:
                    if unresolved_by_language:
                        names = ", ".join(
                            f"{{{name}}}" for name in sorted(unresolved_by_language))
                        request_text = (
                            "Matching frames have no aligned target values for "
                            f"these slots: {names}. Teach parallel examples for them.")
                    else:
                        request_text = (
                            "No verified translation frame can translate this "
                            "sentence for the requested target language.")
                    return TranslationResult(
                        "unknown", register=register,
                        target_language=target_language, source_text=source_text,
                        request=request_text)
                if len(translatable) > 1:
                    languages = tuple(sorted(translatable))
                    candidate_translations = tuple({
                        "source_language": source,
                        "register": style,
                        "output": self._render(template, bindings),
                        "template": template,
                    } for source, source_candidates in translatable.items()
                      for template, _record, bindings, style in source_candidates)
                    return TranslationResult(
                        "ambiguous", register=register,
                        request=("The source language is ambiguous. Choose one: "
                                 + ", ".join(languages) + "."),
                        source_text=source_text, target_language=target_language,
                        matched_source_languages=languages,
                        candidate_translations=candidate_translations)
                fields = (next(iter(translatable)), target_language,
                          register, source_text)
        else:
            fields = (match.group(1), match.group(2), match.group(3),
                      match.group(4).strip())
        try:
            source_language = _label(fields[0], "source language")
            target_language = _label(fields[1], "target language")
            register = (_label(fields[2], "register") if fields[2] else None)
        except ValueError:
            return TranslationResult("unknown", request="Specify source, target, and register labels.")
        text = fields[3]
        candidates, unresolved_slots = self._matching_candidates(
            source_language, target_language, register, text)
        if unresolved_slots:
            names = ", ".join(f"{{{name}}}" for name in sorted(unresolved_slots))
            return TranslationResult(
                "unknown", language_pair=(source_language, target_language),
                register=register,
                request=(f"The sentence matches a learned frame, but these slot "
                         f"values have no aligned target examples: {names}. "
                         "Teach parallel examples for those values."))
        if not candidates:
            return TranslationResult(
                "unknown", language_pair=(source_language, target_language),
                register=register,
                request=("No verified translation frame matches this sentence "
                         "and language pair" +
                         (f" in the {register} register." if register else ".")))
        outputs = {self._render(target_template, bindings)
                   for target_template, _, bindings, _style in candidates}
        matched_registers = tuple(sorted({style for *_, style in candidates}))
        if len(outputs) != 1:
            candidate_translations = tuple({
                "register": style,
                "output": self._render(target_template, bindings),
                "template": target_template,
            } for target_template, _record, bindings, style in candidates)
            return TranslationResult(
                "ambiguous", language_pair=(source_language, target_language),
                register=register,
                request=("More than one verified frame gives different translations; "
                         "specify a register." if register is None else
                         "More than one verified frame gives different translations."),
                matched_registers=matched_registers, source_text=text,
                candidate_translations=candidate_translations)
        output = next(iter(outputs))
        evidence = tuple(example for _, record, _, _style in candidates
                         for example in record["examples"])
        return TranslationResult(
            "translated", output=output,
            language_pair=(source_language, target_language),
            register=(register or (matched_registers[0]
                                   if len(matched_registers) == 1 else None)),
            template=" | ".join(sorted({template for template, _, _, _style in candidates})),
            evidence=evidence, matched_registers=matched_registers)

    @staticmethod
    def _render(template: str, bindings: dict[str, str]) -> str:
        return _SLOT_RE.sub(lambda match: bindings[match.group(1)], template)

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": self.VERSION, "frames": [
            {"source_language": source, "target_language": target,
             "register": register,
             "source_template": str(record["source_template"]),
             "target_template": str(record["target_template"]),
             "examples": record["examples"]}
            for (source, target, register, _), record in sorted(self._frames.items())]}
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        temporary.replace(destination)

    @classmethod
    def load(cls, path: str | Path) -> "CRMSTranslation":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != cls.VERSION:
            raise ValueError("unsupported translation-memory format")
        frames = payload.get("frames")
        if not isinstance(frames, list) or len(frames) > _MAX_TEMPLATES:
            raise ValueError("translation frames must be a bounded list")
        model = cls()
        for frame in frames:
            if not isinstance(frame, dict):
                raise ValueError("translation frame record is malformed")
            try:
                stored_examples = frame["examples"]
                if not isinstance(stored_examples, list):
                    raise ValueError("translation frame examples must be a list")
                examples = []
                for row in stored_examples:
                    if (not isinstance(row, dict)
                            or not isinstance(row.get("source"), str)
                            or not isinstance(row.get("target"), str)):
                        raise ValueError("translation frame example is malformed")
                    examples.append((row["source"], row["target"]))
                if frame["source_language"] == frame["target_language"]:
                    result = model.teach_rewrite(
                        frame["source_language"], frame["register"],
                        frame["source_template"], frame["target_template"],
                        examples)
                else:
                    result = model.teach(
                        frame["source_language"], frame["target_language"],
                        frame["register"], frame["source_template"],
                        frame["target_template"], examples)
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("translation frame failed evidence validation") from error
            if result.status != "licensed":
                raise ValueError("translation frame failed licensing")
        return model


def render(result: TranslationResult) -> str:
    if result.status != "translated" or result.output is None:
        response = result.request or "CRMS has no verified translation for that request."
        if result.candidate_translations:
            alternatives = []
            seen = set()
            for candidate in result.candidate_translations:
                label = (candidate.get("source_language")
                         or candidate.get("register"))
                key = (label, candidate.get("output"))
                if key in seen:
                    continue
                seen.add(key)
                alternatives.append(
                    f"{label}: {candidate.get('output')}")
            if alternatives:
                response += " Candidates: " + "; ".join(alternatives)
        return response
    pair = " to ".join(result.language_pair or ())
    evidence = "; ".join(
        f"{row['source']} ↔ {row['target']}" for row in result.evidence)
    register_info = (", ".join(result.matched_registers)
                     if result.matched_registers else
                     result.register or "unspecified")
    return (f"{result.output} (matched learned {pair}, {register_info} register; "
            f"matched: {result.template}; aligned examples: {evidence})")
