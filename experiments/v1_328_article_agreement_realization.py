"""Apply deterministic a/an agreement to licensed is-a realizations."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase, _indefinite_article_for
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def teach(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
          source_id: str, sentence: str, subject: str, obj: str) -> bool:
    index.add_document(source_id, source_id, sentence, f"{source_id}.txt")
    hit = index.search(sentence, limit=1)[0]
    source = index.citation(hit)
    kb.add_fact(subject, "is-a", obj, source)
    return kb.teach_fact_pattern_from_hit(
        sentence, subject=subject, relation="is-a", obj=obj,
        research_index=index, hit=hit,
        predicate_phrase=("is an" if " is an " in sentence.casefold()
                          else "is a"))


def main() -> None:
    for noun, expected in (
        ("island", "an"), ("orange", "an"), ("hour", "an"),
        ("university", "a"), ("European", "a"), ("one-time event", "a"),
        ("user", "a"), ("honest person", "an"), ("topaz", "a"),
    ):
        require(_indefinite_article_for(noun) == expected,
                f"wrong article for {noun!r}")
    require(_indefinite_article_for("42") is None,
            "numeric phrase received an unsupported article choice")

    with tempfile.TemporaryDirectory(prefix="crms-article-writing-") as folder:
        index = CRMSResearchIndex()
        kb = CRMSKnowledgeBase()
        require(not teach(kb, index, "citrine", "Rila is a citrine.",
                          "Rila", "citrine"),
                "one example should not license the frame")
        require(teach(kb, index, "topaz", "Mira is a topaz.",
                      "Mira", "topaz"),
                "two varied examples did not license the frame")
        kb.teach_question("What is Rila?", relation="is-a",
                          answer_field="object", bound_entity="Rila",
                          answer="citrine")
        kb.teach_question("What is Mira?", relation="is-a",
                          answer_field="object", bound_entity="Mira",
                          answer="topaz")
        for source_id, subject, obj, expected in (
            ("island", "Cia", "island", "Cia is an island."),
            ("university", "Dara", "university", "Dara is a university."),
            ("hour", "Eris", "hour", "Eris is an hour."),
        ):
            kb.add_fact(subject, "is-a", obj, f"fixture:{source_id}")
            require(kb.write_fact(subject, "is-a", obj) == [expected],
                    f"learned is-a frame did not adjust article for {obj}: "
                    f"{kb.write_fact(subject, 'is-a', obj)}")
            if subject == "Cia":
                answer = kb.ask("What is Cia?")
                require(answer.status == "answered" and answer.answer == "island",
                        f"learned type question did not answer: {answer}")
                require(kb.render_brief(answer).startswith(expected),
                        f"chat-facing realization lost article agreement: "
                        f"{kb.render_brief(answer)}")

        # An `an` template must also change to `a` on a consonant onset.
        other = CRMSKnowledgeBase()
        other_index = CRMSResearchIndex()
        require(not teach(other, other_index, "apple", "Iris is an apple.",
                          "Iris", "apple"), "first an-frame example licensed early")
        require(teach(other, other_index, "orange", "Neri is an orange.",
                      "Neri", "orange"), "varied an-frame did not license")
        other.add_fact("Oda", "is-a", "pear", "fixture:pear")
        require(other.write_fact("Oda", "is-a", "pear") == ["Oda is a pear."],
                "learned an-frame did not adapt to a consonant onset")

        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        require(restored.write_fact("Cia", "is-a", "island")
                == ["Cia is an island."],
                "article realization changed after save/load")

    print("licensed is-a article agreement: PASS")
    print("a/an onset rule, varied-frame threshold, both directions and persistence: PASS")


if __name__ == "__main__":
    main()
