"""Numbered source options can only select results actually shown to the user."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-numbered-sources-") as folder:
        root = Path(folder)
        (root / "bistro.txt").write_text(
            "Bistro Alder is an Italian restaurant that serves handmade pasta "
            "and has outdoor seating near the river.", encoding="utf-8")
        (root / "cafe.txt").write_text(
            "Cafe Birch is a French restaurant that serves pastries and has "
            "indoor seating near the river.", encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(str(root))
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        listed = dialogue.turn("List restaurants near the river.",
                               research_index=index)
        require(listed.status == "sources_found"
                and "1. Cafe Birch" in listed.text
                and "2. Bistro Alder" in listed.text,
                f"requested choices were not numbered and cited: {listed.text!r}")
        require(len(dialogue.presented_sources) == 2,
                "only the displayed citations should be selectable")
        selected_citation = dialogue.presented_sources[1]["citation"]

        state_path = root / "dialogue.json"
        dialogue.save(str(state_path))
        restored = CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path),
                                    research_index=index)
        selected = restored.turn("What about the second one?",
                                 research_index=index)
        require(selected.status == "sources_found"
                and "Bistro Alder is an Italian restaurant" in selected.text
                and "Source: bistro.txt" in selected.text
                and "Cafe Birch" not in selected.text,
                f"ordinal did not select the displayed second source: {selected.text!r}")
        require(selected.research is not None
                and selected.research.source_sentences[0]["citation"]
                == selected_citation,
                "selected source citation did not match the displayed option")
        require(not restored.knowledge.facts(),
                "quoting a selected source must not create an accepted fact")

        empty_index = CRMSResearchIndex()
        stale = CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path),
                                  research_index=empty_index)
        require(not stale.presented_sources,
                "removed source citations must not remain selectable")
        stale_choice = stale.turn("What about the second one?",
                                  research_index=empty_index)
        require(stale_choice.status != "sources_found"
                and "Bistro Alder" not in stale_choice.text,
                "a stale or hidden result was exposed after index validation")

    print("explicit source lists expose only numbered, cited results: PASS")
    print("ordinal selection survives save/load and returns the exact citation: PASS")
    print("selecting quoted evidence does not teach or accept a fact: PASS")
    print("source selections are discarded when citations fail revalidation: PASS")


if __name__ == "__main__":
    main()
