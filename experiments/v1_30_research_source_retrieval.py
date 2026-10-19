"""Check deterministic lexical research retrieval and exact source spans.

Run from the project root with:
    python3 experiments/v1_30_research_source_retrieval.py
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_research import CRMSSQLiteResearchIndex, CRMSResearchIndex
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

    with tempfile.TemporaryDirectory(prefix="crms-readonly-index-") as directory:
        folder = Path(directory)
        database = folder / "model-research.sqlite"
        writable = CRMSSQLiteResearchIndex(database)
        writable.add_document(
            "source", "Portable model source",
            "A reviewed fact can be retrieved without changing the model.",
            "portable-source.txt")
        writable.add_document(
            "tavor", "Tavor Engine",
            "Mira Sol designed Tavor Engine.", "tavor.txt")
        writable.close()
        before = database.stat()
        readonly = CRMSSQLiteResearchIndex(database, read_only=True)
        readonly_hits = readonly.search("reviewed fact retrieve model", limit=1)
        if (not readonly_hits
                or readonly_hits[0].document_id != "source"
                or readonly.resolve_citation(
                    readonly.citation(readonly_hits[0]))
                    != readonly_hits[0].snippet):
            raise SystemExit("read-only model index lost retrieval or citations")
        try:
            readonly.add_document("blocked", "Blocked", "Must not be stored.")
        except sqlite3.OperationalError:
            pass
        else:
            raise SystemExit("read-only model index accepted a write")
        readonly.close()

        # Exercise the actual chat runtime against the same source database.
        # All three source-ingestion commands must be rejected before they
        # touch local files or attempt network access.
        corpus = folder / "new-corpus"
        corpus.mkdir()
        (corpus / "new.txt").write_text(
            "This document must not be added.", encoding="utf-8")
        local_source = folder / "local-source.txt"
        local_source.write_text("This file must not be added.", encoding="utf-8")
        knowledge_path = folder / "knowledge.json"
        chat = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--knowledge", str(knowledge_path),
             "--index", str(database), "--index-read-only",
             "--dialogue-state", str(folder / "dialogue.json"),
             "--rules", str(folder / "rules.json"),
             "--math", str(folder / "math.json"),
             "--translations", str(folder / "translations.json")],
            input=(f"/source-dir {corpus}\n/source {local_source}\n"
                   "/crawl https://example.invalid|1|0\n"
                   "Who designed Tavor Engine?\n/quit\n"),
            text=True, capture_output=True, cwd=folder, timeout=30)
        if (chat.returncode != 0
                or chat.stdout.count("research index is read-only") != 3
                or "Mira Sol designed Tavor Engine." not in chat.stdout):
            raise SystemExit(
                "read-only chat did not block ingestion or answer from the "
                f"existing source text:\n{chat.stdout}\n{chat.stderr}")
        after = database.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise SystemExit("read-only model query modified its SQLite database")

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
