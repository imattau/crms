"""Validate extractive source summaries and their natural-language CLI route."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    mars = (
        "Mars Pathfinder landed on Mars in 1997. "
        "The mission used the Sojourner rover to study rocks. "
        "It sent data to Earth."
    )
    moon = "Apollo 11 landed on the Moon in 1969. Neil Armstrong walked on the Moon."
    index.add_document("mars", "Mars Pathfinder", mars, "book:mars")
    index.add_document("apollo", "Apollo 11", moon, "book:apollo")
    source_snapshot = index.documents()

    summary = index.summarize("Mars rover mission", limit=5)
    require(index.documents() == source_snapshot,
            "summary generation mutated the source index")
    require(summary.sentences, "extractive summary returned no source sentences")
    require(any("Sojourner rover" in item.text for item in summary.sentences),
            "summary omitted the best matching source sentence")
    for item in summary.sentences:
        require(item.text in mars or item.text in moon,
                "summary sentence was paraphrased or not present in a source")
        require(index.resolve_citation(item.citation) == item.text,
                "summary citation did not resolve to the exact sentence")
    require("wording is unchanged" in summary.render(),
            "summary did not identify its extractive nature")
    with tempfile.TemporaryDirectory(prefix="crms-summary-persist-") as directory:
        path = Path(directory) / "index.json"
        index.save(path)
        restored = CRMSResearchIndex.load(path)
        restored_summary = restored.summarize("Mars rover mission", limit=5)
        require(restored_summary == summary,
                "summary content or citations changed after index reload")
    unknown = index.summarize("quantum neutrino telescope", limit=3)
    require(not unknown.sentences,
            "summary selected source text without a query-term match")

    coverage = CRMSResearchIndex()
    coverage_text = (
        "Mars rover details repeated. Mars rover observations continued. "
        "The mission ended safely.")
    coverage.add_document("coverage", "Mars mission notes", coverage_text)
    coverage_summary = coverage.summarize(
        "Mars rover mission", limit=2, per_document=2)
    covered_terms = {term for sentence in coverage_summary.sentences
                     for term in sentence.matched_terms}
    require(covered_terms == {"mars", "rover", "mission"}
            and any("mission ended" in sentence.text
                    for sentence in coverage_summary.sentences),
            "summary repeated already-covered terms instead of covering the query")
    for item in coverage_summary.sentences:
        require(coverage.resolve_citation(item.citation) == item.text,
                "coverage selection changed or detached an exact citation")

    alias_index = CRMSResearchIndex()
    alias_index.add_document(
        "canonical", "Design record",
        "Ada Lovelace designed the Analytical Engine.", "sources/design.txt")
    alias_index.add_document(
        "terminology", "Terminology note",
        "The Analytical Engine is also called chronometer.",
        "sources/terms.txt")
    alias_hit = alias_index.search("chronometer", limit=1)[0]
    alias_knowledge = CRMSKnowledgeBase()
    alias_knowledge.add_fact(
        "Ada Lovelace", "designed", "the Analytical Engine",
        "sources/design.txt")
    alias_knowledge.teach_entity_alias_from_hit(
        "chronometer", "the Analytical Engine",
        research_index=alias_index, hit=alias_hit)
    licensed_research = alias_knowledge.research(
        "chronometer", CRMSResearchIndex(), limit=1)
    licenses = tuple({
        "kind": row["kind"], "evidence": row["evidence"],
        "text": row["text"], "sources": row["sources"],
        "rules": row["rules"],
    } for row in licensed_research.query_expansions or [])
    require(any(item["kind"] == "entity_alias" for item in licenses),
            "research did not retain the alias license for summary routing")
    expanded_summary = alias_index.summarize(
        "chronometer", retrieval_terms=(item["text"] for item in licenses),
        expansion_licenses=licenses)
    require(any("Ada Lovelace designed" in item.text
                for item in expanded_summary.sentences)
            and any("chronometer" in item.text
                    for item in alias_index.summarize("chronometer").sentences),
            "licensed alias did not expand source summary retrieval")
    require(any("entity_alias: chronometer → the Analytical Engine" in line
                for line in expanded_summary.render().splitlines())
            and any(source.startswith("terminology#")
                    for license_row in expanded_summary.expansion_licenses
                    for source in license_row["sources"]),
            "expanded summary hid the alias relation or its source lineage:\n"
            + expanded_summary.render())

    revised_index = CRMSResearchIndex()
    revised_index.add_document("revision", "Field report",
                               "The rover transmitted a clear signal.")
    old_summary = revised_index.summarize("rover signal")
    old_citation = old_summary.sentences[0].citation
    revised_text = "The rover transmitted a weak signal after repairs."
    revised_index.add_document("revision", "Field report", revised_text,
                               replace=True)
    try:
        revised_index.resolve_citation(old_citation)
    except ValueError:
        pass
    else:
        raise SystemExit("stale summary citation survived source replacement")
    revised_summary = revised_index.summarize("rover signal")
    require(revised_summary.sentences
            and revised_index.resolve_citation(
                revised_summary.sentences[0].citation)
            == revised_summary.sentences[0].text
            and "weak signal" in revised_summary.sentences[0].text,
            "new summary did not cite the revised source text")

    measurement = CRMSResearchIndex()
    measurement_text = (
        "Instrument measured 3.14 units in Mars soil. Calibration remained stable.")
    measurement.add_document("measurement", "Instrument report", measurement_text)
    decimal_summary = measurement.summarize("3.14 units")
    require(decimal_summary.sentences
            and decimal_summary.sentences[0].text
            == "Instrument measured 3.14 units in Mars soil."
            and measurement.resolve_citation(
                decimal_summary.sentences[0].citation)
            == decimal_summary.sentences[0].text,
            "decimal punctuation split an extractive sentence or its citation")

    paginated = CRMSResearchIndex()
    pages = ("Page one contains an unrelated introduction.",
             "Mars mission ended after the rover sent its final signal.")
    paginated.add_document("report", "Mission report", "\n\f\n".join(pages),
                           "report.pdf", pages=pages)
    page_summary = paginated.summarize("Mars mission final signal")
    require(len(page_summary.sentences) == 1
            and page_summary.sentences[0].page_number == 2
            and paginated.resolve_citation(page_summary.sentences[0].citation)
            == page_summary.sentences[0].text,
            "extractive summary lost exact PDF page citation")

    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="crms-summary-") as directory:
        root = Path(directory)
        source_path = root / "mars.txt"
        source_path.write_text(mars, encoding="utf-8")
        terminal_index = CRMSResearchIndex()
        terminal_index.add_document(
            "mars-extra-1", "Mars rover notes",
            "The Mars rover mission collected soil samples. "
            "A second Mars rover mission mapped the valley.",
            "book:mars-extra-1")
        terminal_index.add_document(
            "mars-extra-2", "Mars expedition report",
            "Mars rover teams examined the landing site. "
            "The Mars mission returned new geological data.",
            "book:mars-extra-2")
        terminal_index.save(root / "index.json")
        command = [sys.executable, str(project / "crms_chat.py"),
                   "--knowledge", str(root / "knowledge.json"),
                   "--index", str(root / "index.json"),
                   "--dialogue-state", str(root / "dialogue.json")]
        run = subprocess.run(
            command,
            input=(f"/source {source_path}\n"
                   "Could you please summarize the Mars rover mission?\n"
                   "Summarize the Mars rover mission.\n"
                   "Show only the first two sentences\nShow more sentences\n"
                   "Show fewer sentences\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=30)
        require(run.returncode == 0
                and "Extractive summary for: the Mars rover mission" in run.stdout
                and "The mission used the Sojourner rover to study rocks." in run.stdout
                and "sha256=" in run.stdout,
                f"natural-language summary route failed:\n{run.stdout}\n{run.stderr}")
        summary_blocks = run.stdout.split("CRMS> Extractive summary for:")[1:]
        summary_counts = [block.split("\nyou> ", 1)[0].count("\n- ")
                          for block in summary_blocks]
        require(summary_counts[:5] == [5, 5, 2, 4, 3],
                f"summary count follow-ups did not re-run source selection: {summary_counts}")

        alias_knowledge_path = root / "alias-knowledge.json"
        alias_index_path = root / "alias-index.json"
        alias_knowledge.save(alias_knowledge_path)
        alias_index.save(alias_index_path)
        alias_cli = subprocess.run(
            [sys.executable, str(project / "crms_chat.py"),
             "--knowledge", str(alias_knowledge_path),
             "--index", str(alias_index_path),
             "--dialogue-state", str(root / "alias-dialogue.json"),
             "--rules", str(root / "alias-rules.json")],
            input="Summarize chronometer.\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=30)
        require(alias_cli.returncode == 0
                and "Ada Lovelace designed the Analytical Engine." in alias_cli.stdout
                and "entity_alias: chronometer → the Analytical Engine" in alias_cli.stdout
                and "terminology#sha256=" in alias_cli.stdout,
                "natural-language summary ignored its licensed alias expansion:\n"
                + alias_cli.stdout + alias_cli.stderr)
    print("extractive research summary diagnostic: PASS")
    print("source-exact wording, citations, query-term coverage, expansion availability without passage hits, licensed alias lineage, no-match abstention, persistence, CLI routing: PASS")


if __name__ == "__main__":
    main()
