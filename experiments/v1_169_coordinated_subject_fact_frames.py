"""Extract two grounded claims from one coordinated-subject assertion."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach(kb: CRMSKnowledgeBase, subject: str, obj: str, source: str) -> None:
    kb.add_fact(subject, "designed", obj, source)
    kb.teach_fact_pattern(
        f"{subject} designed {obj}.", subject=subject, relation="designed",
        obj=obj, source=source, predicate_phrase="designed")


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach(kb, "Ada", "the Engine", "design-a")
    teach(kb, "Grace", "the Compiler", "design-g")
    teach(kb, "Katherine Johnson", "the Rotor", "design-k")

    sentence = "Ada and Grace designed the Rotor."
    proposals = kb.propose_facts(sentence, source="review:coordinated-subject")
    claims = {(item.subject, item.relation, item.object) for item in proposals}
    if claims != {
            ("Ada", "designed", "the Rotor"),
            ("Grace", "designed", "the Rotor"),
    }:
        raise SystemExit(f"coordinated subjects were not distributed: {claims}")
    if any(item.sentence != sentence for item in proposals):
        raise SystemExit("coordinated proposals lost their complete source sentence")
    if len(kb.facts()) != 3:
        raise SystemExit("coordinated subject proposals were auto-committed")

    both = kb.propose_facts(
        "Both Ada and Katherine Johnson designed the Rotor.",
        source="review:both-subjects")
    if {(item.subject, item.relation, item.object) for item in both} != {
            ("Ada", "designed", "the Rotor"),
            ("Katherine Johnson", "designed", "the Rotor"),
    }:
        raise SystemExit(f"multiword/marked coordination failed: {both}")

    # A new name can be proposed under a learned relation frame, but an
    # unsupported predicate cannot borrow the other subject's licensed claim.
    unseen = kb.propose_facts(
        "Ada and Zoe designed the Rotor.", source="review:unseen-subject")
    if {(item.subject, item.relation, item.object) for item in unseen} != {
            ("Ada", "designed", "the Rotor"),
            ("Zoe", "designed", "the Rotor"),
    }:
        raise SystemExit(f"source-backed unseen subject was not reviewable: {unseen}")
    unsupported = kb.propose_facts(
        "Ada and Zoe invented the Rotor.", source="review:unsupported")
    if unsupported:
        raise SystemExit("one licensed half leaked from an unsupported coordination")
    multiple_subjects = kb.propose_facts(
        "Ada and Grace and Zoe designed the Rotor.",
        source="review:multiple-subjects")
    if multiple_subjects:
        raise SystemExit("unsupported three-subject coordination was partly parsed")

    index = CRMSResearchIndex()
    index.add_document("coordinated", "Coordinated subjects", sentence,
                       "https://research.test/coordinated")
    research = kb.research(sentence, index, limit=10)
    expected_new = {
        ("Ada", "designed", "the Rotor"),
        ("Grace", "designed", "the Rotor"),
    }
    research_claims = {
        (item.subject, item.relation, item.object)
        for item in research.candidates or []
    }
    citation = index.citation(next(
        hit for hit in index.search(sentence, limit=10)
        if hit.document_id == "coordinated"))
    if (research.status != "needs_review"
            or research_claims != expected_new
            or any(item.source != citation or item.sentence != sentence
                   for item in research.candidates or [])):
        raise SystemExit("research lost citation or review boundaries")
    if len(kb.facts()) != 3:
        raise SystemExit("research committed coordinated-subject candidates")

    print("coordinated-subject fact-frame diagnostic: PASS")
    print("shared-frame distribution, unseen entity proposal, unsupported-predicate abstention, complete citation, review-only behavior: PASS")


if __name__ == "__main__":
    main()
