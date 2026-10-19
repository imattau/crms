"""Verify page-title coreference for pronoun-subject fact proposals.

Run from the project root with:
    python3 experiments/v1_416_page_title_subject_coreference.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex

PEOPLE = ("Jimmy Winston", "Pier Angeli", "Molly Ringwald")
PLACES = ("Leeds", "Cagliari", "Roseville")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def propose(kb: CRMSKnowledgeBase, index: CRMSSQLiteResearchIndex,
            document_id: str, sentence: str):
    hit = index.search(sentence.split(" was ")[0] if " was " in sentence
                       else sentence, limit=3)
    hit = next(h for h in hit if h.document_id == document_id)
    start = hit.snippet.find(sentence)
    require(start >= 0, f"sentence not inside snippet for {document_id}")
    return kb.propose_facts_from_hit(sentence, research_index=index, hit=hit)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-title-coref-") as folder:
        index = CRMSSQLiteResearchIndex(Path(folder) / "research.sqlite")
        kb = CRMSKnowledgeBase()
        # Teach one frame from a named-subject sentence so "was born in" is
        # licensed; pronoun sentences then reuse it.
        for number, (name, place) in enumerate(zip(PEOPLE, PLACES)):
            sentence = f"{name} was born in {place}."
            index.add_document(f"named-{number}", f"Biography {number}", sentence,
                               f"named-{number}.txt")
            kb.add_fact(name, "born in", place, f"named-{number}.txt#1")
            kb.teach_fact_pattern(
                sentence, subject=name, relation="born in", obj=place,
                source=f"named-{number}.txt#1", predicate_phrase="was born in",
                subject_phrase=name, object_phrase=place)
        index.add_document(
            "p1", "Jimmy Winston (musician)",
            "Jimmy Winston was an English musician. He was born in Leeds.",
            "p1.txt")
        index.add_document(
            "p2", "List of musicians",
            "Many musicians are listed here. He was born in Leeds.", "p2.txt")
        index.add_document(
            "p3", "Pier Angeli",
            "Many actors appear in films. She was born in Cagliari.", "p3.txt")

        stored = len(kb.facts())
        resolved = propose(kb, index, "p1", "He was born in Leeds.")
        require(any(c.subject == "Jimmy Winston" and c.relation == "born in"
                    and c.object == "Leeds" for c in resolved),
                f"pronoun was not resolved to the page title: {resolved}")
        require(not any(c.subject.casefold() == "he" for c in resolved),
                "resolved pronoun candidate should replace the pronoun one")
        evidence = [item for c in resolved for item in c.language_evidence
                    if item.get("kind") == "page_title_coreference"]
        require(evidence and evidence[0]["pronoun"] == "He"
                and evidence[0]["antecedent"] == "Jimmy Winston"
                and evidence[0]["review_required"] is True,
                f"missing page-title coreference evidence: {evidence}")
        require(len(kb.facts()) == stored,
                "proposal must not write to the fact store")

        for document_id, sentence, why in (
                ("p2", "He was born in Leeds.", "list title"),
                ("p3", "She was born in Cagliari.", "title absent from opening")):
            unresolved = propose(kb, index, document_id, sentence)
            require(all(item.get("kind") != "page_title_coreference"
                        for c in unresolved for item in c.language_evidence),
                    f"{why} must not resolve")
    print("page-title coreference resolves only bounded, in-opening titles")


if __name__ == "__main__":
    main()
