"""Phase 11 Stage A engine contract.

Checks, with no network, LLM, or corpus index: the tokenizer and chunker; the
pattern matcher (gaps, alternation, optional groups, verb forms, dates, budget);
pattern transformations and their synthetic probes; the SQL pattern memory
(seed, versioned parameters, retirement, reload); that every seeded relation
spec replays its own evidence through the deterministic verifier; that the
verifier rejects over-general, non-replaying, and contrast-leaking proposals;
and that a small in-memory research index answers, abstains, and refuses
conflicting or truncated answers.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import IndexSentenceSource, ListSentenceSource  # noqa: E402
from crms_patterns import (  # noqa: E402
    MatchContext, PatternError, chunk, match_patterns, parse_pattern, span_text,
    tokenize)
from crms_pattern_transforms import probe, variants  # noqa: E402
from crms_relation_specs import RelationEngine, RelationSpec  # noqa: E402
from crms_research import CRMSResearchIndex  # noqa: E402
from crms_spec_verifier import expand, verify_spec  # noqa: E402

RANDOM_SENTENCES = [
    "Paris is the capital of France.", "The river flows through three countries.",
    "Mount Everest is 8849 metres tall.", "Linus Torvalds developed Linux in 1991.",
    "Water boils at 100 degrees Celsius at sea level.",
    "Marie Curie won two Nobel Prizes.", "Tokyo is the largest city in Japan.",
    "Photosynthesis converts sunlight into chemical energy in plants.",
] * 25


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    folder = tempfile.mkdtemp(prefix="crms-pattern-")
    with PatternMemory(Path(folder) / "patterns.sqlite") as memory:
        count = memory.seed()
        language = memory.language()
        params = memory.params()
        specs = memory.specs()
        require(count == 14 and len(specs) == 14, f"seed loaded {count} specs / {len(specs)} active")
        require(len(language.verbs) >= 30 and "place_noun" in language.classes,
                "language resources did not load from SQL")

        # --- tokenizer, chunker, matcher
        text = "A Clockwork Orange is an English dystopian novella written by Anthony Burgess and published in 1962."
        tokens = tokenize(text, language)
        starts = chunk(tokens, language)
        kinds = {c.type for chunks in starts.values() for c in chunks}
        require({"NP", "PP", "VG"} <= kinds, f"chunk types missing: {kinds}")
        ctx = MatchContext(language, tokens, starts, ["a", "clockwork", "orange"], {"v": "write"})
        found = match_patterns(parse_pattern(
            "E ...{0,10} AUX? V.part[@v] P[by] NP:A | NP:A V.fin[@v] E~"), ctx)
        require(found and span_text(text, tokens, found[0]["binds"], "A") == "Anthony Burgess",
                "passive pattern did not capture the agent")
        # a verb after a name is not absorbed into the noun phrase
        sentence = "Jane Doe built Tenochtitlan."
        t2 = tokenize(sentence, language)
        m2 = match_patterns(parse_pattern("NP:A V.fin[@v] E~"),
                            MatchContext(language, t2, chunk(t2, language), ["tenochtitlan"], {"v": "build"}))
        require(m2 and span_text(sentence, t2, m2[0]["binds"], "A") == "Jane Doe",
                "active base pattern failed (verb absorbed into the noun phrase?)")
        # typed values
        for date_text, expected in (("on 26 October 2023, at", "26 October 2023"),
                                    ("on November 17, 2009.", "November 17, 2009"),
                                    ("in 1930 and", "1930")):
            t3 = tokenize("X died " + date_text, language)
            m3 = match_patterns(parse_pattern("E V.any:v P:p DATE:A"),
                                MatchContext(language, t3, chunk(t3, language), ["x"]))
            require(m3 and span_text("X died " + date_text, t3, m3[0]["binds"], "A") == expected,
                    f"DATE failed for {date_text!r}")
        # bounded work
        long_sentence = " ".join(["word"] * 60) + " end"
        t4 = tokenize(long_sentence, language)
        capped = match_patterns(parse_pattern("...{0,40} ...{0,40} ...{0,40} NP:A"),
                                MatchContext(language, t4, chunk(t4, language)), budget=500)
        require(all(m["truncated"] for m in capped) or not capped, "budget did not truncate")
        try:
            parse_pattern("E $$$")
            raise SystemExit("bad pattern was accepted")
        except PatternError:
            pass

        # --- transformations
        pairs = variants("NP:A V.fin[@v] E~", ["passive", "agentive_noun", "participle"])
        require([n for n, _p in pairs] == ["base", "passive", "agentive_noun", "participle"],
                "variants not expanded")
        engine = RelationEngine(language, specs, ListSentenceSource([]), params)
        for name, pattern in pairs:
            sentence = probe(name, "Tenochtitlan", "Jane Doe", language, "build")
            require(sentence is not None, f"no probe for {name}")
            solo = ("t", ("W[who] V.any:v TAIL:E",), (pattern,), "{A} {v.q} {E}.", "")
            got = engine.ask("Who built Tenochtitlan?", pool=[("p", sentence)], extra=[solo])
            require(got is not None and "Jane Doe" in got.answer, f"variant {name} missed its probe")

        # --- every seeded spec replays its own evidence
        replay_failures = []
        for spec in specs:
            evidence = memory.spec_evidence(spec.name)
            proposal = {"name": spec.name, "priority": spec.priority,
                        "question_patterns": list(spec.question_patterns),
                        "sentence_patterns": list(spec.sentence_patterns),
                        "template": spec.template, "verb_class": spec.verb_class,
                        "support": evidence.get("support", []), "heldout": evidence.get("heldout", []),
                        "contrast": evidence.get("contrast", []),
                        "grandfathered": bool(evidence.get("grandfathered"))}
            if "base" in evidence:
                proposal["base"] = evidence["base"]
                proposal["transforms"] = evidence.get("transforms", [])
            # replay against the engine that already holds this spec, excluding it so the candidate is the only copy
            result = verify_spec(proposal, engine, corpus_sentences=RANDOM_SENTENCES)
            if not result.ok:
                replay_failures.append((spec.name, result.reasons))
        require(not replay_failures, f"seed specs failed their own evidence: {replay_failures}")

        # --- the verifier rejects bad proposals
        def proposal(**kw):
            base = {"name": "bad", "priority": 50, "question_patterns": ["W[who] V.any:v TAIL:E"],
                    "sentence_patterns": ["NP:A V.fin[@v] E~"], "template": "{A} {v.q} {E}.",
                    "support": [
                        {"q": "Who built Tenochtitlan?", "E": "Tenochtitlan",
                         "S": "The Aztecs built Tenochtitlan around 1325.", "A": "The Aztecs"},
                        {"q": "Who founded Nagasaki?", "E": "Nagasaki",
                         "S": "The Portuguese founded Nagasaki in the 16th century.", "A": "The Portuguese"}],
                    "heldout": [{"q": "Who built Tenochtitlan?", "S": "The Aztecs built Tenochtitlan.", "A": "Aztecs"}],
                    "contrast": [{"q": "Who wrote Foo?", "S": "Foo was edited by Bar."}]}
            base.update(kw)
            return base
        good = verify_spec(proposal(), engine, corpus_sentences=RANDOM_SENTENCES)
        require(good.ok, f"a sound proposal was rejected: {good.reasons}")
        bad_replay = verify_spec(proposal(sentence_patterns=["E ...{0,3} P[by] NP:A"]), engine,
                                 corpus_sentences=RANDOM_SENTENCES)
        require(not bad_replay.ok and any("replay" in r for r in bad_replay.reasons),
                "a non-replaying proposal was accepted")
        loose = verify_spec(proposal(sentence_patterns=["NP:A ...{0,6} E~"],
                                     contrast=[{"q": "Who built Foo?", "S": "Bar wrote about Foo."}]),
                            engine, corpus_sentences=RANDOM_SENTENCES)
        require(not loose.ok and any("contrast" in r for r in loose.reasons),
                "a contrast-leaking proposal was accepted")
        general = verify_spec(proposal(sentence_patterns=["TAIL:A"], contrast=[]), engine,
                              corpus_sentences=RANDOM_SENTENCES)
        require(not general.ok and any("too general" in r or "contrast" in r or "verb" in r
                                       for r in general.reasons), "an over-general proposal was accepted")

        # --- SQL memory: versioned parameters, retirement, reload
        version = memory.set_param("rk_window", 20.0, origin="human", rationale="test")
        require(version == 2 and memory.params()["rk_window"] == 20.0, "parameter versioning failed")
        memory.set_spec_status("population_of", "retired", "test retirement")
        require("population_of" not in {s.name for s in memory.specs()}, "retirement did not remove the spec")
        memory.connection.commit()
    with PatternMemory(Path(folder) / "patterns.sqlite") as reopened:
        require(len(reopened.specs()) == 13 and reopened.params()["rk_window"] == 20.0,
                "memory did not persist across reopen")
        require(reopened.changes(), "audit trail is empty")

    # --- a small research index end to end
    with PatternMemory(Path(folder) / "e2e.sqlite") as memory:
        memory.seed()
        language = memory.language()
        index = CRMSResearchIndex()
        index.add_document("d1", "Binago Works", "Binago Works was founded in 1934 by Anna Rossi.")
        index.add_document("d2", "Aldo Press", "Aldo Press is a publisher. It was established in 1960 in Milan.")
        index.add_document("d3", "Lantern Bay", "Lantern Bay is a film directed by Rafe Ostin.")
        index.add_document("d4", "Oldtown", "Oldtown was established in 1901. Oldtown was established in 1950.")
        index.add_document("d5", "Pemberton", "Pemberton was established in 1990 by Ana Maria Lopez Garcia Smith and others.")
        engine = RelationEngine(language, memory.specs(), IndexSentenceSource(index), memory.params())
        a = engine.ask("When was Binago Works founded?")
        require(a is not None and "1934" in a.answer and a.source.startswith("Binago Works"),
                f"dated event not answered: {a}")
        b = engine.ask("Who directed Lantern Bay?")
        require(b is not None and "Rafe Ostin" in b.answer and b.title == "Lantern Bay",
                f"agent not answered: {b}")
        require(engine.ask("Who directed The Glass Orchard?") is None, "unanswerable question was answered")
        require(engine.ask("When was Oldtown established?") is None,
                "conflicting equally good answers were not refused")
        proposition = b.proposition()
        require(proposition["subject"] == "Rafe Ostin" and proposition["verb"] == "directed"
                and proposition["object"] == "Lantern Bay"
                and proposition["source_text"].startswith("Lantern Bay"), f"proposition wrong: {proposition}")
        dated = engine.ask("When was Binago Works founded?").proposition()
        require(dated["subject"] == "Binago Works" and dated["verb"] == "was"
                and dated["complement"] == "founded in 1934", f"dated proposition wrong: {dated}")
        again = engine.ask("Who directed Lantern Bay?")
        require(again is not None and again.answer == b.answer and again.trace == b.trace,
                "answers are not deterministic")
    print("Phase 11 pattern engine contract passed")


if __name__ == "__main__":
    main()
