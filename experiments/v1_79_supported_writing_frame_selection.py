"""Prefer the most independently supported grounded writing frame."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def add_example(kb: CRMSKnowledgeBase, subject: str, obj: str,
                surface: str, sentence: str, source: str) -> None:
    kb.add_fact(subject, "design", obj, source)
    kb.teach_fact_pattern(
        sentence, subject=subject, relation="design", obj=obj,
        source=source, predicate_phrase=surface)


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    add_example(kb, "Ada", "Engine", "designed",
                "Ada designed the Engine.", "active-1#frag")
    add_example(kb, "Bea", "Compiler", "designed",
                "Bea designed the Compiler.", "active-2#frag")
    add_example(kb, "Ada", "Engine", "designed",
                "The Engine was designed by Ada.", "passive-1#frag")
    add_example(kb, "Bea", "Compiler", "designed",
                "The Compiler was designed by Bea.", "passive-2#frag")
    add_example(kb, "Dee", "Rotor", "designed",
                "The Rotor was designed by Dee.", "passive-3#frag")
    return kb


def main() -> None:
    kb = seed()
    alternatives = kb.write_fact("Ada", "design", "Engine")
    passive = "The Engine was designed by Ada."
    active = "Ada designed the Engine."
    if not alternatives or alternatives[0] != passive or active not in alternatives:
        raise SystemExit(f"writer did not rank the better-supported frame first: {alternatives}")

    digest = kb.write_about("Ada")
    if (digest.status != "written" or not digest.statements
            or digest.statements[0]["sentence"] != passive
            or digest.statements[0]["frame_evidence"]["document_count"] != 3
            or set(digest.statements[0]["frame_evidence"]["source_documents"])
            != {"passive-1", "passive-2", "passive-3"}
            or not all(source in digest.text for source in
                       digest.statements[0]["frame_evidence"]["sources"])
            or "The Engine was designed by Ada." not in digest.text):
        raise SystemExit(f"write_about ignored the evidence-ranked frame: {digest}")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        if restored.write_fact("Ada", "design", "Engine") != alternatives:
            raise SystemExit("writing frame ranking changed after persistence")
        restored_digest = restored.write_about("Ada")
        if (restored_digest.status != "written"
                or restored_digest.statements[0]["frame_evidence"]
                != digest.statements[0]["frame_evidence"]):
            raise SystemExit("wording-frame provenance changed after persistence")

    print("supported writing-frame selection diagnostic: PASS")
    print("distinct-document ranking, alternatives retained, digest selection, persistence: PASS")


if __name__ == "__main__":
    main()
