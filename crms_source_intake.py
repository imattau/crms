"""Source-to-proposition intake for generation (Phase 11, Stage A).

Questions are answered from source documents with the relation specs, and each
verified match becomes a `Fact` that the Phase 10 planner can compose. A fact
is kept only when its answer span really occurs in its source sentence.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable, Sequence

from crms_generation import Fact
from crms_pattern_defaults import seeded_resources
from crms_relation_specs import ListSentenceSource, RelationEngine
from crms_patterns import sentence_spans as _sentence_spans


def split_sentences(documents: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for name, text in documents:
        for a, b in _sentence_spans(text):
            for part in text[a:b].split("\n"):
                if part.strip():
                    pairs.append((name, part.strip()))
    return pairs


def _fact_of(answer: Any, fact_id: str, role: str, order: int, tags: tuple,
             *, attribute: bool = False) -> Fact | None:
    prop = answer.proposition()
    if answer.value not in answer.source or not (prop["subject"] or prop["verb"]):
        return None
    complement = prop["complement"]
    if attribute:       # sources disagree: each side names where it comes from
        complement = f"{complement} according to {answer.title}".strip()
    return Fact(
        fact_id=fact_id, subject=prop["subject"], verb=prop["verb"],
        object=prop["object"], complement=complement, role=role,
        source=answer.title, span=answer.value, order=order,
        source_text=answer.source, tags=tags)


def intake_facts(questions: Sequence[Any], documents: Iterable[tuple[str, str]], *,
                 prefix: str = "intake", report_conflicts: bool = True
                 ) -> tuple[list[Fact], list[dict[str, Any]]]:
    """Return (facts, report). The report lists every question, answered or not.

    When sources disagree (`report_conflicts`), every side is kept as a fact with
    its own citation: the best answer in the requested role and the others as
    `caveat` facts tagged `conflict`, so the composed text says the sources
    differ instead of silently choosing. An equal-cost disagreement that the
    engine abstains on is reported the same way."""
    language, specs, params, _rewrites = seeded_resources()
    source = ListSentenceSource(split_sentences(documents))
    engine = RelationEngine(language, specs, source, params)
    facts: list[Fact] = []
    report: list[dict[str, Any]] = []
    for index, item in enumerate(questions):
        # An item is a question string, or {"question": ..., "role": ...} where the
        # role is the rhetorical role the planner needs (main, support, caveat, ...).
        question = str(item["question"] if isinstance(item, dict) else item)
        role = str(item.get("role", "claim")) if isinstance(item, dict) else "claim"
        conflicts: list = []
        answer = engine.ask(question, conflicts=conflicts if report_conflicts else None)
        sides = [c for c in conflicts if c.value]
        if answer is None and len(sides) > 1:
            built = [_fact_of(c, f"{prefix}-{index + 1}" + ("" if k == 0 else chr(97 + k - 1)),
                              role if k == 0 else "caveat", index,
                              ("intake", c.spec, "conflict"), attribute=True)
                     for k, c in enumerate(sides)]
            built = [f for f in built if f is not None]
            if len(built) > 1:
                facts.extend(built)
                report.append({"question": question, "status": "conflict",
                               "sides": [{"value": c.value, "source": c.title}
                                         for c in sides]})
                continue
        if answer is None:
            report.append({"question": question, "status": "abstained"})
            continue
        prop = answer.proposition()
        if (answer.value not in answer.source
                or not (prop["subject"] or prop["verb"])):
            report.append({"question": question, "status": "dropped",
                           "reason": "answer span not in its source sentence"})
            continue
        extra: list[Fact] = []
        if len(sides) > 1:
            for k, c in enumerate(sides[1:]):
                alt = _fact_of(c, f"{prefix}-{index + 1}{chr(97 + k)}", "caveat",
                               index, ("intake", c.spec, "conflict"), attribute=True)
                if alt is not None:
                    extra.append(alt)
        facts.append(Fact(
            fact_id=f"{prefix}-{index + 1}", subject=prop["subject"],
            verb=prop["verb"], object=prop["object"],
            complement=(f"{prop['complement']} according to {answer.title}".strip()
                        if extra else prop["complement"]),
            role=role, source=answer.title,
            span=answer.value, order=index, source_text=answer.source,
            tags=("intake", answer.spec) + (("conflict",) if extra else ())))
        facts.extend(extra)
        row = {"question": question, "status": "answered",
               "spec": answer.spec, "source": answer.source}
        if extra:
            row["status"] = "conflict"
            row["sides"] = [{"value": c.value, "source": c.title} for c in sides]
        report.append(row)
    return facts, report
