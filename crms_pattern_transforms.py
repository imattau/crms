"""Rules about patterns (Phase 11).

A relation is written once as a base pattern; named transformations derive its
other surface forms. Every transformation also builds a synthetic probe
sentence, so the spec verifier can test each derived variant mechanically.
"""
from __future__ import annotations

from typing import Callable

from crms_patterns import PatternLanguage

# A probe maker gets (entity, answer, verb forms, agentive noun or None).
_ProbeMaker = Callable[[str, str, dict, "str | None"], "str | None"]

TRANSFORMS: dict[str, dict[str, object]] = {
    "passive": {
        "make": lambda base: "E ...{0,16} AUX? V.part[@v] ...{0,4} P[by] NP:A",
        "probe": lambda e, a, f, ag: f"{e} was {f['part']} by {a}.",
    },
    "agentive_noun": {
        "make": lambda base: "NP:A COP DET ...{0,3} N.agent[@v] P[of] E~",
        "probe": lambda e, a, f, ag: f"{a} is the {ag} of {e}." if ag else None,
    },
    "participle": {
        "make": lambda base: "E ...{0,16} V.ing[@v] (P[in])? NP:A",
        "probe": lambda e, a, f, ag: f"{e} is a film {sorted(f['ing'])[-1]} {a}.",
    },
}


def _base_probe(entity: str, answer: str, forms: dict, _agent: str | None) -> str:
    return f"{answer} {forms['past']} {entity}."


def variants(base: str, names: list[str] | tuple[str, ...]) -> list[tuple[str, str]]:
    """[(name, pattern)]: the base pattern plus each selected transformation."""
    out = [("base", base)]
    for name in names:
        if name not in TRANSFORMS:
            raise ValueError(f"unknown pattern transformation: {name!r}")
        out.append((name, TRANSFORMS[name]["make"](base)))  # type: ignore[operator]
    return out


def probe(name: str, entity: str, answer: str, language: PatternLanguage,
          lemma: str) -> str | None:
    forms = language.forms(lemma)
    nouns = sorted(language.agent_nouns.get(lemma, ()))
    agent = nouns[0] if nouns else None
    maker: _ProbeMaker = _base_probe if name == "base" else TRANSFORMS[name]["probe"]  # type: ignore[assignment]
    return maker(entity, answer, forms, agent)
