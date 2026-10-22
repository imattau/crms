"""Candidate features, hand-set ranking, and the truncated-name veto (Phase 11).

Weights and thresholds are SQL parameters (`pat_param`), not constants. A learned
ranker was tried and did not beat these values under leave-one-set-out
validation; it may replace them only if it does.
"""
from __future__ import annotations

import math
import re
from typing import Mapping, Sequence

from crms_patterns import Token

FEATURES = ("gap", "alt", "subj_first", "e_late", "title_eq", "title_has",
            "rank", "a_len", "a_cap", "synth", "sent_len", "e_start",
            "consensus", "a_last_cap", "a_next_cap", "a_cap_ratio")

DEFAULT_PARAMS: dict[str, float] = {
    "rk_gap": -1.0,        # cost per gap token
    "rk_alt": -1.0,        # cost per pattern alternative index
    "rk_e_late": -12.0,    # entity not at the start of the sentence
    "rk_title_eq": 1.0,    # page title equals the entity
    "rk_window": 14.0,     # cost window for preferring the most specific compatible answer
    "conflict_window": 2.0,  # report a disagreement when a different source's incompatible answer is this close in cost
    "veto_next_cap": 1.0,  # abstain when the answer is followed by a capitalised word
    "veto_extended_title": 0.0,  # abstain when the source page's title extends the entity
}


def features(*, gap: int, alt: int, pattern: str, start: int, title: str,
             entity: str, pool_index: int, answer: str, sentence: str,
             synthetic: bool, at_start: bool, consensus: int,
             answer_tokens: Sequence[Token] = (),
             next_token: Token | None = None) -> dict[str, float]:
    entity_first = pattern.startswith("E ")
    caps = sum(1 for t in answer_tokens if t.kind in ("CAP", "NUM"))
    return {
        "gap": float(gap), "alt": float(alt),
        "subj_first": 1.0 if entity_first and start <= 2 else 0.0,
        "e_late": 1.0 if entity_first and start > 2 else 0.0,
        "title_eq": 1.0 if title.lower() == entity.lower() else 0.0,
        "title_has": 1.0 if entity.lower() in title.lower() else 0.0,
        "rank": math.log1p(pool_index),
        "a_len": math.log1p(len(answer.split())),
        "a_cap": 1.0 if re.search(r"\b[A-Z]", answer) else 0.0,
        "synth": 1.0 if synthetic else 0.0,
        "sent_len": math.log1p(len(sentence.split())),
        "e_start": 1.0 if at_start else 0.0,
        "consensus": math.log1p(consensus),
        "a_last_cap": 1.0 if answer_tokens and answer_tokens[-1].kind in ("CAP", "NUM") else 0.0,
        "a_next_cap": 1.0 if next_token is not None and next_token.kind == "CAP" else 0.0,
        "a_cap_ratio": caps / len(answer_tokens) if answer_tokens else 0.0,
    }


def cost(f: Mapping[str, float], params: Mapping[str, float]) -> float:
    """Lower is better. This is the hand-set ranking, read from parameters."""
    p = {**DEFAULT_PARAMS, **params}
    return -(p["rk_gap"] * f["gap"] + p["rk_alt"] * f["alt"]
             + p["rk_e_late"] * f["e_late"] + p["rk_title_eq"] * f["title_eq"])


def compatible(a: str, b: str) -> bool:
    a = re.sub(r"\W+", " ", a.lower()).strip()
    b = re.sub(r"\W+", " ", b.lower()).strip()
    return a in b or b in a
