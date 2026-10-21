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


def intake_facts(questions: Sequence[Any], documents: Iterable[tuple[str, str]], *,
                 prefix: str = "intake") -> tuple[list[Fact], list[dict[str, Any]]]:
    """Return (facts, report). The report lists every question, answered or not."""
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
        answer = engine.ask(question)
        if answer is None:
            report.append({"question": question, "status": "abstained"})
            continue
        prop = answer.proposition()
        if (answer.value not in answer.source
                or not (prop["subject"] or prop["verb"])):
            report.append({"question": question, "status": "dropped",
                           "reason": "answer span not in its source sentence"})
            continue
        facts.append(Fact(
            fact_id=f"{prefix}-{index + 1}", subject=prop["subject"],
            verb=prop["verb"], object=prop["object"],
            complement=prop["complement"], role=role, source=answer.title,
            span=answer.value, order=index, source_text=answer.source,
            tags=("intake", answer.spec)))
        report.append({"question": question, "status": "answered",
                       "spec": answer.spec, "source": answer.source})
    return facts, report
