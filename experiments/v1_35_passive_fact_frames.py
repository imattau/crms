"""Check semantic argument roles in learned passive sentence frames.

Run from the project root with:
    python3 experiments/v1_35_passive_fact_frames.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    examples = [
        ("a", "The Analytical Engine was designed by Ada Lovelace.",
         "Ada Lovelace", "The Analytical Engine"),
        ("b", "The Compiler was designed by Grace Hopper.",
         "Grace Hopper", "The Compiler"),
    ]
    kb = CRMSKnowledgeBase()
    for doc_id, sentence, agent, patient in examples:
        index.add_document(doc_id, doc_id, sentence, f"sources/{doc_id}.txt")
        hit = index.search(sentence, limit=1)[0]
        kb.add_fact_from_hit(agent, "designed", patient, index, hit)
        licensed = kb.teach_fact_pattern_from_hit(
            hit.snippet, subject=agent, relation="designed", obj=patient,
            research_index=index, hit=hit)
        if doc_id == "a" and licensed:
            raise SystemExit("one passive example unexpectedly licensed a frame")
        if doc_id == "b" and not licensed:
            raise SystemExit("two passive examples did not license a frame")
        question = f"Who was {patient} designed by?"
        if not kb.teach_question(
                question, relation="designed", answer_field="subject",
                bound_entity=patient, answer=agent):
            if doc_id == "b":
                raise SystemExit("passive question frame was not learned")

    index.add_document(
        "c", "Held out", "The trajectory table was designed by Katherine Johnson.",
        "sources/heldout.txt")
    hit = index.search("trajectory table designed Katherine Johnson", limit=1)[0]
    proposals = kb.propose_facts_from_hit(hit.snippet, research_index=index, hit=hit)
    if (len(proposals) != 1
            or (proposals[0].subject, proposals[0].relation, proposals[0].object)
            != ("Katherine Johnson", "designed", "The trajectory table")):
        raise SystemExit(f"passive frame reversed or lost semantic roles: {proposals}")
    kb.accept_fact_candidate(proposals[0], index)
    response = kb.ask("Who was The trajectory table designed by?")
    if response.status != "answered" or response.answer != "Katherine Johnson":
        raise SystemExit(f"passive learned question frame failed: {response}")

    print("passive fact-frame diagnostic: PASS")
    print("agent/patient role grounding, passive extraction, passive question transfer: PASS")


if __name__ == "__main__":
    main()
