"""Keep dotted initialisms attached to following words during sentence splitting."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex, _sentence_spans


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    cases = (
        ("Ban met U.S. Secretary of State. The talks continued.",
         ("Ban met U.S. Secretary of State.", "The talks continued.")),
        ("The group met U.S. forces. It later left.",
         ("The group met U.S. forces.", "It later left.")),
        ("The delegation travelled to the U.S. It continued.",
         ("The delegation travelled to the U.S.", "It continued.")),
        ("The U.K. minister arrived. Later, the group left.",
         ("The U.K. minister arrived.", "Later, the group left.")),
        ("Ban met U.S. President John F. Kennedy. The talks ended.",
         ("Ban met U.S. President John F. Kennedy.", "The talks ended.")),
    )
    for text, expected in cases:
        actual = tuple(text[start:end] for start, end in _sentence_spans(text))
        require(actual == expected,
                f"incorrect sentence boundaries: {actual!r} != {expected!r}")

    index = CRMSResearchIndex()
    index.add_document(
        "meeting-one", "Meeting one",
        "Ban met U.S. President John F. Kennedy.",
        "https://meeting-one.example/source")
    index.add_document(
        "meeting-two", "Meeting two",
        "Lee met U.K. Prime Minister Alex Smith.",
        "https://meeting-two.example/source")
    proposals = CRMSKnowledgeBase().propose_corpus_relation_frames(index)
    met = next((item for item in proposals if item["relation"] == "met"), None)
    require(met is not None and len(met["support"]) == 2,
            f"complete sentences did not form a reviewed frame: {proposals!r}")
    objects = {row["object"] for row in met["support"]}
    require(objects == {"U.S. President John F. Kennedy",
                        "U.K. Prime Minister Alex Smith"},
            f"initialism continuation was truncated from an object: {objects!r}")
    for row in met["support"]:
        require(index.resolve_citation(row["source"]) == row["sentence"],
                "proposal citation did not resolve to its complete sentence")

    print("dotted-initialism sentence boundaries and source spans: PASS")
    print("review proposals retain the full U.S. role noun phrase: PASS")


if __name__ == "__main__":
    main()
