"""Ensure shared-document mentions do not hide independent alignment sources."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-334-") as folder:
        index = CRMSSQLiteResearchIndex(Path(folder) / "research.sqlite")
        # Sorted document order makes this co-mentioned record the first
        # occurrence of Ada's pair for both predicates. It cannot count as
        # independent cross-predicate support by itself.
        index.add_document(
            "a-shared", "Development history",
            "Ada created Engine. Ada developed Engine.", "shared.txt")
        index.add_document(
            "b-canonical-ada", "Creation note",
            "Ada created Engine.", "canonical-ada.txt")
        index.add_document(
            "c-alias-ada", "Development note",
            "Ada developed Engine.", "alias-ada.txt")
        index.add_document(
            "d-canonical-bea", "Creation note",
            "Bea created Compiler.", "canonical-bea.txt")
        index.add_document(
            "e-alias-bea", "Development note",
            "Bea developed Compiler.", "alias-bea.txt")

        knowledge = CRMSKnowledgeBase()
        proposals = knowledge.propose_corpus_predicate_alignments(
            index, maximum_documents=10, maximum_sentences=100)
        proposal = next((row for row in proposals
                         if {row["relation"], row["predicate_phrase"]}
                         == {"created", "developed"}), None)
        if proposal is None or proposal["distinct_pairs"] != 2:
            raise SystemExit(
                "independent sources were hidden by first same-document rows: "
                f"{proposals}")
        ada = next(row for row in proposal["support"]
                   if row["subject"] == "Ada")
        if (ada["canonical_document_id"]
                == ada["alias_document_id"]):
            raise SystemExit(
                "proposal used the shared document for both sides of an alignment")
        if knowledge.facts():
            raise SystemExit("report-only discovery wrote facts before review")

        accepted = knowledge.accept_corpus_predicate_alignment(
            proposal["proposal_id"], index, maximum_documents=10,
            maximum_sentences=100)
        answer = knowledge.ask("Who developed Engine?")
        if (answer.status != "answered" or answer.answer != "Ada"
                or not answer.evidence):
            raise SystemExit(
                f"reviewed evidence did not transfer to the queried wording: {answer}")
        if accepted["predicate_phrase"] != "developed":
            raise SystemExit(f"unexpected alias direction: {accepted}")
        print("PASS: first same-document mentions do not hide independent sources")
        print("PASS: alignment still requires two distinct entity pairs")
        print("PASS: no facts are written before explicit acceptance")
        print("PASS: accepted, source-backed wording answers a recombined query")
        index.close()


if __name__ == "__main__":
    main()
