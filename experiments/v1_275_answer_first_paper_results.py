"""Check answer-first result extraction for named papers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (
    _natural_main_result_request,
    _render_main_result,
)
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _chat_command(index_path: str, root: Path) -> list[str]:
    return [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--index", index_path,
        "--knowledge", str(root / "knowledge.json"),
        "--rules", str(root / "rules.json"),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--candidate-session", str(root / "candidates.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--math-session", str(root / "math-session.json"),
        "--translation-session", str(root / "translation-session.json"),
    ]


def main() -> None:
    question = (
        "What is the main result of On the cop number of toroidal graphs?")
    require(_natural_main_result_request(question)
            == "On the cop number of toroidal graphs",
            "main-result wording did not isolate the paper title")

    index_path = (PROJECT / "data" / "crms_project_model_academic.sqlite.memories"
                  / "research.sqlite")
    require(index_path.is_file(), f"academic corpus index is missing: {index_path}")
    index = CRMSSQLiteResearchIndex.load(index_path)
    rendered, evidence = _render_main_result(
        index, _natural_main_result_request(question))
    require("We show that the cop number of toroidal graphs is at most 3."
            in rendered,
            f"named-paper result was not realized as a sentence: {rendered}")
    require("Metadata license:" not in rendered and evidence is not None,
            f"metadata leaked or result citation was not retained: {rendered}")
    require("https://arxiv.org/abs/1904.07946v3" in rendered,
            f"short source link is missing: {rendered}")
    require(index.resolve_citation(evidence["citation"])
            == "We show that the cop number of toroidal graphs is at most 3.",
            "the short answer did not retain an exact, verifiable citation")

    with tempfile.TemporaryDirectory(prefix="crms-main-result-") as folder:
        root = Path(folder)
        output = subprocess.run(
            _chat_command(str(index_path), root),
            input=question + "\nWhy?\n/quit\n", text=True, capture_output=True,
            check=True, timeout=45).stdout
        require("CRMS> We show that the cop number of toroidal graphs is at most 3."
                in output and "Metadata license:" not in output,
                f"chat did not answer the named-paper request directly: {output}")
        require("I don't have a verified language rule to paraphrase this result yet."
                in output and "On the cop number of toroidal graphs" in output,
                f"the follow-up did not retain the selected paper: {output}")

    with tempfile.TemporaryDirectory(prefix="crms-main-result-fixture-") as folder:
        fixture_path = Path(folder) / "research.sqlite"
        fixture = CRMSSQLiteResearchIndex(fixture_path)
        fixture.add_document(
            "clear", "A Clear Result",
            "Abstract: We show that the sample system uses three steps.",
            "https://example.test/clear")
        fixture.add_document(
            "unclear", "A Descriptive Paper",
            "Abstract: This paper describes a sample system with three steps.",
            "https://example.test/unclear")
        clear_text, clear_evidence = _render_main_result(
            fixture, "A Clear Result")
        require("We show that the sample system uses three steps." in clear_text
                and clear_evidence is not None,
                f"explicit result cue was not cited: {clear_text}")
        unclear_text, unclear_evidence = _render_main_result(
            fixture, "A Descriptive Paper")
        require("no clear result statement" in unclear_text
                and unclear_evidence is None,
                f"descriptive abstract was overstated as a result: {unclear_text}")
        fixture.close()

    with tempfile.TemporaryDirectory(prefix="crms-main-result-title-overlap-") as folder:
        root = Path(folder)
        fixture_path = root / "research.sqlite"
        fixture = CRMSSQLiteResearchIndex(fixture_path)
        long_title = (
            "Program Synthesis Through Reinforcement Learning Guided Tree Search")
        long_result = (
            "We evaluate the combined method and demonstrate its effectiveness.")
        fixture.add_document(
            "long-title", long_title,
            f"Title: {long_title}\nAbstract: We attempt to find a useful "
            f"program representation. {long_result}",
            "https://example.test/long-title")
        fixture.add_document(
            "short-title", "Reinforcement Learning",
            "Title: Reinforcement Learning\n"
            "Abstract: We describe a general learning approach.",
            "https://example.test/short-title")
        request = "What is the main result of " + long_title + "?"
        reference = _natural_main_result_request(request)
        require(reference == long_title,
                f"title overlap changed the requested title: {reference}")
        rendered, evidence = _render_main_result(fixture, reference)
        require(long_result in rendered and evidence is not None,
                f"the longest exact paper title was treated as ambiguous: {rendered}")

        output = subprocess.run(
            _chat_command(str(fixture_path), root),
            input=request + "\n/quit\n", text=True, capture_output=True,
            check=True, timeout=45).stdout
        require(long_result in output and "couldn't identify one paper" not in output,
                f"chat did not resolve an overlapping exact title: {output}")
        fixture.close()

    print("answer-first named-paper result diagnostic: PASS")


if __name__ == "__main__":
    main()
