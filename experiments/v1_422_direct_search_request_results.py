"""Direct search requests surface only relevant, cited source excerpts."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-direct-search-") as folder:
        root = Path(folder)
        (root / "sacramento_lunch.txt").write_text(
            "At Arden Fair Mall in Sacramento, the Garden Cafe serves "
            "vegetarian lunch and sandwiches.", encoding="utf-8")
        # This shares only location words with the request and must not be
        # presented as a restaurant or lunch result.
        (root / "california_capital.txt").write_text(
            "Sacramento is the capital of California.", encoding="utf-8")
        (root / "new_york_lunch.txt").write_text(
            "The Garden Cafe in New York serves vegetarian lunch and "
            "sandwiches.", encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(str(root))
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        request = "Looking for a place to eat lunch in Sacramento, California."
        first = respond(dialogue, request, research_index=index)
        require(first.status == "sources_found"
                and first.intent_hypothesis is not None
                and first.intent_hypothesis.matched_frame
                    == "explicit-search-request",
                f"direct search did not reach source retrieval: {first}")
        require("Garden Cafe serves vegetarian lunch" in first.text
                and "Source: sacramento_lunch.txt" in first.text,
                f"the relevant source excerpt was not surfaced: {first.text!r}")
        require("Partial location match" in first.text
                and "does not state: california" in first.text.casefold(),
                "an excerpt omitting the comma-qualified region was not labelled as a partial location match")
        require("not verified recommendations" in first.text
                and "capital of California" not in first.text
                and "New York" not in first.text,
                f"unrelated or overclaimed source text was shown: {first.text!r}")
        require(len(dialogue.presented_sources) == 1,
                "only the displayed relevant source should be selectable")
        citation = dialogue.presented_sources[0]["citation"]

        explanation = respond(dialogue, "why?", research_index=index)
        require("matched terms in your search" in explanation.text
                and "verified recommendations" in explanation.text,
                f"why? did not explain the source-only result: {explanation.text!r}")

        selected = respond(dialogue, "What about the first one?",
                           research_index=index)
        require(selected.status == "sources_found"
                and selected.research is not None
                and selected.research.source_sentences
                and selected.research.source_sentences[0]["citation"] == citation,
                f"the displayed source could not be selected: {selected.text!r}")
        require(not dialogue.knowledge.facts(),
                "retrieved source text was incorrectly accepted as a fact")

        empty_target = CRMSResearchIndex()
        empty_target.add_document(
            "capital", "Sacramento facts",
            "Sacramento is the capital of California.",
            location="capital.txt")
        no_match = respond(CRMSDialogue(CRMSKnowledgeBase()), request,
                           research_index=empty_target)
        require("couldn't find a source excerpt" in no_match.text
                and "capital of California" not in no_match.text,
                f"location-only overlap was presented as a search result: {no_match.text!r}")

        options: list[str] = []
        for name in ("knowledge", "math", "rules", "dialogue-state",
                     "rule-session", "candidate-session", "math-session",
                     "translations", "translation-session"):
            options.extend(("--" + name, str(root / f"{name}.json")))
        command = [sys.executable,
                   str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
                   *options, "--feedback-db", str(root / "feedback.sqlite3"),
                   "--index", str(root / "chat-research.sqlite")]
        run = subprocess.run(
            command,
            input=(f"/source-dir {root}\n{request}\nwhy?\n"
                   "What about the first one?\n/quit\n"),
            text=True, capture_output=True, timeout=120,
            env=os.environ.copy(), check=False)
        require(run.returncode == 0,
                f"scratch chat failed ({run.returncode}): {run.stderr}\n{run.stdout}")
        require("Garden Cafe serves vegetarian lunch" in run.stdout
                and "Matching source excerpts" in run.stdout,
                f"interactive chat did not display the search result: {run.stdout!r}")
        require("capital of California" not in run.stdout
                and "New York" not in run.stdout
                and "used this quoted source sentence as evidence" in run.stdout
                and "Source text: At Arden Fair Mall" in run.stdout,
                f"interactive chat lost the search explanation or selected source: {run.stdout!r}")

    print("direct search requests reach cited source retrieval: PASS")
    print("only target-matching excerpts are presented and selectable: PASS")
    print("source matches stay unverified and why? names their status: PASS")
    print("search misses abstain instead of presenting a location-only hit: PASS")
    print("interactive chat preserves source context across why? and selection: PASS")


if __name__ == "__main__":
    main()
