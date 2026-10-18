"""Check teacher-grounded predicate variation without a synonym inventory.

Run from the project root with:
    python3 experiments/v1_34_grounded_predicate_learning.py
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
        ("a", "Ada Lovelace designed the Analytical Engine.",
         "Ada Lovelace", "the Analytical Engine", "designed"),
        ("b", "Grace Hopper built the Compiler.",
         "Grace Hopper", "the Compiler", "built"),
    ]
    kb = CRMSKnowledgeBase()
    licensed = []
    for doc_id, sentence, subject, obj, phrase in examples:
        index.add_document(doc_id, doc_id, sentence, f"sources/{doc_id}.txt")
        hit = index.search(sentence, limit=1)[0]
        kb.add_fact_from_hit(subject, "created", obj, index, hit)
        licensed.append(kb.teach_fact_pattern_from_hit(
            hit.snippet, subject=subject, relation="created", obj=obj,
            predicate_phrase=phrase, research_index=index, hit=hit))
    if licensed != [False, True]:
        raise SystemExit(f"distinct predicate examples did not license a frame: {licensed}")

    index.add_document("heldout", "Held out", 
                       "Katherine Johnson designed the trajectory table.",
                       "sources/heldout.txt")
    hit = index.search("Katherine Johnson designed the trajectory table", limit=1)[0]
    proposals = kb.propose_facts_from_hit(hit.snippet, research_index=index, hit=hit)
    if (len(proposals) != 1
            or (proposals[0].subject, proposals[0].relation, proposals[0].object)
            != ("Katherine Johnson", "created", "the trajectory table")):
        raise SystemExit(f"known predicate did not transfer to a new fact: {proposals}")

    unknown = "Katherine Johnson engineered the trajectory table."
    if kb.propose_facts(unknown, source="unseen"):
        raise SystemExit("an ungrounded predicate phrase was treated as known")
    kb.accept_fact_candidate(proposals[0], index)
    if kb.write_fact("Katherine Johnson", "created", "the trajectory table") != [
            "Katherine Johnson built the trajectory table.",
            "Katherine Johnson designed the trajectory table."]:
        raise SystemExit("writer did not preserve both grounded predicate realizations")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_proposals = restored.propose_facts(
            "Dorothy Vaughan built the calculation tables.", source="another")
    if (len(restored_proposals) != 1
            or restored_proposals[0].relation != "created"):
        raise SystemExit(f"predicate evidence did not persist: {restored_proposals}")

    print("grounded predicate learning diagnostic: PASS")
    print("canonical relation alignment, held-out transfer, unseen-phrase abstention, writing, persistence: PASS")


if __name__ == "__main__":
    main()
