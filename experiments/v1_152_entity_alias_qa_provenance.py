"""Expose cited entity-alias evidence in fact-backed question answers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for subject, obj, source in (("Ada", "the Engine", "source:engine"),
                                 ("Bea", "the Compiler", "source:compiler")):
        kb.add_fact(subject, "designed", obj, source)
        kb.teach_question(f"Who designed {obj}?", relation="designed",
                          answer_field="subject", bound_entity=obj,
                          answer=subject)
    return kb


def main() -> None:
    kb = seed()
    question = "Who designed the Engines?"
    unsupported = kb.ask(question)
    if unsupported.status != "unknown":
        raise SystemExit("an unlicensed plural entity mention was canonicalized")

    kb.teach_entity_alias(
        "the Engines", "the Engine", source="teacher:confirmed-reference")
    answer = kb.ask(question)
    if answer.status != "answered" or answer.answer != "Ada":
        raise SystemExit(f"explicitly taught entity alias did not answer: {answer}")
    alias_evidence = next((item for item in answer.language_evidence or []
                           if item.get("kind") == "entity_alias"), None)
    if (alias_evidence is None or alias_evidence.get("alias") != "the engines"
            or alias_evidence.get("entity") != "the Engine"
            or alias_evidence.get("sources") != ["teacher:confirmed-reference"]):
        raise SystemExit(f"QA omitted alias provenance: {answer.language_evidence}")
    rendered = kb.render(answer)
    if "Entity alias: the engines → the Engine" not in rendered:
        raise SystemExit(f"answer renderer omitted alias evidence: {rendered}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        persisted = restored.ask(question)
        if (persisted.status != "answered" or persisted.answer != "Ada"
                or alias_evidence not in (persisted.language_evidence or [])):
            raise SystemExit(f"alias evidence changed after reload: {persisted}")

    qualified = CRMSKnowledgeBase()
    for subject, obj, year in (("Ada", "the Engine", "2020"),
                               ("Bea", "the Compiler", "2021")):
        qualified.add_fact(subject, "designed", obj, f"source:{year}",
                           qualifiers={"year": year})
        qualified.teach_qualified_question(
            f"Who designed {obj} in {year}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject,
            qualifier={"year": year})
    qualified.teach_entity_alias(
        "the Engines", "the Engine", source="teacher:qualified-reference")
    qualified_answer = qualified.ask("Who designed the Engines in 2020?")
    if (qualified_answer.status != "answered" or qualified_answer.answer != "Ada"
            or not any(item.get("kind") == "entity_alias"
                       and item.get("sources") == ["teacher:qualified-reference"]
                       for item in qualified_answer.language_evidence or [])):
        raise SystemExit(f"qualified QA omitted alias provenance: {qualified_answer}")

    collision = seed()
    collision.add_fact("Nia", "owns", "the Engines", "source:plural-object")
    try:
        collision.teach_entity_alias(
            "the Engines", "the Engine", source="teacher:ambiguous")
    except ValueError:
        pass
    else:
        raise SystemExit("alias teaching overrode an independently stored entity")

    print("entity alias QA provenance diagnostic: PASS")
    print("unlicensed plural abstention, explicit alias transfer, visible source, "
          "persistence, and entity-collision rejection: PASS")


if __name__ == "__main__":
    main()
