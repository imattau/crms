"""Dialogue referents must come from source text the user actually saw."""

from __future__ import annotations

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
    with tempfile.TemporaryDirectory(prefix="crms-visible-referents-") as folder:
        root = Path(folder)
        (root / "bistro.txt").write_text(
            "Bistro Alder serves handmade pasta and has outdoor seating near the river.",
            encoding="utf-8")
        (root / "cafe.txt").write_text(
            "Cafe Birch serves pastries and has indoor seating near the river.",
            encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(str(root))
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        first = respond(dialogue, "Find me a restaurant near the river.",
                        research_index=index)
        require(first.status == "sources_found"
                and "Cafe Birch serves pastries" in first.text,
                f"controlled setup did not quote the expected first result: {first.text!r}")
        mentions = {item["entity"] for item in dialogue.source_mentions}
        require("Cafe Birch" in mentions,
                f"visible source entity was not retained: {mentions}")
        require("Bistro Alder" not in mentions,
                f"an unshown source became a referent: {mentions}")

        for query in ("What about the second one?",
                      "Tell me about the second one.",
                      "Can you tell me more about the other option?"):
            ordinal = respond(dialogue, query, research_index=index)
            require(ordinal.status == "clarify"
                    and "one source item" in ordinal.text
                    and "numbered list" in ordinal.text,
                    f"an ordinal for an unshown result was not clarified: {ordinal.text!r}")
            require("Bistro Alder" not in ordinal.text,
                    f"clarification leaked an unshown result: {ordinal.text!r}")

        follow_up = respond(dialogue, "Can you tell me more about that one?",
                            research_index=index)
        require(follow_up.status == "sources_found"
                and "Cafe Birch serves pastries" in follow_up.text,
                f"visible source follow-up did not resolve to Cafe Birch: {follow_up.text!r}")
        require("Which entity do you mean?" not in follow_up.text,
                f"one visible referent incorrectly caused ambiguity: {follow_up.text!r}")

    print("only the source entity quoted to the user becomes a referent: PASS")
    print("an ordinal cannot select an unshown source result: PASS")
    print("a source-backed demonstrative follow-up resolves to the visible entity: PASS")


if __name__ == "__main__":
    main()
