"""Check retrieval-to-candidate-to-answer research workflow without auto-commit.

Run from the project root with:
    python3 experiments/v1_33_grounded_research_workflow.py
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
        ("source-a", "Ada Lovelace designed the Analytical Engine."),
        ("source-b", "Grace Hopper designed the Compiler."),
        ("source-c", "Katherine Johnson designed the trajectory table."),
    ]
    hits = []
    for doc_id, sentence in examples:
        index.add_document(doc_id, doc_id, sentence, f"research/{doc_id}.txt")
        hits.append(index.search(sentence, limit=1)[0])

    kb = CRMSKnowledgeBase()
    for hit, subject, obj in zip(
            hits[:2], ("Ada Lovelace", "Grace Hopper"),
            ("the Analytical Engine", "the Compiler")):
        kb.add_fact_from_hit(subject, "designed", obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            hit.snippet, subject=subject, relation="designed", obj=obj,
            research_index=index, hit=hit)
        kb.teach_question(
            f"Who designed {obj}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject)

    pending = kb.research("Who designed the trajectory table?", index)
    if pending.status != "needs_review" or len(pending.candidates or []) != 1:
        raise SystemExit(f"research did not return one reviewable candidate: {pending}")
    if len(kb.facts()) != 2:
        raise SystemExit("research committed a proposed fact without review")
    candidate = pending.candidates[0]
    if ((candidate.subject, candidate.relation, candidate.object)
            != ("Katherine Johnson", "designed", "the trajectory table")):
        raise SystemExit(f"wrong candidate extracted from source: {candidate}")
    rendered = kb.render_research(pending)
    if ("Proposed for review" not in rendered
            or candidate.source not in rendered
            or candidate.sentence not in rendered):
        raise SystemExit(f"review output omitted candidate provenance: {rendered}")

    kb.accept_fact_candidate(candidate, index)
    answered = kb.research("Who designed the trajectory table?", index)
    if answered.status != "answered" or not answered.response:
        raise SystemExit(f"accepted fact did not ground research answer: {answered}")
    if answered.response.answer != "Katherine Johnson":
        raise SystemExit(f"research returned wrong answer: {answered.response}")
    if answered.candidates:
        raise SystemExit("already-stored fact was proposed again")
    final_text = kb.render_research(answered)
    if candidate.source not in final_text:
        raise SystemExit("answer renderer omitted the fact citation")

    unknown = kb.research("Who discovered quantum telepathy?", index)
    if unknown.status != "unknown" or unknown.response.status != "unknown":
        raise SystemExit(f"unsupported research question did not abstain: {unknown}")
    print("grounded research workflow diagnostic: PASS")
    print("retrieval, review-only extraction, explicit acceptance, cited answer, abstention: PASS")


if __name__ == "__main__":
    main()
