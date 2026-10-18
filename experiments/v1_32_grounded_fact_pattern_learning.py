"""Check non-LLM relation-frame learning from source-backed sentences.

Run from the project root with:
    python3 experiments/v1_32_grounded_fact_pattern_learning.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def add_sentence(index: CRMSResearchIndex, document_id: str,
                 sentence: str):
    index.add_document(document_id, document_id, sentence, document_id)
    hit = index.search(sentence, limit=1)[0]
    return hit.snippet, hit


def main() -> None:
    index = CRMSResearchIndex()
    sentence_a, hit_a = add_sentence(
        index, "source-a", "Ada Lovelace designed the Analytical Engine.")
    sentence_b, hit_b = add_sentence(
        index, "source-b", "Grace Hopper designed the Compiler.")
    source_a, source_b = index.citation(hit_a), index.citation(hit_b)
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada Lovelace", "designed", "the Analytical Engine", source_a)
    kb.add_fact("Grace Hopper", "designed", "the Compiler", source_b)

    if kb.teach_fact_pattern_from_hit(
        sentence_a, subject="Ada Lovelace", relation="designed",
        obj="the Analytical Engine", research_index=index, hit=hit_a,
    ):
        raise SystemExit("one sentence should not license extraction")
    first_status = kb.fact_pattern_diagnostics(
        sentence_a, subject="Ada Lovelace", relation="designed",
        obj="the Analytical Engine")
    if (first_status.get("status") != "unlicensed"
            or first_status.get("distinct_pairs") != 1
            or first_status.get("distinct_subjects") != 1
            or first_status.get("distinct_objects") != 1
            or len(first_status.get("cited_sources", [])) != 1):
        raise SystemExit(f"first-example licensing diagnostics were unclear: {first_status}")
    if kb.propose_facts(
        "Katherine Johnson designed the trajectory table.", source="unseen"):
        raise SystemExit("fact pattern generalized from one example")
    if not kb.teach_fact_pattern_from_hit(
        sentence_b, subject="Grace Hopper", relation="designed",
        obj="the Compiler", research_index=index, hit=hit_b,
    ):
        raise SystemExit("two distinct grounded sentences did not license the frame")
    second_status = kb.fact_pattern_diagnostics(
        sentence_b, subject="Grace Hopper", relation="designed",
        obj="the Compiler")
    if (second_status.get("status") != "licensed"
            or second_status.get("distinct_pairs") != 2
            or second_status.get("distinct_subjects") != 2
            or second_status.get("distinct_objects") != 2):
        raise SystemExit(f"varied-example licensing was not explained: {second_status}")

    question_a = "Who designed the Analytical Engine?"
    question_b = "Who designed the Compiler?"
    kb.teach_question(question_a, relation="designed", answer_field="subject",
                      bound_entity="the Analytical Engine", answer="Ada Lovelace")
    kb.teach_question(question_b, relation="designed", answer_field="subject",
                      bound_entity="the Compiler", answer="Grace Hopper")

    sentence_c, hit_c = add_sentence(
        index, "source-c", "Katherine Johnson designed the trajectory table.")
    source_c = index.citation(hit_c)
    proposals = kb.propose_facts_from_hit(sentence_c, research_index=index, hit=hit_c)
    if len(proposals) != 1:
        raise SystemExit(f"expected one fact candidate, got: {proposals}")
    candidate = proposals[0]
    if ((candidate.subject, candidate.relation, candidate.object)
            != ("Katherine Johnson", "designed", "the trajectory table")
            or candidate.source != source_c):
        raise SystemExit(f"extracted candidate or provenance is wrong: {candidate}")
    if len(kb.facts()) != 2:
        raise SystemExit("candidate fact was committed without explicit acceptance")

    repeated_explicit_clauses = (
        "Katherine Johnson designed the trajectory table and "
        "Katherine Johnson designed the other thing.")
    repeated_candidates = kb.propose_facts(
        repeated_explicit_clauses, source="ambiguous-source")
    if {(item.subject, item.relation, item.object) for item in repeated_candidates} != {
            ("Katherine Johnson", "designed", "the trajectory table"),
            ("Katherine Johnson", "designed", "the other thing"),
    }:
        raise SystemExit(
            "two explicit coordinated clauses were not extracted independently")
    if any(item.sentence != repeated_explicit_clauses
           for item in repeated_candidates):
        raise SystemExit("coordinated candidates lost the complete source sentence")
    if kb.propose_facts("Katherine Johnson created the trajectory table.",
                        source="unseen-wording"):
        raise SystemExit("unseen relation wording was treated as a synonym")

    kb.accept_fact_candidate(candidate, index)
    written = kb.write_fact(candidate.subject, candidate.relation, candidate.object)
    if written != [sentence_c]:
        raise SystemExit(f"grounded sentence writer did not reproduce its learned frame: {written}")
    if kb.write_fact("Unverified Person", "designed", "the trajectory table"):
        raise SystemExit("writer generated a sentence for an unstored fact")
    answer = kb.ask("Who designed the trajectory table?")
    if answer.status != "answered" or answer.answer != "Katherine Johnson":
        raise SystemExit(f"accepted extracted fact did not answer the question: {answer}")
    if source_c not in (answer.evidence or [])[0]["sources"]:
        raise SystemExit("Q&A answer lost the extracted sentence citation")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_candidates = restored.propose_facts(
            "Dorothy Vaughan designed the calculation tables.",
            source="source-d")
        restored_writing = restored.write_fact(
            candidate.subject, candidate.relation, candidate.object)
    if (len(restored_candidates) != 1
            or restored_candidates[0].subject != "Dorothy Vaughan"):
        raise SystemExit(f"learned fact pattern did not persist: {restored_candidates}")
    if restored_writing != written:
        raise SystemExit(f"learned writing frames did not persist: {restored_writing}")

    print("grounded fact-pattern learning diagnostic: PASS")
    print("two-example acquisition, uncommitted extraction, abstention, source linkage, controlled writing, persistence: PASS")


if __name__ == "__main__":
    main()
