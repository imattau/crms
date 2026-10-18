"""Stress corpus-only language alignment on a 1,200-document SQLite corpus."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def main() -> None:
    pairs = 600
    with tempfile.TemporaryDirectory(prefix="crms-large-alignment-") as folder:
        index = CRMSSQLiteResearchIndex(Path(folder) / "sources.sqlite")
        try:
            for number in range(pairs - 1):
                subject = f"Researcher {number:04d}"
                obj = f"Vela Module {number:04d}"
                index.add_document(
                    f"canonical-{number:04d}", "Development record",
                    f"{subject} created {obj}.",
                    f"canonical-{number:04d}.txt")
                index.add_document(
                    f"alternate-{number:04d}", "Development record",
                    f"{subject} developed {obj}.",
                    f"alternate-{number:04d}.txt")
            heldout = pairs - 1
            heldout_subject = f"Researcher {heldout:04d}"
            heldout_object = f"Vela Module {heldout:04d}"
            heldout_sentence = f"{heldout_subject} developed {heldout_object}."
            index.add_document(
                f"alternate-{heldout:04d}", "Development record",
                heldout_sentence, f"alternate-{heldout:04d}.txt")
            index.add_document(
                f"canonical-unpaired-{heldout:04d}", "Development record",
                f"Writer {heldout:04d} created Atlas Module {heldout:04d}.",
                f"canonical-unpaired-{heldout:04d}.txt")
            kb = CRMSKnowledgeBase()
            proposals = kb.propose_corpus_predicate_alignments(
                index, maximum_documents=1500)
            proposal = next((item for item in proposals
                             if item["predicate_phrase"] == "developed"
                             and item["relation"] == "created"), None)
            trained_pairs = pairs - 1
            if (proposal is None or proposal["distinct_pairs"] != trained_pairs
                    or proposal["canonical_documents"] != trained_pairs
                    or proposal["alias_documents"] != trained_pairs):
                raise SystemExit(
                    "large SQLite corpus did not retain every aligned pair: "
                    f"{None if proposal is None else (proposal['distinct_pairs'], proposal['canonical_documents'], proposal['alias_documents'])}")
            if kb.facts():
                raise SystemExit("large-corpus proposal wrote facts before review")
            kb.accept_corpus_predicate_alignment(
                proposal["proposal_id"], index, maximum_documents=1500)
            for number in (0, 137, 598):
                query = f"Who developed the Vela Module {number:04d}?"
                answer = kb.ask(query)
                expected = f"Researcher {number:04d}"
                if (answer.status != "answered" or answer.answer != expected
                        or not answer.evidence):
                    raise SystemExit(
                        f"large-corpus learned language failed {query}: {answer}")
            source_hit = next(
                hit for hit in index.search(heldout_sentence, limit=10)
                if hit.document_id == f"alternate-{heldout:04d}")
            candidates = kb.propose_facts(
                heldout_sentence, source=index.citation(source_hit))
            if (len(candidates) != 1
                    or candidates[0].relation != "created"
                    or candidates[0].subject != heldout_subject
                    or candidates[0].object != heldout_object):
                raise SystemExit(
                    "accepted corpus pattern did not generalize to an unseen pair: "
                    f"{candidates}")
            kb.accept_fact_candidate(candidates[0], index)
            heldout_answer = kb.ask(
                f"Who developed the {heldout_object}?")
            if (heldout_answer.status != "answered"
                    or heldout_answer.answer != heldout_subject):
                raise SystemExit(
                    f"held-out pair failed after candidate review: {heldout_answer}")
            print("large corpus-only alignment diagnostic: PASS")
            print("SQLite documents=1200; training pairs=599; accepted alignment; held-out entity-pair candidate review and answer; provenance: PASS")
        finally:
            index.close()


if __name__ == "__main__":
    main()
