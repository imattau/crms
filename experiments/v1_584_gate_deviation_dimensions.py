"""Phase 12: the quote-evidence gate names why a sentence fails (deviation dimensions).

Each deviation of a candidate sentence from what the question requires carries a
dimension (fragment, entity_absent, relation_not_predicated, relation_coverage,
answer_type_mismatch, answer_slot_unfilled, role_order) and a witness reason. Which
dimensions are invariant is data in the SQL ``pat_gate_policy`` table, not code.

Run with: python3 experiments/v1_584_gate_deviation_dimensions.py
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import crms_nl_gate as gate  # noqa: E402
from crms_pattern_memory import PatternMemory  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")


def dims(question: str, sentence: str, title: str = "") -> set[str]:
    _ok, found, _score = gate._judge(question, sentence, [], title)
    return {d.dimension for d in found}


def main() -> None:
    # policy is SQL data
    with PatternMemory(":memory:") as memory:
        memory.seed()
        policy = memory.gate_policy()
    require({"fragment", "entity_absent", "relation_not_predicated", "relation_coverage",
             "answer_type_mismatch", "answer_slot_unfilled", "role_order"} <= set(policy),
            sorted(policy))
    require(all(row["invariant"] for row in policy.values()), "seed dimensions are invariant")
    require(policy["relation_coverage"]["threshold"] == 0.67, policy["relation_coverage"])
    require(policy == gate.gate_policy(), "the gate reads the seeded policy")

    # fragment: section label, truncation, table row, timeline entry
    q = "What is BlackWatch?"
    require("fragment" in dims(q, "Title: BlackWatch: Increasing Attack Awareness Within Web Applications"), "title")
    require("fragment" in dims("Where are word embeddings used?",
                               "Word embeddings represent words as vectors based on counts of"), "truncated")
    require("fragment" in dims("When was Filmation founded?",
                               "2013 – Lou Scheimer, animator, co-founded the Filmation Company."), "timeline")
    require("fragment" in dims("What sort of song is Oy pri luzhku?", 'Oy pri luzhku (lit.'), "unbalanced")
    require("fragment" in dims("Who directed X Film?", "Infobox film name = X Film director = Y"), "infobox")
    require("fragment" not in dims("Where did Ada Lovelace live?", "Ada Lovelace lived in London, England."), "clean")

    # slots
    require("answer_slot_unfilled" in dims("In which year did Julieta Venegas put out Limón y Sal?",
                                           "Limón y Sal is the fourth studio album released by Julieta Venegas."),
            "year slot")
    require("answer_slot_unfilled" not in dims("In which year was Ada Lovelace born?",
                                               "Ada Lovelace was born in 1815."), "year present")
    require("answer_slot_unfilled" in dims("How many people attended the lecture at Concord Lyceum?",
                                           "In 1848, Thoreau lectured at the Concord Lyceum to people."),
            "count not next to the noun")
    require("answer_slot_unfilled" not in dims("For how many years did Blueger play at Minnesota State?",
                                               "Blueger played four years with the Minnesota State Mavericks."),
            "count next to the noun")

    # coverage: terms naming the cited document are topic, not relation
    require("relation_coverage" in dims(
        "Which techniques underlie the learning-aided comparison schemes?",
        "In this paper, we formulate the problem of service chain composition as a game."),
        "relation terms absent")
    covered = "How does LaMP compute the hidden representation of each label?"
    require("relation_coverage" in dims(covered, "LaMP is a model of labels."), "uncovered")
    require("relation_coverage" not in dims(
        "On what real example is the chemical reaction network approach demonstrated?",
        "We demonstrate the practical utility of our approach on a real protodeboronation example.",
        title="Chemical reaction network for protodeboronation"), "title words are topic")

    # dash normalisation: Saffir–Simpson (en dash) against Saffir-Simpson
    require("entity_absent" not in dims("What is the Saffir–Simpson scale used for?",
                                        "The Saffir-Simpson scale is used to rank hurricanes."),
            "en dash joins")

    # a typed rejection comes back with its dimensions
    decision = gate.gate_quoted_evidence(
        "In which year did Julieta Venegas put out Limón y Sal?",
        [{"text": "Limón y Sal is the fourth studio album released by Julieta Venegas.", "title": "Limón y Sal"}])
    require(decision["status"] == "rejected" and "answer_slot_unfilled" in decision["dimensions"], decision)

    # shape-independent check on the one sentence a quote fallback would show
    shown = gate.gate_displayed_quote(
        "Whose use of grey literature does the survey paper study?",
        {"text": "Objective: To reduce the bias in the study selection process.", "title": "SLR"})
    require(shown["status"] == "rejected" and "fragment" in shown["dimensions"], shown)
    kept = gate.gate_displayed_quote(
        "Are all mammals and birds endotherms?",
        {"text": "All mammals and birds are endotherms (homeotherms or homoiotherms).",
         "title": "Thermoregulation"})
    require(kept["status"] == "accepted", kept)

    # turning a dimension off in the policy is a data change, not a code change
    original = gate.gate_policy
    try:
        relaxed = {k: dict(v) for k, v in original().items()}
        relaxed["fragment"]["invariant"] = False
        gate.gate_policy = lambda: relaxed
        require("fragment" not in {d.dimension for d in gate._judge(
            "What is BlackWatch?", "Title: BlackWatch: Increasing Attack Awareness", [])[1]},
            "a non-invariant dimension must not reject")
    finally:
        gate.gate_policy = original
    print("Phase 12 gate deviation dimensions passed")


if __name__ == "__main__":
    main()
