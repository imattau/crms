"""Check source-scoped paper questions and structured summaries at corpus scale."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (
    _file_sha256, _paper_scoped_summary_hit, _render_main_result,
    _render_paper_authors,
)
from crms_package import install_model_database
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    source_model = PROJECT / "data" / "crms_project_model_academic_expanded.sqlite"
    require(source_model.is_file(), f"large portable model is missing: {source_model}")

    with tempfile.TemporaryDirectory(prefix="crms-quoted-paper-title-") as folder:
        root = Path(folder)
        memory_dir = root / "source.memories"
        install_model_database(source_model, memory_dir)
        model = root / source_model.name
        shutil.copy2(source_model, model)
        model_sidecar = model.with_name(model.name + ".memories")
        shutil.copytree(memory_dir, model_sidecar)
        (model_sidecar / ".model.sha256").write_text(
            _file_sha256(model) + "\n", encoding="ascii")

        title = "Cross-domain signal grammars of transcription termination"
        body = (
            f"Title: {title}\n"
            "Authors: Ada Example, Bo Example\n"
            "Abstract: We compare termination signals across three domains. "
            "We demonstrate that the signal grammars share an ordered core "
            "while using domain-specific mechanisms.\n\n"
            "The analysis distinguishes sequence signals, RNA structure, "
            "and processing-coupled termination.\n\n"
            "Fig. 1\nFigure legend: The signal grammar caption should not "
            "be attached to a table answer.\n\n"
            "Table 1\nSignal grammar comparison\n"
            "| Domain | Shared signal grammar |\n"
            "| Bacteria | cross-domain signal grammar |\n\n"
            "Table 2\nOther signal grammar comparison\n"
            "| Domain | Shared signal grammar |\n"
            "| Eukaryotes | cross-domain signal grammar alternative |"
        )
        index = CRMSSQLiteResearchIndex(model_sidecar / "research.sqlite")
        index.add_document("fixture:target", title, body,
                           "https://example.test/target-paper")
        # This decoy shares most of the query vocabulary. Exact title lookup
        # must still select the one paper whose full title was quoted.
        index.add_document(
            "fixture:decoy", "Cross-domain signal grammars in transcription",
            "A decoy summary sentence that must not appear in the answer.",
            "https://example.test/decoy-paper")
        review_result = (
            "It examines bacterial intrinsic and Rho-dependent termination, "
            "archaeal routes, and specialized RNAPII pathways, showing how "
            "shared kinetic constraints are met by divergent molecular "
            "solutions shaped by cellular organization.")
        index.add_document(
            "fixture:review", "Domain-specific termination review",
            "Title: Domain-specific termination review\n"
            "Authors: Casey Reviewer\n"
            "Abstract: " + review_result,
            "https://example.test/review")
        count = index.document_count()
        require(count >= 2_936,
                f"large-corpus fixture gate failed: only {count} documents")
        for query in (title, f"'{title}'", f'"{title}"'):
            hit = _paper_scoped_summary_hit(index, query)
            require(hit is not None and hit.document_id == "fixture:target",
                    f"title lookup failed for {query!r}: {hit}")
        authors_text, authors_evidence = _render_paper_authors(
            index, f"'{title}'")
        require("Authors: Ada Example, Bo Example" in authors_text
                and authors_evidence is not None
                and "chars=" in authors_evidence["citation"],
                f"author field lookup did not return a cited answer: {authors_text}")
        target_hit = _paper_scoped_summary_hit(index, f"'{title}'")
        general_summary = index.summarize(
            f"'{title}'", precomputed_hits=[target_hit])
        require(general_summary.sentences
                and all("|" not in sentence.text
                        for sentence in general_summary.sentences),
                "table rows crowded a general paper summary")
        table_query = "What does Table 1 say about signal grammar?"
        table_hits = [hit for hit in index.search(table_query, limit=50)
                      if hit.document_id == "fixture:target"]
        table_summary = index.summarize(table_query, precomputed_hits=table_hits)
        require(any("|" in sentence.text for sentence in table_summary.sentences),
                "explicit table question could not retrieve structured rows")
        require(all(sentence.context_kind == "table"
                    for sentence in table_summary.sentences),
                "a table answer included non-table source prose")
        require(all("Table 2" not in sentence.text
                    for sentence in table_summary.sentences),
                "a numbered table request returned a different table")
        require(all("Figure legend" not in sentence.text
                    for sentence in table_summary.sentences),
                "a figure caption leaked into the explicit table answer")
        table_render = table_summary.render()
        require("| --- |" in table_render
                and "cross-domain signal grammar" in table_render
                and all(sentence.context_kind == "table"
                        for sentence in table_summary.sentences
                        if "|" in sentence.text),
                f"table answer was not realized as a labeled Markdown table: {table_render}")
        figure_query = "What does Figure 1 show?"
        figure_hits = [hit for hit in index.search(figure_query, limit=50)
                       if hit.document_id == "fixture:target"]
        figure_summary = index.summarize(
            figure_query, precomputed_hits=figure_hits)
        require(any("Figure legend" in sentence.text
                    for sentence in figure_summary.sentences),
                "explicit figure request could not retrieve its caption")
        result_text, result_evidence = _render_main_result(
            index, "'Domain-specific termination review'")
        require(review_result in result_text and result_evidence is not None,
                f"review-style abstract result was not extracted verbatim: {result_text}")
        index.close()

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(model),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
            "--math-session", str(root / "math.json"),
            "--translation-session", str(root / "translations.json"),
        ]
        run = subprocess.run(
            command,
            input=(f"Summarize '{title}'\n"
                   f"Summarize Table 1 in '{title}'\n"
                   f"Who are the authors of '{title}'?\n"
                   f"What is the main result of '{title}'?\n"
                   "What is the main result of 'Domain-specific termination review'?\n"
                   "/quit\n"),
            text=True, capture_output=True, check=True, timeout=90)
        output = run.stdout
        require(output.count("[Cross-domain signal grammars of transcription termination") >= 1
                and "decoy summary sentence" not in output,
                f"quoted summary escaped the exact-title scope: {output}")
        require("| Domain | Shared signal grammar |" in output
                and "| --- | --- |" in output
                and "Figure legend" not in output,
                f"chat did not realize the explicit table request cleanly: {output}")
        require("We demonstrate that the signal grammars share an ordered core" in output
                and "Source: [Cross-domain signal grammars of transcription termination]"
                in output,
                f"quoted main-result request did not retrieve the target abstract: {output}")
        require(review_result in output,
                f"review-style result realization failed in chat: {output}")
        require("Authors: Ada Example, Bo Example [Source: " + title + "]"
                in output,
                f"natural-language author lookup did not realize the indexed field: {output}")
        require("License:" not in output and "Creative Commons" not in output,
                f"generated license metadata leaked into a paper answer: {output}")
        require("Loaded portable learned model:" in output,
                f"chat did not load the temporary portable model: {output}")

    print("large-corpus paper questions and structured summaries: PASS")


if __name__ == "__main__":
    main()
