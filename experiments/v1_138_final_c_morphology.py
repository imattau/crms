"""Learn final-c k-insertion for English -ed and -ing from aligned cases."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def teach_relation(kb: CRMSKnowledgeBase, relation: str, surface: str,
                   document: str) -> None:
    for index, (subject, obj) in enumerate((("Ada", "Engine"),
                                             ("Bea", "Compiler")), start=1):
        source = f"{document}#example-{index}"
        sentence = f"{subject} {surface} {obj}."
        kb.add_fact(subject, relation, obj, source)
        kb.teach_fact_pattern(sentence, subject=subject, relation=relation,
                              obj=obj, source=source,
                              predicate_phrase=surface)


def candidate_for(kb: CRMSKnowledgeBase, text: str, relation: str):
    return next((candidate for candidate in kb.propose_facts(
        text, source=f"review:{relation}")
        if candidate.relation == relation and candidate.subject == "Sage"), None)


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach_relation(kb, "panic", "panicked", "panic-doc")
    teach_relation(kb, "picnic", "picnicked", "picnic-doc")
    teach_relation(kb, "panic", "panicking", "panic-ing-doc")
    teach_relation(kb, "picnic", "picnicking", "picnic-ing-doc")
    teach_relation(kb, "mimic", "mimic", "mimic-a")
    teach_relation(kb, "mimic", "mimic", "mimic-b")
    teach_relation(kb, "walk", "walked", "walk-doc")
    teach_relation(kb, "paint", "painted", "paint-doc")
    teach_relation(kb, "walk", "walks", "walk-present")
    teach_relation(kb, "paint", "paints", "paint-present")

    past = candidate_for(kb, "Sage mimicked Sculpture", "mimic")
    evidence = next((item for item in (past.language_evidence if past else ())
                     if item.get("kind") == "induced_suffix"), None)
    if (past is None or evidence is None
            or evidence.get("context") != "final-c-k"
            or evidence.get("suffix") != "ed"
            or {item["relation"] for item in evidence["support"]}
            != {"panic", "picnic"}
            or any(not item["sources"] for item in evidence["support"])):
        raise SystemExit("cross-relation evidence did not license mimic → mimicked")
    if any(item.relation == "mimic" and item.subject == "Sage"
           for item in kb.facts()):
        raise SystemExit("induced past-tense candidate was committed automatically")

    progressive = candidate_for(kb, "Sage mimicking Sculpture", "mimic")
    if (progressive is None or not any(
            item.get("context") == "final-c-k" and item.get("suffix") == "ing"
            for item in progressive.language_evidence)):
        raise SystemExit("final-c k-insertion did not transfer to -ing")

    third_person = candidate_for(kb, "Sage mimics Sculpture", "mimic")
    if (third_person is None or not any(
            item.get("context") == "other-ending" and item.get("suffix") == "s"
            for item in third_person.language_evidence)):
        raise SystemExit("final-c rule interfered with ordinary -s")

    if candidate_for(kb, "Sage mimiced Sculpture", "mimic") is not None:
        raise SystemExit("generic -ed evidence overrode final-c k-insertion")

    generic_only = CRMSKnowledgeBase()
    teach_relation(generic_only, "walk", "walked", "walk-doc")
    teach_relation(generic_only, "paint", "painted", "paint-doc")
    teach_relation(generic_only, "mimic", "mimic", "mimic-a")
    teach_relation(generic_only, "mimic", "mimic", "mimic-b")
    if candidate_for(generic_only, "Sage mimicked Sculpture", "mimic") is not None:
        raise SystemExit("generic -ed evidence guessed an unsupported c-k form")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        persisted = candidate_for(
            restored, "Sage mimicked Sculpture", "mimic")
        if (persisted is None or not any(
                item.get("context") == "final-c-k"
                and item.get("suffix") == "ed"
                for item in persisted.language_evidence)):
            raise SystemExit("final-c morphology failed after persistence")

    print("final-c morphology diagnostic: PASS")
    print("independent source/predicate support, -ed/-ing transfer, ordinary -s, review-only status, persistence, generic-ending abstention: PASS")


if __name__ == "__main__":
    main()
