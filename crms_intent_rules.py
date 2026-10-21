"""Pattern-rule classification for request and sentence intents (Phase 11, Stage B+).

A family is an ordered list of rules held in the SQL `pat_intent` table. Each
rule has one or more patterns in the Phase 11 pattern language and a result
label; the first rule (by priority) that matches wins. A rule may be anchored to
the start of the text. Nothing here uses regular expressions to decide intent:
`words()` only splits text into word tokens, and the rules decide the rest.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Sequence

from crms_patterns import (MatchContext, chunk, match_patterns,
                           parse_pattern, tokenize)
from crms_pattern_defaults import seeded_resources


def words(text: str) -> list[str]:
    """Word tokens in order (letters, digits and underscore), lower-cased."""
    out: list[str] = []
    cur: list[str] = []
    for ch in text.casefold():
        if ch.isalnum() or ch == "_":
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


class IntentRules:
    def __init__(self, language: Any, rules: Sequence[dict[str, Any]]) -> None:
        self.language = language
        self.rules = [dict(r, parsed=[parse_pattern(p) for p in r["patterns"]])
                      for r in rules]

    def classify(self, text: str, *, lead_ok: bool = True) -> dict[str, Any] | None:
        """First matching rule for `text` (already word-normalised) or None.

        `lead_ok=False` means the original text did not begin with a word, so
        start-anchored rules cannot match.
        """
        tokens = tokenize(text, self.language)
        ctx = MatchContext(self.language, tokens, _no_chunks())
        for rule in self.rules:
            if rule["anchored"] and not lead_ok:
                continue
            starts = [0] if rule["anchored"] else None
            for alternatives in rule["parsed"]:
                found = match_patterns(alternatives, ctx, limit=1,
                                       start_positions=starts)
                if found:
                    return {"name": rule["name"], "result": rule["result"],
                            "trace": found[0]["trace"]}
        return None


def body_of(family: str, text: str) -> str | None:
    """Text of the ``body`` capture of the first rule in `family` that matches
    the whole of `text`, with the rule's trailing marks trimmed.

    A rule result of ``body:<marks>`` trims whitespace and then the marks that
    end the body. Returns None when no rule matches or the body is empty."""
    rules = _family(family)
    language = rules.language
    tokens = tokenize(text, language)
    ctx = MatchContext(language, tokens, {})
    for rule in rules.rules:
        for alternatives in rule["parsed"]:
            for found in match_patterns(alternatives, ctx, limit=30,
                                        start_positions=[0]):
                if found["end"] != len(tokens) or "body" not in found["binds"]:
                    continue
                i, j = found["binds"]["body"]
                if i == 0 or j <= i:
                    continue
                start = tokens[i - 1].end
                if start >= len(text) or not text[start].isspace():
                    continue
                stop = tokens[j].start if j < len(tokens) else len(text)
                if alternatives[found["alt"]][-1][0] != "TAIL":
                    # a closed ending (…equal): only whitespace and one "?" may follow
                    rest = text[tokens[-1].end:].strip()
                    if rest not in ("", "?"):
                        continue
                body = text[start:stop].strip()
                marks = rule["result"].partition(":")[2]
                if marks == "?":
                    body = body.rstrip()
                    body = body[:-1].rstrip() if body.endswith("?") else body
                else:
                    body = body.rstrip(marks + " \t\n") if marks else body
                if body:
                    return body
    return None


def _no_chunks() -> dict:
    return {}


@lru_cache(maxsize=None)
def _family(family: str) -> IntentRules:
    from crms_pattern_memory import PatternMemory
    language = seeded_resources()[0]
    memory = PatternMemory(":memory:")
    memory.seed()
    rules = memory.intents(family)
    memory.close()
    return IntentRules(language, rules)


def classify(family: str, text: str, *, normalise: bool = True) -> str | None:
    """Result label of the first rule in `family` that matches `text`."""
    stripped = text.strip()
    lead_ok = bool(stripped) and (stripped[0].isalnum() or stripped[0] == "_")
    flat = " ".join(words(stripped)) if normalise else stripped
    hit = _family(family).classify(flat, lead_ok=lead_ok)
    return hit["result"] if hit else None
