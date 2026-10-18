"""Check inflection transfer in aligned multiword predicates."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach_relation(kb: CRMSKnowledgeBase, relation: str, surface: str,
                   subject: str, obj: str, document_id: str) -> None:
    sentence = f"{subject} {surface} {obj}."
    source = f"{document_id}#sentence"
    kb.add_fact(subject, relation, obj, source)
    kb.teach_fact_pattern(sentence, subject=subject, relation=relation,
                          obj=obj, source=source, predicate_phrase=surface)


def main() -> None:
    kb = CRMSKnowledgeBase()
    # Two separate predicate families ground inflection at the first token
    # while preserving the shared particle "through".
    teach_relation(kb, "work through", "worked through", "Ada", "the puzzle",
                   "work-a")
    teach_relation(kb, "work through", "worked through", "Bea", "the problem",
                   "work-b")
    teach_relation(kb, "talk through", "talked through", "Cora", "the plan",
                   "talk-c")
    teach_relation(kb, "talk through", "talked through", "Dee", "the issue",
                   "talk-d")

    # The target relation is grounded independently in its base form.
    teach_relation(kb, "walk through", "walk through", "Teams", "the yard",
                   "walk-a")
    teach_relation(kb, "walk through", "walk through", "Groups", "the site",
                   "walk-b")
    candidate = next((item for item in kb.propose_facts(
        "Sage walked through Sculpture", source="review:past")
        if item.relation == "walk through" and item.subject == "Sage"), None)
    rule = next((item for item in (candidate.language_evidence if candidate else ())
                 if item.get("kind") == "induced_suffix"), None)
    if (candidate is None or rule is None
            or rule["canonical_form"] != "walk through"
            or rule["surface_form"] != "walked through"
            or {item["relation"] for item in rule["support"]}
            != {"talk through", "work through"}):
        raise SystemExit("multiword predicate inflection did not transfer with evidence")

    # The unchanged particle is part of the learned rule context.
    teach_relation(kb, "walk into", "walk into", "Teams", "the yard",
                   "into-a")
    teach_relation(kb, "walk into", "walk into", "Groups", "the site",
                   "into-b")
    if any(item.relation == "walk into" for item in kb.propose_facts(
            "Sage walked into Sculpture", source="review:wrong-particle")):
        raise SystemExit("multiword spelling rule transferred across particles")

    index = CRMSResearchIndex()
    index.add_document("target", "target",
                       "The historian walked through the archive.",
                       "sources/target.txt")
    retrieved = kb.research("walk through", index, limit=5)
    ids = {passage["citation"].split("#", 1)[0]
           for passage in retrieved.passages or []}
    if "target" not in ids:
        raise SystemExit("multiword inflection did not expand research retrieval")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_candidate = next((item for item in restored.propose_facts(
            "Sage walked through Sculpture", source="review:reload")
            if item.relation == "walk through" and item.subject == "Sage"), None)
        if restored_candidate is None or not any(
                item.get("surface_form") == "walked through"
                for item in restored_candidate.language_evidence):
            raise SystemExit("multiword morphology did not survive persistence")

    print("multiword predicate morphology diagnostic: PASS")
    print("aligned token induction, particle-context gate, review-only extraction, research expansion, persistence: PASS")


if __name__ == "__main__":
    main()
