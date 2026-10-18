"""Check one-example sentence-structure transfer under a grounded relation.

Run from the project root with:
    python3 experiments/v1_70_grounded_sentence_structure_transfer.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase, ResearchResult
from crms_research import CRMSResearchIndex


def add_source(index: CRMSResearchIndex, document_id: str, sentence: str):
    index.add_document(document_id, document_id, sentence,
                       f"sources/{document_id}.txt")
    hits = [hit for hit in index.search(sentence, limit=1000)
            if hit.document_id == document_id]
    if len(hits) != 1:
        raise SystemExit(f"source sentence was not retrieved: {document_id}")
    return hits[0]


def main() -> None:
    kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    for document_id, sentence, subject, obj in (
            ("active-ada", "Ada Lovelace designed the Analytical Engine.",
             "Ada Lovelace", "the Analytical Engine"),
            ("active-grace", "Grace Hopper designed the Compiler.",
             "Grace Hopper", "the Compiler")):
        hit = add_source(index, document_id, sentence)
        kb.add_fact_from_hit(subject, "designed", obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="designed", obj=obj,
            research_index=index, hit=hit)

    # A single independently cited passive example binds its role structure to
    # the already-supported canonical relation.
    passive_training = "The Rotor was designed by Katherine Johnson."
    hit = add_source(index, "passive-training", passive_training)
    kb.add_fact_from_hit("Katherine Johnson", "designed", "the Rotor", index, hit)
    if not kb.teach_fact_pattern_from_hit(
            passive_training, subject="Katherine Johnson", relation="designed",
            obj="the Rotor", research_index=index, hit=hit):
        raise SystemExit("one grounded passive frame did not transfer a licensed relation")

    target = "The Quantum Mill was designed by Alan Turing."
    target_hit = add_source(index, "passive-target", target)
    candidates = kb.propose_facts_from_hit(
        target, research_index=index, hit=target_hit)
    matching = [candidate for candidate in candidates
                if (candidate.subject.casefold(), candidate.relation.casefold(),
                    candidate.object.casefold())
                == ("alan turing", "designed", "the quantum mill")]
    if len(matching) != 1 or len(candidates) != 1:
        raise SystemExit(f"passive frame did not yield one unambiguous grounded triple: {candidates}")
    evidence_templates = {item["template"] for item in matching[0].language_evidence}
    evidence_sources = {source for item in matching[0].language_evidence
                        for source in item["sources"]}
    if ("<subject> <predicate> <object>" not in evidence_templates
            or "<object> was <predicate> by <subject>" not in evidence_templates
            or not any(source.startswith("active-") for source in evidence_sources)
            or not any(source.startswith("passive-training#")
                       for source in evidence_sources)):
        raise SystemExit(f"candidate omitted the language evidence that licensed transfer: {matching[0]}")
    rendered = kb.render_research(
        ResearchResult("needs_review", candidates=candidates))
    if ("Language-frame support:" not in rendered
            or "passive-training#" not in rendered):
        raise SystemExit("research review did not render language-frame provenance")
    if any(fact.subject == "Alan Turing" and fact.relation == "designed"
           and fact.object == "The Quantum Mill" for fact in kb.facts()):
        raise SystemExit("a transferred candidate was committed without review")
    kb.accept_fact_candidate(matching[0], index)

    # A single frame cannot bootstrap a new relation, even when its syntax is
    # parseable and its fact has a valid citation.
    unsupported = "Eve Example operated the Test Craft."
    hit = add_source(index, "unsupported-relation", unsupported)
    kb.add_fact_from_hit("Eve Example", "operated", "the Test Craft", index, hit)
    kb.teach_fact_pattern_from_hit(
        unsupported, subject="Eve Example", relation="operated",
        obj="the Test Craft", research_index=index, hit=hit)
    unlicensed = kb.propose_facts("Bob Example operated the Other Craft.",
                                  source="untrusted test source")
    if any(candidate.relation == "operated" for candidate in unlicensed):
        raise SystemExit("one example licensed an unsupported relation structure")

    # A positive relation frame must not license a new negative construction.
    negative_training = "Katherine Johnson did not design the Rotor."
    hit = add_source(index, "negative-training", negative_training)
    kb.add_negative_fact_from_hit(
        "Katherine Johnson", "designed", "the Rotor", index, hit)
    if kb.teach_fact_pattern_from_hit(
            negative_training, subject="Katherine Johnson", relation="designed",
            obj="the Rotor", research_index=index, hit=hit, predicate_phrase="design",
            polarity=False):
        raise SystemExit("one negative example borrowed positive-frame licensing")
    negative_unseen = kb.propose_facts(
        "Alan Turing did not design the Quantum Mill.", source="unseen negative")
    if any(not candidate.polarity and candidate.relation == "designed"
           for candidate in negative_unseen):
        raise SystemExit("positive frame licensed negative sentence extraction")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        after_reload = restored.propose_facts(target, source="reloaded source")
        if not any((candidate.subject.casefold(), candidate.relation.casefold(),
                    candidate.object.casefold())
                   == ("alan turing", "designed", "the quantum mill")
                   for candidate in after_reload):
            raise SystemExit("transferred sentence structure did not persist")

    print("grounded sentence-structure transfer diagnostic: PASS")
    print("single-example passive transfer, relation/polarity gates, unique role parsing, review-only proposal, citation acceptance, persistence: PASS")


if __name__ == "__main__":
    main()
