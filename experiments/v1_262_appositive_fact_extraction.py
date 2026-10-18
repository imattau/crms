"""Extract bounded appositive facts without swallowing clause boundaries."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    kb = CRMSKnowledgeBase()
    examples = (
        ("passive-python",
         "Python, a high-level programming language, was created by Guido van Rossum.",
         "Guido van Rossum", "created", "Python"),
        ("passive-linux",
         "Linux, an open-source operating system, was created by Linus Torvalds.",
         "Linus Torvalds", "created", "Linux"),
        ("active-python",
         "Guido van Rossum, a Dutch programmer, created Python.",
         "Guido van Rossum", "created", "Python"),
        ("trailing-python",
         "Guido van Rossum created Python, a popular programming language.",
         "Guido van Rossum", "created", "Python"),
    )
    index = CRMSResearchIndex()
    for document_id, sentence, *_ in examples:
        index.add_document(document_id, "Computing history", sentence,
                           f"{document_id}.txt")
        hit = next(hit for hit in index.search(sentence, limit=10)
                   if hit.document_id == document_id)
        candidates = kb._discover_surface_relation_candidates(
            sentence, source=index.citation(hit), research_index=index)
        if len(candidates) != 1:
            raise SystemExit(f"appositive did not yield one review candidate: {sentence}: {candidates}")
        candidate = candidates[0]
        expected = examples[[row[0] for row in examples].index(document_id)][2:]
        if ((candidate.subject, candidate.relation, candidate.object) != expected
                or candidate.sentence != sentence
                or not any(item.get("method")
                           == "single bounded nominal appositive with unique core parse"
                           for item in candidate.language_evidence)):
            raise SystemExit(f"appositive roles or exact source span changed: {candidate}")

    proposal = next((item for item in kb.propose_corpus_relation_frames(index)
                     if item["relation"] == "created"), None)
    if proposal is None or len(proposal["support"]) != 2:
        raise SystemExit(
            f"appositive source frames did not group across distinct pairs: {proposal}")
    kb.accept_corpus_relation_frame(proposal["proposal_id"], index)

    for query, expected in (("Who created Python?", "Guido van Rossum"),
                            ("Who created Linux?", "Linus Torvalds")):
        answer = kb.ask(query)
        if answer.status != "answered" or answer.answer != expected:
            raise SystemExit(f"reviewed appositive fact did not answer {query}: {answer}")
        if not answer.evidence:
            raise SystemExit(f"appositive answer lost provenance: {answer}")

    unsafe = (
        "Guido van Rossum, who created Python, worked at Bletchley Park.",
        "Guido van Rossum created Python, but Linus Torvalds created Linux.",
    )
    for sentence in unsafe:
        if kb._discover_surface_relation_candidates(sentence, source="scratch"):
            raise SystemExit(
                "unsupported comma attachment produced a candidate: "
                f"{sentence}")

    print("bounded appositive fact extraction diagnostic: PASS")
    print("active/passive and trailing appositives, unchanged sentence provenance, reviewed QA, ambiguous comma attachment abstention: PASS")


if __name__ == "__main__":
    main()
