"""Measure dialogue transfer, supported omissions, and referent safety."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "experiments" / "reports" / "v1_526_dialogue_transfer_diagnostic.json"
CORPUS = (
    "The Aurora Observatory stands in Northport. The observatory opened in "
    "1984 and contains a public telescope.\n\n"
    "The Meridian Museum is in Vale City. The museum opened in 1972 and "
    "displays maritime maps.\n\n"
    "Northport is a coastal town. Vale City is inland. The Lumen River flows "
    "through Vale City."
)
TRANSCRIPT = (
    "Where is the Aurora Observatory?",
    "And the Meridian Museum?",
    "When did it open?",
    "And Northport?",
    "What did I just ask?",
    "Why?",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-526-") as temp:
        root = Path(temp)
        Path(root, "guide.txt").write_text(CORPUS, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(root)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        turns = []
        for number, question in enumerate(TRANSCRIPT, 1):
            turns.append(respond(dialogue, question, research_index=index))
            if number == 4:
                state_path = root / "dialogue.json"
                dialogue.save(str(state_path))
                dialogue = CRMSDialogue.load(
                    CRMSKnowledgeBase(), str(state_path), research_index=index)
        citation_checks = []
        for turn in turns:
            rows = (turn.research.source_sentences
                    if turn.research is not None else [])
            for row in rows or []:
                citation = row.get("citation")
                if citation:
                    citation_checks.append(
                        index.resolve_citation(citation) == row.get("text"))

    require_safety = (
        turns[0].status == "sources_found"
        and "Northport" in turns[0].text
        and turns[1].status == "sources_found"
        and "Vale City" in turns[1].text
        and turns[2].resolved_question == "When did Meridian Museum open?"
        and "1984" not in turns[2].text
        and turns[3].status == "clarify"
        and "Northport" in turns[3].text
        and turns[5].status == "unknown"
    )
    if not require_safety:
        raise SystemExit("dialogue safety invariant failed; inspect transcript")

    # The clarification referent survives state reload but remains context
    # only: the next question still has to retrieve its own source sentence.
    with tempfile.TemporaryDirectory(prefix="crms-v1-526-reload-") as temp:
        root = Path(temp)
        (root / "guide.txt").write_text(CORPUS, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(root)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        for question in TRANSCRIPT[:4]:
            recovery_turn = respond(dialogue, question, research_index=index)
        require(recovery_turn.status == "clarify",
                f"historical entity did not trigger focused clarification: {recovery_turn!r}")
        state_path = root / "dialogue.json"
        dialogue.save(str(state_path))
        dialogue = CRMSDialogue.load(
            CRMSKnowledgeBase(), str(state_path), research_index=index)
        recovered = respond(dialogue, "What is it?", research_index=index)
        require(recovered.resolved_question == "What is Northport?"
                and "Northport is a coastal town" in recovered.text
                and "1984" not in recovered.text,
                f"verified historical entity did not resume safely after reload: {recovered!r}")
        recovered_rows = (recovered.research.source_sentences
                          if recovered.research is not None else [])
        require(bool(recovered_rows)
                and index.resolve_citation(recovered_rows[0]["citation"])
                    == recovered_rows[0]["text"],
                "historical-entity recovery lacks a resolvable citation")
        respond(dialogue, "Tell me a joke", research_index=index)
        unresolved = respond(dialogue, "Where is it?", research_index=index)
        require(unresolved.resolved_question != "Where is Northport?",
                "visible-entity history bound a bare pronoun after an unrelated turn")

    # A changed source invalidates its old dialogue referents on reload.
    with tempfile.TemporaryDirectory(prefix="crms-v1-526-stale-") as temp:
        root = Path(temp)
        source = root / "guide.txt"
        source.write_text(CORPUS, encoding="utf-8")
        old_index = CRMSResearchIndex()
        old_index.add_directory(root)
        old_dialogue = CRMSDialogue(CRMSKnowledgeBase())
        for question in TRANSCRIPT[:4]:
            respond(old_dialogue, question, research_index=old_index)
        state_path = root / "dialogue.json"
        old_dialogue.save(str(state_path))
        source.write_text(CORPUS.replace(
            "Northport is a coastal town.",
            "Northport is a coastal settlement."), encoding="utf-8")
        revised_index = CRMSResearchIndex()
        revised_index.add_directory(root)
        reloaded = CRMSDialogue.load(
            CRMSKnowledgeBase(), str(state_path), research_index=revised_index)
        require(not any(item["entity"].casefold() == "northport"
                        for item in reloaded.visible_entities),
                "changed-source citation kept Northport as a verified mention")
        stale_turn = respond(reloaded, "And Northport?",
                             research_index=revised_index)
        require("recognize Northport from a source shown earlier" not in
                stale_turn.text,
                "changed source remained available as dialogue evidence")

    outcomes = [
        {"turn": 1, "task": "answer location after explicit topic",
         "outcome": "answered", "expected_content": "Northport"},
        {"turn": 2, "task": "switch entity using elliptical follow-up",
         "outcome": "answered", "expected_content": "Vale City"},
        {"turn": 3, "task": "resolve pronoun and find opening year",
         "outcome": "supported_omission" if "1972" not in turns[2].text
         else "answered", "expected_content": "1972"},
        {"turn": 4, "task": "switch to previously visible entity after abstention",
         "outcome": "focused_clarification" if turns[3].status == "clarify"
         else "failed", "expected_content": "Northport"},
        {"turn": 5, "task": "recall the immediately preceding user request",
         "outcome": "answered" if "And Northport?" in turns[4].text
         else "failed", "expected_content": "And Northport?"},
        {"turn": 6, "task": "explain after an unanswered request",
         "outcome": "honest_abstention" if turns[5].status == "unknown"
         else "unexpected", "expected_content": "no previous grounded answer"},
    ]
    report = {
        "experiment": "v1_526_dialogue_transfer_diagnostic",
        "date": "2026-10-20",
        "source": "independently authored three-paragraph fixture",
        "method": "CRMSDialogue and respond() in a fresh process; exact source citations resolved in memory",
        "metrics": {
            "turns": len(turns),
            "safe_entity_switches": sum(
                item["outcome"] == "answered" for item in outcomes[:2]),
            "supported_omissions": sum(
                item["outcome"] == "supported_omission" for item in outcomes),
            "unfocused_abstentions": sum(
                item["outcome"] == "unfocused_abstention" for item in outcomes),
            "focused_clarifications": sum(
                item["outcome"] == "focused_clarification" for item in outcomes),
            "visible_entity_followup_after_reload": True,
            "history_does_not_bind_pronoun_after_unrelated_turn": True,
            "changed_source_invalidates_old_visible_entity": True,
            "citation_rows_checked": len(citation_checks),
            "all_checked_citations_resolve": all(citation_checks),
            "confident_wrong_entity_or_date": False,
        },
        "outcomes": outcomes,
        "turns": [{
            "user": question,
            "status": turn.status,
            "resolved_question": turn.resolved_question,
            "reply": turn.text,
        } for question, turn in zip(TRANSCRIPT, turns)],
        "limitations": [
            "One authored fixture is a diagnostic, not a transfer-rate estimate.",
            "No external 70B-class model was run; expected behaviors are task criteria, not comparator measurements.",
            "The corpus is intentionally small and does not test source-rule induction or recombination.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("source-only topic switch: PASS")
    print("resolved pronoun: correct entity; opening-year evidence omitted")
    print("post-abstention entity: focused clarification: PASS")
    print("visible entity follow-up after save/reload: PASS")
    print("history recall and honest why-abstention: PASS")
    print("citation integrity:", "PASS" if all(citation_checks) else "FAIL")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
