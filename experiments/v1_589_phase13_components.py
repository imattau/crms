"""Phase 13: rarity weights, the rarity-driven gate dimension, grader v2, spec induction, span reader."""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import crms_nl_gate as gate  # noqa: E402
from crms_independent_eval import oracle_label  # noqa: E402
from crms_pattern_defaults import seeded_resources  # noqa: E402
from crms_relation_specs import ListSentenceSource, RelationEngine  # noqa: E402
from crms_span_reader import analyse_question, candidates, read  # noqa: E402
from crms_patterns import tokenize  # noqa: E402
from crms_spec_induction import induce, propose  # noqa: E402
from crms_word_rarity import weight  # noqa: E402


def require(ok: bool, message: object) -> None:
    if not ok:
        raise SystemExit(str(message))


def main() -> None:
    language, specs, params, _ = seeded_resources()

    # rarity: common words weigh little, rare words a lot, unknown words the most
    require(weight("the") < 1 < weight("seasons") < weight("copper") < weight("zzzzqq"), "rarity order")

    # the gate drops a sentence about a different thing when a rare question term is missing
    ok, found, _s = gate._judge("What colour is hydrated copper(II) chloride, as opposed to the anhydrous form?",
                                "Anhydrous cobalt(II) chloride is blue, while the hydrated form is red.", [], "Hydration")
    require(not ok and any(d.dimension == "weighted_coverage" for d in found), found)
    ok2, _f2, _s2 = gate._judge("Where did Ada Lovelace live?", "Ada Lovelace lived in London, England.", [], "Ada Lovelace")
    require(ok2, "a responsive sentence must still pass")

    # grader v2: refusals abstain, a yes/no quote of its support is correct, v1 unchanged
    yes = {"answerable": True, "gold": "Yes", "support": "All mammals and birds are endotherms.", "type": "yesno"}
    quote = "Source text: All mammals and birds are endotherms. Source: Thermoregulation."
    require(oracle_label(yes, quote) == "wrong" and oracle_label(yes, quote, version=2) == "correct", "yes/no")
    plain = {"answerable": True, "gold": "green", "support": "", "type": "define"}
    require(oracle_label(plain, "I have no grounded cardinal value for 'x'.", version=2) == "abstain", "refusal")
    require(oracle_label({"answerable": False, "gold": "", "support": ""}, "It is blue.", version=2) == "wrong", "unsafe")

    # induction: one triple becomes a question frame and a sentence pattern the engine can replay
    got = induce("Who founded Acme?", "Bob Smith founded Acme in 1990.", "Bob Smith", language)
    require(got is not None and got.entity == "Acme", got)
    triples = [{"id": f"T{i}", "title": f"P{i}", "question": f"Who founded Co{i}?",
                "support": f"{n} founded Co{i} in 19{50 + i}.", "gold": n}
               for i, n in enumerate(["Ann Lee", "Bob Smith", "Cy Young", "Di Prince", "Ed Boyd"])]
    cands = propose(triples, language, min_group=4)
    require(cands, "five agreeing triples must give a candidate")
    c = cands[0]
    engine = RelationEngine(language, specs, ListSentenceSource([("P9", "Fay Wong founded Co9 in 1999.")]), params)
    spec = (c["name"], tuple(c["question_patterns"]), tuple(c["sentence_patterns"]), c["template"], "")
    answer = engine.ask("Who founded Co9?", extra=[spec])
    require(answer is not None and "Fay Wong" in answer.answer, (c, answer))

    # span reader: with a hand-set weight for "who -> capitalised phrase" it picks the name
    q = analyse_question("Who founded Acme?", language)
    require(q.wh == "who" and q.entity == ("acme",), q)
    weights = {"type:who|cap": 3.0, "entity_present": 0.5, "bias": 0.0}
    out = read("Who founded Acme?", [{"text": "Bob Smith founded Acme in 1990.", "title": "Acme"}], weights, language,
               threshold=0.0)
    require(out["status"] in ("answered", "low_confidence") and "Bob Smith" in out["answer"], out)
    require(read("Who founded Acme?", [{"text": "", "title": "x"}], weights, language)["status"] == "no_candidate", "empty")
    print("Phase 13 components passed")


if __name__ == "__main__":
    main()
