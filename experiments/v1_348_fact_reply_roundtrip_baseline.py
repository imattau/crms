"""Measure role round-tripping and support checks for fact-backed replies.

This is a diagnostic for the existing fact writer, not a general NL parser.
It deliberately keeps parsing and support validation separate: a sentence can
fit a learned wording frame while asserting a tuple that is not stored.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def parsed_claims(kb: CRMSKnowledgeBase, sentence: str):
    return [
        (candidate.subject, candidate.relation, candidate.object,
         candidate.polarity, candidate.qualifiers)
        for candidate in kb.propose_facts(sentence, source="reply-roundtrip")
    ]


def main() -> None:
    kb = CRMSKnowledgeBase()
    pairs = [
        (f"Researcher {index:03d}", f"Instrument {index:03d}",
         f"source-{index:03d}")
        for index in range(100)
    ]
    for index, (subject, obj, source) in enumerate(pairs):
        kb.add_fact(subject, "designed", obj, source)
        if index < 2:
            sentence = f"{subject} designed {obj}."
            kb.teach_fact_pattern(
                sentence, subject=subject, relation="designed", obj=obj,
                source=source, predicate_phrase="designed")

    # The initial pair licenses the surface frame. The remaining 98 pairs
    # measure transfer to facts that did not license that frame.
    stored = {
        (fact.subject, fact.relation, fact.object)
        for fact in kb.facts()
    }
    correct_roundtrips = 0
    correct_replies = 0
    wrong_pairs_rejected = 0
    for index, (subject, obj, source) in enumerate(pairs):
        expected = (subject, "designed", obj, True, ())
        sentence = kb.write_fact(subject, "designed", obj)
        require(sentence == [f"{subject} designed {obj}."],
                f"fact {index} was not realized by the licensed frame: {sentence}")
        require(parsed_claims(kb, sentence[0]) == [expected],
                f"fact {index} changed roles on round trip: {sentence[0]}")
        require((subject, "designed", obj) in stored,
                f"realized fact {index} lacks independent store support")
        correct_roundtrips += 1

        question = f"Who designed {obj}?"
        if index < 2:
            kb.teach_question(question, relation="designed",
                              answer_field="subject", bound_entity=obj,
                              answer=subject)
        result = kb.ask(question)
        reply = kb.render_brief(result)
        require(result.status == "answered" and result.answer == subject,
                f"fact {index} question did not resolve: {result}")
        require(reply.startswith(sentence[0]) and source in reply,
                f"fact {index} reply lost wording or provenance: {reply}")
        require(kb.render_brief(result) == reply,
                f"fact {index} reply was nondeterministic")
        correct_replies += 1

        # For every question, supply a sentence with the right actor and
        # relation but the adjacent instrument. It fits the learned frame
        # yet states a different (unstored) tuple.
        wrong_obj = pairs[(index + 1) % len(pairs)][1]
        wrong_sentence = f"{subject} designed {wrong_obj}."
        wrong_claims = parsed_claims(kb, wrong_sentence)
        expected_wrong = (subject, "designed", wrong_obj, True, ())
        require(wrong_claims == [expected_wrong],
                f"wrong-pair {index} was not parsed as expected: {wrong_claims}")
        require((subject, "designed", wrong_obj) not in stored,
                f"wrong-pair {index} unexpectedly has stored support")
        require(kb.write_fact(subject, "designed", wrong_obj) == [],
                f"writer emitted unsupported wrong-pair {index}")
        wrong_pairs_rejected += 1

    reversed_claims = parsed_claims(kb, "Instrument 000 designed Researcher 000.")
    require(reversed_claims != [
        ("Researcher 000", "designed", "Instrument 000", True, ())],
        f"round trip failed to detect reversed semantic roles: {reversed_claims}")
    wrong_relation = parsed_claims(kb, "Researcher 000 invented Instrument 000.")
    require(not wrong_relation,
            f"unlicensed predicate unexpectedly parsed: {wrong_relation}")

    print("fact reply round-trip baseline: PASS")
    print(f"correct replies: {correct_replies}; role-preserving round trips: "
          f"{correct_roundtrips}; question/decoy pairs rejected by separate store "
          f"support check: {wrong_pairs_rejected}")
    print("reversed-role and wrong-predicate controls, citations, determinism: PASS")


if __name__ == "__main__":
    main()
