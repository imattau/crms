"""Write and explain grounded digests for bounded named entity groups."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def build() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    examples = (
        ("Ada", "designed", "Engine", "ada-engine"),
        ("Ada", "built", "Widget", "ada-widget"),
        ("Grace", "designed", "Compiler", "grace-compiler"),
        ("Grace", "built", "Rotor", "grace-rotor"),
        ("Kai", "designed", "Bridge", "kai-bridge"),
    )
    for subject, relation, obj, source in examples:
        fact_object = f"the {obj}"
        kb.add_fact(subject, relation, fact_object, source)
        kb.teach_fact_pattern(
            f"{subject} {relation} {fact_object}.", subject=subject,
            relation=relation, obj=fact_object, source=source,
            predicate_phrase=relation)
    kb.teach_about_frame("Tell me about Ada", entity="Ada")
    kb.teach_about_frame("Tell me about Grace", entity="Grace")
    return kb


def main() -> None:
    kb = build()
    direct = kb.write_about("Ada and Grace")
    if (direct.status != "written"
            or "About Ada and Grace:" not in direct.text
            or "Ada built the Widget and designed the Engine." not in direct.text
            or "Grace built the Rotor and designed the Compiler." not in direct.text):
        raise SystemExit(f"group writing missed an entity digest: {direct}")
    for source in ("ada-engine", "ada-widget", "grace-compiler", "grace-rotor"):
        if source not in direct.text:
            raise SystemExit(f"group writing lost source evidence {source}")

    triple = kb.write_about("Ada, Grace, and Kai")
    if (triple.status != "written"
            or "About Ada, Grace, and Kai:" not in triple.text
            or "Kai designed the Bridge." not in triple.text
            or "kai-bridge" not in triple.text):
        raise SystemExit(f"three-subject group writing failed: {triple}")

    dialogue = CRMSDialogue(kb)
    request = "Tell me about Ada and Grace"
    turn = dialogue.turn(request)
    if (turn.status != "written" or turn.writing is None
            or turn.writing.subject != "Ada and Grace"
            or "grace-compiler" not in turn.text):
        raise SystemExit(f"learned about-frame did not route a subject pair: {turn}")
    why = dialogue.turn("Why?")
    if (why.writing is None or "ada-engine" not in why.text
            or "grace-rotor" not in why.text):
        raise SystemExit("group explanation did not recompute both digests")

    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory) / "dialogue.json"
        dialogue.save(str(state))
        restored = CRMSDialogue.load(kb, str(state))
        after_restart = restored.turn("Why?")
        if (after_restart.writing is None
                or "About Ada and Grace:" not in after_restart.text
                or "grace-compiler" not in after_restart.text):
            raise SystemExit("group writing context did not survive persistence")

    unknown = kb.write_about("Ada and Zoe")
    if unknown.status != "unknown" or unknown.statements:
        raise SystemExit("an unknown group member was silently omitted")

    followup = dialogue.turn("What about Grace?")
    if followup.writing is None or "Grace built the Rotor" not in followup.text:
        raise SystemExit("entity follow-up from a group digest failed")

    triple_dialogue = CRMSDialogue(kb)
    triple_turn = triple_dialogue.turn("Tell me about Ada, Grace, and Kai")
    if (triple_turn.status != "written" or triple_turn.writing is None
            or triple_turn.writing.subject != "Ada, Grace, and Kai"
            or "kai-bridge" not in triple_turn.text):
        raise SystemExit(
            f"learned about-frame did not route a three-subject group: {triple_turn}")

    print("multi-entity about-writing diagnostic: PASS")
    print("separate grounded digests, source retention, explanation refresh, persistence, unknown-member abstention, entity follow-up: PASS")


if __name__ == "__main__":
    main()
