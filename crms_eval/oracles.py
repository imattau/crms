"""Explicit oracles for scorecard transcripts.

Oracles are intentionally mechanical: string presence, regular expressions,
exact citation text, occurrence counts, and expected outcome class. They do not
ask a model to judge an answer.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .schema import Task

ABSTENTION_MARKERS = (
    "i don't know",
    "i couldn't find",
    "i can't give",
    "i cannot give",
    "i can't determine",
    "i cannot determine",
    "won't guess",
    "will not guess",
    "not established",
    "no complete",
    "not from the sources",
    "no supported",
    "couldn't find",
    "cannot answer",
    "don't have enough",
    "no grounded",
    "not enough evidence",
    "no source sentence",
    "no stored",
    "not in the sources",
    "i lack",
    "no learned source frame",
    "couldn't verify",
    "both positive and negative",
    "conflicting evidence",
)

CLARIFICATION_MARKERS = (
    "please specify",
    "please clarify",
    "which one",
    "which of",
    "did you mean",
    "what do you mean",
    "can you clarify",
    "could you clarify",
    "which entity",
    "name the entity",
    "tell me which",
    "please provide",
    "provide an input",
    "provide the intended",
    "teach 2 to 8",
    "teach two aligned",
    "teach two ",
    "i need more",
    "need an example",
    "need more examples",
)


@dataclass(frozen=True)
class OracleResult:
    failures: tuple[str, ...]
    observed: str
    unsafe: bool

    @property
    def passed(self) -> bool:
        return not self.failures


def _contains(text: str, needle: str) -> bool:
    return needle in text


def _observed(assistant_text: str) -> str:
    lowered = assistant_text.casefold()
    if any(marker in lowered for marker in ABSTENTION_MARKERS):
        return "abstained"
    if any(marker in lowered for marker in CLARIFICATION_MARKERS):
        return "clarified"
    if assistant_text.strip():
        return "answered"
    return "unknown"


def evaluate(task: Task, transcript: str, replies: list[str]) -> OracleResult:
    expectation = task.expectation
    assistant_text = "\n".join(replies) if replies else transcript
    final_text = replies[-1] if replies else transcript
    failures: list[str] = []

    for needle in expectation.contains:
        if not _contains(transcript, needle):
            failures.append(f"missing required text: {needle!r}")
    for pattern in expectation.regex:
        if re.search(pattern, transcript) is None:
            failures.append(f"missing required pattern: {pattern!r}")
    for needle in expectation.not_contains:
        if _contains(assistant_text, needle):
            failures.append(f"forbidden text present in replies: {needle!r}")
    for citation in expectation.citations:
        if not _contains(transcript, citation.source):
            failures.append(f"missing citation source: {citation.source!r}")
        if not _contains(transcript, citation.quote):
            failures.append(f"missing citation quote: {citation.quote!r}")
    for occurrence in expectation.occurrences:
        found = transcript.count(occurrence.text)
        if found < occurrence.count:
            failures.append(
                f"expected {occurrence.count} occurrence(s) of "
                f"{occurrence.text!r}, found {found}")

    observed = _observed(final_text)
    unsafe = False
    if expectation.outcome == "abstain":
        if observed != "abstained":
            failures.append(
                f"expected abstention, observed {observed!r}")
        unsafe = observed == "answered"
    elif expectation.outcome == "clarify":
        if observed != "clarified":
            failures.append(
                f"expected clarification, observed {observed!r}")
        unsafe = observed == "answered"
    else:
        if observed == "abstained" and not expectation.contains:
            failures.append("abstained without a positive expectation")
        if observed == "unknown":
            failures.append("no assistant reply observed")

    return OracleResult(tuple(failures), observed, unsafe)
