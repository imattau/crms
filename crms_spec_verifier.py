"""Deterministic gate for proposed relation specs (Phase 11).

A proposal comes from a teacher (or a human) and is accepted only if every check
passes: the patterns parse; support examples replay; held-out examples pass;
contrast sentences do not answer; a binding to the question's verb really binds
it; the spec does not fire on random corpus sentences; every derived variant
recognises its own synthetic probe; and no previously correct answer in the
control bank gets worse. The proposer never accepts its own proposal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import random
import re
from typing import Any, Callable, Mapping, Sequence

from crms_pattern_transforms import probe, variants
from crms_patterns import PatternError, parse_pattern, tokenize
from crms_relation_specs import RelationEngine

# bank(candidate, excluded_names) -> {question: "correct" | "wrong" | "abstain" | "hallucinated"}
BankFn = Callable[[tuple | None, tuple[str, ...]], Mapping[str, str]]


@dataclass
class Verification:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower().replace(",", "")).strip()


def contains(answer: str, gold: str) -> bool:
    return _norm(gold) in _norm(answer)


def expand(proposal: dict[str, Any]) -> dict[str, Any]:
    """Normalise key names and expand a base pattern plus transformations."""
    proposal.setdefault("question_patterns", proposal.get("q", []))
    if "base" in proposal:
        pairs = variants(proposal["base"], proposal.get("transforms", []))
        proposal["sentence_patterns"] = [p for _n, p in pairs]
        proposal["_variants"] = [n for n, _p in pairs]
    else:
        proposal.setdefault("sentence_patterns", proposal.get("s", []))
    proposal.setdefault("template", proposal.get("t", ""))
    return proposal


def candidate_tuple(proposal: Mapping[str, Any]) -> tuple:
    return (proposal["name"], tuple(proposal["question_patterns"]),
            tuple(proposal["sentence_patterns"]), proposal["template"],
            proposal.get("verb_class", ""))


def verify_spec(proposal: dict[str, Any], engine: RelationEngine, *,
                bank: BankFn | None = None,
                corpus_sentences: Sequence[str] = (),
                min_support: int = 2, seed: int = 11) -> Verification:
    rng = random.Random(seed)
    proposal = expand(proposal)
    reasons: list[str] = []
    metrics: dict[str, Any] = {}
    try:
        for pattern in (*proposal["question_patterns"], *proposal["sentence_patterns"]):
            parse_pattern(pattern)
    except PatternError as error:
        return Verification(False, [f"pattern does not parse: {error}"], metrics)
    cand = candidate_tuple(proposal)
    name = proposal["name"]

    def ask(question: str, sentence: str):
        return engine.ask(question, pool=[("x", sentence)], extra=[cand])

    support = proposal.get("support", [])
    miss = []
    for item in support:
        got = ask(item["q"], item["S"])
        if not got or got.spec != name or not contains(got.answer, item["A"]):
            miss.append((item["q"], got.answer if got else None))
    metrics["replay"] = f"{len(support) - len(miss)}/{len(support)}"
    if miss:
        reasons.append(f"replay failed on {len(miss)}: {miss[:2]}")
    if len(support) < min_support and not proposal.get("grandfathered"):
        reasons.append(f"needs at least {min_support} support examples")

    if proposal.get("_variants") and support:
        language = engine.language
        item = support[0]
        tokens = tokenize(item["q"], language)
        lemma = next((next(iter(language.lemmas(t))) for t in tokens if language.lemmas(t)), None)
        entity = re.sub(r"^(?:the|a|an)\s+", "", item.get("E", ""), flags=re.I) or item["q"]
        results: dict[str, str] = {}
        for variant, pattern in zip(proposal["_variants"], proposal["sentence_patterns"]):
            sentence = probe(variant, entity, "Jane Doe", language, lemma) if lemma else None
            if not sentence:
                results[variant] = "skipped (no agentive noun)"
                continue
            solo = (name, cand[1], (pattern,), cand[3], cand[4])
            got = engine.ask(item["q"], pool=[("probe", sentence)], extra=[solo])
            results[variant] = ("ok" if got and got.spec == name
                                and "jane doe" in got.answer.lower()
                                else "FAIL: " + sentence)
        metrics["variant_probes"] = results
        failed = [k for k, v in results.items() if v.startswith("FAIL")]
        if failed:
            reasons.append(f"derived variant(s) {failed} do not recognise their own probe sentence")

    held = proposal.get("heldout", [])
    hm = []
    for item in held:
        got = ask(item["q"], item["S"])
        if not got or got.spec != name or not contains(got.answer, item["A"]):
            hm.append((item["q"], got.answer if got else None))
    metrics["heldout"] = f"{len(held) - len(hm)}/{len(held)}"
    if not held and not proposal.get("grandfathered"):
        reasons.append("no held-out example supplied")
    elif hm:
        reasons.append(f"held-out failed on {len(hm)}: {hm[:2]}")

    contrast = proposal.get("contrast", [])
    bad = [(c["q"], r.answer) for c in contrast
           if (r := ask(c["q"], c["S"])) and r.spec == name]
    metrics["contrast_rejected"] = f"{len(contrast) - len(bad)}/{len(contrast)}"
    if bad:
        reasons.append(f"contrast answered (should not): {bad[:2]}")

    if any("@v" in p for p in proposal["sentence_patterns"]) and support:
        language = engine.language
        verbs = [v for v in language.verbs]
        every = sorted({f for lem in verbs for f in language.forms(lem)["any"]},
                       key=len, reverse=True)
        leaks = total = 0
        for item in support:
            m = re.search(r"\b(" + "|".join(map(re.escape, every)) + r")\b", item["q"], re.I)
            if not m:
                continue
            for lemma in rng.sample(verbs, min(6, len(verbs))):
                swapped = item["q"][:m.start()] + language.forms(lemma)["past"] + item["q"][m.end():]
                if swapped == item["q"]:
                    continue
                total += 1
                got = ask(swapped, item["S"])
                if got and got.spec == name:
                    leaks += 1
        metrics["verb_swap_leaks"] = f"{leaks}/{total}"
        if total and leaks / total > 0.1:
            reasons.append(f"verb binding too loose: {leaks}/{total} swapped-verb questions still answered")

    fired = total = 0
    for item in support[:2]:
        entity = item.get("E")
        if not entity:
            continue
        for sentence in list(corpus_sentences)[:200]:
            subject = " ".join(sentence.split()[:2])
            got = ask(item["q"].replace(entity, subject), sentence)
            total += 1
            if got and got.spec == name:
                fired += 1
    metrics["corpus_fire_rate"] = f"{fired}/{total}"
    if total and fired / total > 0.05:
        reasons.append(f"fires on {fired}/{total} random corpus sentences (too general)")

    if bank is not None:
        before = bank(None, ())
        after = bank(cand, tuple(proposal.get("retire", ())))
        regress = [q for q, st in before.items() if st == "correct" and after.get(q) != "correct"]
        halluc = [q for q, st in after.items() if st == "hallucinated" and before.get(q) != "hallucinated"]
        metrics["bank_gain"] = sum(1 for q, st in after.items()
                                   if st == "correct" and before.get(q) != "correct")
        metrics["bank_regress"] = len(regress)
        if regress:
            reasons.append(f"regresses {len(regress)} previously correct answers: {regress[:3]}")
        if halluc:
            reasons.append(f"answers unanswerable controls: {halluc[:2]}")
    return Verification(not reasons, reasons, metrics)
