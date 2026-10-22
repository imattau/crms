"""Phase 12: conflict reporting, page-subject resolution, and failure-cause grouping."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_failure_causes import classify  # noqa: E402
from crms_generation import _lower_first  # noqa: E402
from crms_pattern_defaults import seeded_resources  # noqa: E402
from crms_pattern_sources import resolve_page_subject  # noqa: E402
from crms_relation_specs import ListSentenceSource, RelationEngine  # noqa: E402
from crms_source_intake import intake_facts  # noqa: E402


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(message)


def engine_for(pool):
    language, specs, params, _ = seeded_resources()
    return RelationEngine(language, specs, ListSentenceSource(pool), params)


def main() -> None:
    # names keep their capital after a transition; function words do not
    require(_lower_first("Oldtown was built.") == "Oldtown was built.", "name was lower-cased")
    require(_lower_first("The town was built.") == "the town was built.", "function word kept capital")

    # page subject: a stripped lead sentence gets its title back, a pronoun does not by default
    require(resolve_page_subject(") is a 2014 film directed by Ann Lee.", "Big Film")
            == "Big Film is a 2014 film directed by Ann Lee.", "bracket case")
    require(resolve_page_subject("It was directed by Ann Lee.", "Big Film") is None, "pronoun mode must be off by default")
    require(resolve_page_subject("It was directed by Ann Lee.", "Big Film", frozenset({"pronoun"}))
            == "Big Film was directed by Ann Lee.", "pronoun mode")
    require(resolve_page_subject("Big Film was directed by Ann Lee.", "Big Film") is None, "title already present")

    # disagreement is reported without changing the engine's answer
    pool = [("a.txt", "Bob Smith founded Acme in 1990."), ("b.txt", "Jane Doe founded Acme in 1991.")]
    engine = engine_for(pool)
    conflicts: list = []
    answer = engine.ask("Who founded Acme?", conflicts=conflicts)
    alone = engine_for(pool).ask("Who founded Acme?")
    require(answer is not None and alone is not None and answer.answer == alone.answer,
            "conflict reporting changed the answer")
    require({c.value for c in conflicts} == {"Bob Smith", "Jane Doe"}, [c.value for c in conflicts])
    agree: list = []
    engine_for([("a.txt", "Bob Smith founded Acme."), ("b.txt", "Acme was founded by Bob Smith.")]).ask(
        "Who founded Acme?", conflicts=agree)
    require(not agree, "agreeing sources reported as a conflict")

    # intake states both sides with their sources; composed text keeps names and cites
    facts, report = intake_facts(["Who founded Acme?"], pool)
    require(report[0]["status"] == "conflict" and len(facts) == 2, report)
    require(facts[0].role == "claim" and facts[1].role == "caveat", [f.role for f in facts])
    require("according to a.txt" in facts[0].complement and "according to b.txt" in facts[1].complement,
            [f.complement for f in facts])   # composed wording is covered by v1_579 (conflict case)

    # failure causes
    item = {"question": "Who founded Acme?", "gold": "Bob Smith"}
    require(classify(engine_for(pool[:1]), item)["cause"] == "correct", "correct")
    require(classify(engine_for(pool[1:]), item)["cause"] == "wrong_entity", "wrong entity")
    require(classify(engine_for([("c", "Acme makes tools.")]), item)["cause"] == "retrieval_miss", "retrieval miss")
    require(classify(engine_for([("c", "Bob Smith is the boss of Acme.")]), item)["cause"] == "no_sentence", "no sentence")
    require(classify(engine_for([("c", "founder = Bob Smith")]), item)["cause"] == "infobox_only", "infobox only")
    require(classify(engine_for([]), {"question": "Tell me things", "gold": "x"})["cause"] == "no_question", "no question")
    print("Phase 12 mechanisms passed")


if __name__ == "__main__":
    main()
