"""Check source-grounded negative sentence acquisition and QA integration.

Run from the project root with:
    python3 experiments/v1_37_negative_fact_extraction.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    examples = [
        ("a", "Ada Lovelace did not design the Analytical Engine.",
         "Ada Lovelace", "the Analytical Engine"),
        ("b", "Grace Hopper did not design the Compiler.",
         "Grace Hopper", "the Compiler"),
    ]
    kb = CRMSKnowledgeBase()
    licenses = []
    for doc_id, sentence, subject, obj in examples:
        index.add_document(doc_id, doc_id, sentence, f"sources/{doc_id}.txt")
        hit = index.search(sentence, limit=1)[0]
        kb.add_negative_fact_from_hit(subject, "designed", obj, index, hit)
        licenses.append(kb.teach_fact_pattern_from_hit(
            hit.snippet, subject=subject, relation="designed", obj=obj,
            research_index=index, hit=hit, predicate_phrase="design",
            polarity=False))
        learned = kb.teach_polar_question(
            f"Did {subject} design {obj}?", subject=subject,
            relation="designed", obj=obj, answer=False)
    if licenses != [False, True] or not learned:
        raise SystemExit(f"negative examples did not license both frames: {licenses}")

    index.add_document("heldout", "Held out",
                       "Katherine Johnson did not design the trajectory table.",
                       "sources/heldout.txt")
    pending = kb.research("Did Katherine Johnson design the trajectory table?", index)
    if pending.status != "needs_review" or len(pending.candidates or []) != 1:
        raise SystemExit(f"research did not propose one negative fact: {pending}")
    candidate = pending.candidates[0]
    if (candidate.polarity is not False
            or (candidate.subject, candidate.relation, candidate.object)
            != ("Katherine Johnson", "designed", "the trajectory table")):
        raise SystemExit(f"negative extraction lost polarity or roles: {candidate}")
    if "Proposed for review (negative fact)" not in kb.render_research(pending):
        raise SystemExit("research renderer did not label negative candidate")
    if kb.propose_facts("Katherine Johnson designed the trajectory table.",
                        source="affirmative"):
        raise SystemExit("negative frame matched an affirmative sentence")

    kb.accept_fact_candidate(candidate, index)
    response = kb.ask("Did Katherine Johnson design the trajectory table?")
    if response.status != "answered" or response.truth is not False:
        raise SystemExit(f"accepted negative fact did not answer no: {response}")
    if kb.write_fact(candidate.subject, candidate.relation, candidate.object,
                     polarity=False) != [candidate.sentence]:
        raise SystemExit("negative writer dropped the source-grounded negation")

    # Contradictory positive evidence must not silently overwrite the explicit negative.
    kb.add_fact(candidate.subject, candidate.relation, candidate.object,
                "contradictory-positive-source")
    conflict = kb.ask("Did Katherine Johnson design the trajectory table?")
    if conflict.status != "ambiguous":
        raise SystemExit(f"contradiction was silently resolved: {conflict}")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_candidate = restored.propose_facts(
            "Dorothy Vaughan did not design the calculation tables.",
            source="persisted")
    if len(restored_candidate) != 1 or restored_candidate[0].polarity:
        raise SystemExit(f"negative pattern or polarity did not persist: {restored_candidate}")

    print("negative fact extraction diagnostic: PASS")
    print("negative frame learning, review, acceptance, polar QA, writing, conflict, persistence: PASS")


if __name__ == "__main__":
    main()
