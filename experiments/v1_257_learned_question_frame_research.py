"""Check that learned natural-language question frames expand retrieval.

Run from the project root with:
    python3 experiments/v1_257_learned_question_frame_research.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex, CRMSSQLiteResearchIndex


ROWS = (
    ("Ada", "Vela instrument A"),
    ("Bea", "Vela instrument B"),
    ("Cy", "Vela instrument C"),
)


def exercise(index) -> None:
    kb = CRMSKnowledgeBase()
    for position, (person, instrument) in enumerate(ROWS):
        sentence = f"{person} designed the {instrument}."
        document_id = f"design-record-{position}"
        index.add_document(document_id, f"Design record {position}", sentence,
                           f"records/{document_id}.txt")
        if position >= 2:
            continue
        hit = next(hit for hit in index.search(sentence, limit=5)
                   if hit.document_id == document_id)
        kb.add_fact_from_hit(person, "designed", f"the {instrument}",
                             index, hit)
        licensed = kb.teach_question(
            f"Who was the designer of the {instrument}?",
            relation="designed", answer_field="subject",
            bound_entity=f"the {instrument}", answer=person)
        if licensed != (position == 1):
            raise SystemExit("the nominal question frame licensed at the wrong point")

    heldout_question = "Who was the designer of the Vela instrument C?"
    before_learning = CRMSKnowledgeBase().research(
        heldout_question, index, limit=5)
    if any(record.get("kind") == "learned_question_frame"
           for record in before_learning.query_expansions or []):
        raise SystemExit("an untrained question frame was reported as learned")

    result = kb.research(heldout_question, index, limit=5)
    frame_expansions = [record for record in result.query_expansions or []
                        if record.get("kind") == "learned_question_frame"]
    if not any(record.get("text") == "designed"
               and record.get("sources") for record in frame_expansions):
        raise SystemExit("the learned frame did not expose its grounded relation and sources")
    if not any(row["text"] == "Cy designed the Vela instrument C."
               for row in result.source_sentences or []):
        raise SystemExit("learned-frame retrieval missed the held-out source sentence")
    if any(fact.subject == "Cy" for fact in kb.facts()):
        raise SystemExit("retrieved held-out evidence was incorrectly stored as a fact")


def main() -> None:
    exercise(CRMSResearchIndex())
    with tempfile.TemporaryDirectory(prefix="crms-learned-frame-") as folder:
        index = CRMSSQLiteResearchIndex(Path(folder) / "sources.sqlite")
        try:
            exercise(index)
        finally:
            index.close()
    print("learned question-frame research diagnostic: PASS")
    print("two-example licensing, held-out evidence retrieval, source provenance, "
          "no automatic fact write-back, in-memory/SQLite parity: PASS")


if __name__ == "__main__":
    main()
