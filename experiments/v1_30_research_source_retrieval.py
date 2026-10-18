"""Check deterministic lexical research retrieval and exact source spans.

Run from the project root with:
    python3 experiments/v1_30_research_source_retrieval.py
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_research import CRMSResearchIndex
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document(
        "manual", "CRMS Rule Learning",
        "CRMS learns grounded rules from examples. A contrastive probe can "
        "separate candidate procedures. CRMS also separates ambiguous "
        "hypotheses. Each evidence citation should point to an exact source "
        "offset.",
        "docs/crms-manual.txt",
    )
    index.add_document(
        "botany", "Field Notes",
        "Roots absorb water. Leaves use light. Flowers produce seeds.",
        "notes/botany.txt",
    )
    index.add_document(
        "orchid", "Orchid Monograph",
        "A botanical reference covering greenhouse conditions and cultivation.",
        "docs/orchid-reference.txt",
    )

    title_hit = index.search("Orchid Monograph", limit=1)
    if (not title_hit or title_hit[0].document_id != "orchid"
            or not {"orchid", "monograph"} <= set(title_hit[0].matched_terms)):
        raise SystemExit(f"title-only query did not retrieve its source: {title_hit}")
    title_citation = index.citation(title_hit[0])
    if index.resolve_citation(title_citation) != title_hit[0].snippet:
        raise SystemExit("title-only result did not retain an exact body citation")

    hits = index.search("contrastive probe candidate procedures", limit=3)
    if not hits or hits[0].document_id != "manual":
        raise SystemExit(f"relevant source was not ranked first: {hits}")
    if not all(hit.snippet == index._documents[hit.document_id].text[hit.start:hit.end]
               for hit in hits):
        raise SystemExit("a returned excerpt did not match its exact source offsets")
    if not set(hits[0].matched_terms) >= {"contrastive", "probe", "candidate", "procedures"}:
        raise SystemExit(f"matched-term trace is incomplete: {hits[0]}")
    citation = index.citation(hits[0])
    if index.resolve_citation(citation) != hits[0].snippet:
        raise SystemExit("citation did not resolve to the exact retrieved excerpt")
    knowledge = CRMSKnowledgeBase()
    fact = knowledge.add_fact_from_hit(
        "CRMS", "separates", "candidate procedures", index, hits[0])
    if citation not in fact.sources:
        raise SystemExit(f"fact did not retain its verified source citation: {fact}")
    second_hit = index.search("CRMS ambiguous hypotheses", limit=1)[0]
    second_citation = index.citation(second_hit)
    knowledge.add_fact_from_hit(
        "CRMS", "separates", "ambiguous hypotheses", index, second_hit)
    knowledge.teach_question(
        "What separates candidate procedures?", relation="separates",
        answer_field="subject", bound_entity="candidate procedures", answer="CRMS")
    licensed = knowledge.teach_question(
        "What separates ambiguous hypotheses?", relation="separates",
        answer_field="subject", bound_entity="ambiguous hypotheses", answer="CRMS")
    if not licensed:
        raise SystemExit("source-backed question frame was not learned")
    response, response_text = knowledge.respond("What separates ambiguous hypotheses?")
    if (response.status != "answered" or response.answer != "CRMS"
            or second_citation not in response_text):
        raise SystemExit(f"source retrieval did not ground the Q&A response: {response_text}")
    tampered = replace(hits[0], snippet=hits[0].snippet + " altered")
    try:
        index.citation(tampered)
    except ValueError:
        pass
    else:
        raise SystemExit("tampered source excerpt was accepted as a citation")
    if index.search("quantum telescope nonexistent"):
        raise SystemExit("unmatched query returned an unsupported source")
    if index.search("contrastive probe") != index.search("contrastive probe"):
        raise SystemExit("retrieval order or scores are nondeterministic")

    rendered = index.render_hits("contrastive probe", hits[:1])
    if ("manual" not in rendered or "docs/crms-manual.txt" not in rendered
            or hits[0].snippet not in rendered):
        raise SystemExit(f"rendered citation omitted source details: {rendered}")
    try:
        index.add_document("manual", "Replacement", "Changed text")
    except ValueError:
        pass
    else:
        raise SystemExit("duplicate document id was silently overwritten")

    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        source_file = folder / "source.txt"
        source_file.write_text("A local source has a verifiable passage.", encoding="utf-8")
        index.add_file(source_file, document_id="local", title="Local Source")
        saved = folder / "index.json"
        index.save(saved)
        restored = CRMSResearchIndex.load(saved)
        loaded = restored.search("verifiable passage", limit=1)
    if (not loaded or loaded[0].document_id != "local"
            or loaded[0].snippet != "A local source has a verifiable passage."):
        raise SystemExit(f"file ingestion or persistence failed: {loaded}")

    index.add_document("manual", "Replacement", "Updated content only.",
                       replace=True)
    if index.search("contrastive candidate procedures"):
        raise SystemExit("replacement left stale terms in the retrieval index")
    if index.search("CRMS Rule Learning"):
        raise SystemExit("replacement left stale title terms in the retrieval index")
    try:
        index.resolve_citation(citation)
    except ValueError:
        pass
    else:
        raise SystemExit("citation to replaced source revision was not rejected")

    print("research source retrieval diagnostic: PASS")
    print("lexical ranking, exact spans, deterministic abstention, citations, file ingestion, persistence: PASS")


if __name__ == "__main__":
    main()
