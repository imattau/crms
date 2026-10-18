"""Learn an irregular passive relation frame only from accepted source claims."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-291-") as folder:
        index = CRMSSQLiteResearchIndex(Path(folder) / "research.sqlite")
        knowledge = CRMSKnowledgeBase()
        examples = (
            ("Pride", "Pride was written by Jane Austen."),
            ("Utopia", "Utopia was written by Thomas More."),
        )
        for position, (title, sentence) in enumerate(examples):
            document_id = f"book-{position}"
            index.add_document(document_id, title, sentence,
                               f"fixture://{title}")
            existing_facts = len(knowledge.facts())
            proposals = knowledge._discover_surface_relation_candidates(
                sentence, source=f"unreviewed:{title}")
            assert len(proposals) == 1, proposals
            candidate = proposals[0]
            assert (candidate.subject, candidate.relation, candidate.object) == (
                sentence.split(" was written by ")[1].rstrip("."),
                "written", title)
            assert candidate.language_evidence[0]["review_required"] is True
            assert len(knowledge.facts()) == existing_facts
            hit = next(hit for hit in index.search(sentence, limit=5)
                       if hit.document_id == document_id)
            reviewed = replace(candidate, source=index.citation(hit))
            knowledge.accept_fact_candidate(reviewed, index)

        assert len(knowledge.facts()) == 2
        held_out = "A Brief History was written by Ada Lovelace."
        proposals = knowledge.propose_facts(held_out, source="fixture://held-out")
        assert len(proposals) == 1, proposals
        assert (proposals[0].subject, proposals[0].relation,
                proposals[0].object) == (
                    "Ada Lovelace", "written", "A Brief History")
        assert len(knowledge.facts()) == 2, "held-out proposal was stored without review"

        negated = knowledge._discover_surface_relation_candidates(
            "Pride was not written by Jane Austen.", source="fixture://negative")
        assert not negated, negated
        print("PASS: explicit irregular passive claims are proposed with review evidence")
        print("PASS: two accepted varied examples transfer roles to a held-out passive")
        print("PASS: transfer stays a candidate until explicitly accepted; negation is excluded")
        index.close()


if __name__ == "__main__":
    main()
