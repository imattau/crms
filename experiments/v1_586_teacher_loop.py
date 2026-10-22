"""Phase 12: the teacher loop accepts a verified spec, rejects a bad one, and rolls back
a round that makes the dev split worse. Synthetic corpus; no teacher call."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_relation_specs import ListSentenceSource  # noqa: E402
from crms_teacher_loop import (CorpusEngines, apply_proposals, failures, measure,  # noqa: E402
                               round_decision, split, write_brief)

POOL = [("Norland", "Valdis is the capital of Norland."), ("Estria", "Brem is the capital of Estria."),
        ("Quill", "Torvik is the capital of Quill."), ("Maren", "Selk is the capital of Maren."),
        ("Norland", "Norland is a country in the north.")]


def item(i, q, gold, answerable=True):
    return {"id": f"T{i}", "corpus": "A", "question": q, "answerable": answerable, "gold": gold,
            "support": "", "type": "where", "title": ""}


ITEMS = [item(1, "What is the capital of Norland?", "Valdis"), item(2, "What is the capital of Estria?", "Brem"),
         item(3, "What is the capital of Quill?", "Torvik"), item(4, "What is the capital of Maren?", "Selk"),
         item(5, "What is the capital of Zubria?", "", False)]

GOOD = {"name": "capital_of", "priority": 50,
        "question_patterns": ["W[what] COP DET W[capital] P[of] TAIL:E"],
        "sentence_patterns": ["NP:A COP DET W[capital] P[of] E~"],
        "template": "The capital of {E} is {A}.",
        "support": [{"q": "What is the capital of Norland?", "S": "Valdis is the capital of Norland.", "A": "Valdis", "E": "Norland"},
                    {"q": "What is the capital of Estria?", "S": "Brem is the capital of Estria.", "A": "Brem", "E": "Estria"}],
        "heldout": [{"q": "What is the capital of Quill?", "S": "Torvik is the capital of Quill.", "A": "Torvik", "E": "Quill"}],
        "contrast": [{"q": "What is the capital of Norland?", "S": "Norland is a country in the north."}],
        "rationale": "capital questions"}
BAD = dict(GOOD, name="capital_bad", sentence_patterns=["NP:A COP ...{0,6} P[of] E~"],
           contrast=[{"q": "What is the capital of Norland?", "S": "Valdis is the largest city of Norland."}])
NOHELD = dict(GOOD, name="capital_noheld", heldout=[])


def require(ok, message):
    if not ok:
        raise SystemExit(message)


def main() -> None:
    memory = PatternMemory(":memory:")
    memory.seed()
    engines = CorpusEngines(memory, {"A": ListSentenceSource(POOL)})
    train, dev = split(ITEMS)
    require(train and dev and not ({i["id"] for i in train} & {i["id"] for i in dev}), "split overlaps")
    before = measure(engines, ITEMS)
    miss = failures(ITEMS, before["rows"])
    require(len(miss) >= 3, f"expected misses, got {len(miss)}")
    brief = write_brief("/tmp/phase12_loop_test_brief.json", miss, engines, round_no=1)
    require("pattern_language" in brief and brief["existing_specs"] and brief["exemplars_by_type"], "brief incomplete")

    verdicts = apply_proposals([NOHELD, GOOD, BAD], engines, ITEMS, [s for _t, s in POOL], round_no=1)
    by = {v["name"]: v for v in verdicts}
    require(by["capital_noheld"]["accepted"] is False and any("held-out" in r for r in by["capital_noheld"]["reasons"]), by)
    require(by["capital_of"]["accepted"] is True, by["capital_of"])
    require(by["capital_bad"]["accepted"] is False, "a spec that answers its contrast must be rejected")

    after = measure(engines, ITEMS)
    d = round_decision(before["summary"], after["summary"])
    require(d["keep"] and d["dev_correct"][1] > d["dev_correct"][0], d)
    require(after["summary"]["overall"]["unsafe_on_unanswerable"] == 0, "answered an unanswerable control")
    worse = {"overall": {"wrong_share_of_answered": 0.5, "utility": 1, "correct": 1, "wrong": 1}}
    better = {"overall": {"wrong_share_of_answered": 0.2, "utility": 5, "correct": 5, "wrong": 1}}
    require(round_decision(better, worse)["keep"] is False, "a worse round must not be kept")
    print("Phase 12 teacher loop passed")


if __name__ == "__main__":
    main()
