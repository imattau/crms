"""Check bounded CVC final-consonant doubling in verb inflection.

Run from the project root with:
    python3 experiments/v1_78_cvc_doubling_morphology.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def teach_relation(kb: CRMSKnowledgeBase, relation: str, surface: str,
                   document_id: str) -> None:
    for number, (subject, obj) in enumerate((("Ada", "Engine"),
                                              ("Bea", "Compiler")), start=1):
        sentence = f"{subject} {surface} {obj}."
        source = f"{document_id}#fragment-{number}"
        kb.add_fact(subject, relation, obj, source)
        kb.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj,
            source=source, predicate_phrase=surface)


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach_relation(kb, "stop", "stopped", "stop-doc")
    teach_relation(kb, "plan", "planned", "plan-doc")
    teach_relation(kb, "run", "runs", "run-doc")
    teach_relation(kb, "tap", "taps", "tap-doc")
    teach_relation(kb, "walk", "walked", "walk-doc")
    teach_relation(kb, "paint", "painted", "paint-doc")
    teach_relation(kb, "clap", "clap", "clap-doc")

    candidate = next((item for item in kb.propose_facts(
        "Sage clapped Sculpture", source="review:cvc")
        if item.relation == "clap" and item.subject == "Sage"), None)
    rule = next((item for item in (candidate.language_evidence if candidate else ())
                 if item.get("kind") == "induced_suffix"), None)
    if (rule is None or rule["context"] != "cvc-double"
            or rule["suffix"] != "ed"
            or {item["relation"] for item in rule["support"]}
            != {"plan", "stop"}):
        raise SystemExit("grounded CVC examples did not license final doubling")
    if any(item.relation == "clap" and item.subject == "Sage"
           for item in kb.facts()):
        raise SystemExit("morphology proposal was committed without review")
    third_person = next((item for item in kb.propose_facts(
        "Sage claps Sculpture", source="review:third-person")
        if item.relation == "clap" and item.subject == "Sage"), None)
    if (third_person is None
            or not any(item.get("context") == "other-ending"
                       and item.get("suffix") == "s"
                       for item in third_person.language_evidence)):
        raise SystemExit("plain third-person -s failed on a CVC verb")
    if any(item.relation == "clap" for item in kb.propose_facts(
            "Sage claped Sculpture", source="review:bad-ed")):
        raise SystemExit("plain -ed overrode the licensed CVC doubling rule")

    # Two-vowel and excluded-final classes must not inherit the CVC change.
    teach_relation(kb, "open", "open", "open-doc")
    teach_relation(kb, "fix", "fix", "fix-doc")
    if any(item.relation == "open" for item in kb.propose_facts(
            "Sage openned Sculpture", source="review:open")):
        raise SystemExit("CVC rule doubled a consonant in a two-vowel word")
    if any(item.relation == "fix" for item in kb.propose_facts(
            "Sage fixxed Sculpture", source="review:fix")):
        raise SystemExit("CVC rule doubled excluded final x")

    generic_only = CRMSKnowledgeBase()
    teach_relation(generic_only, "walk", "walked", "walk-doc")
    teach_relation(generic_only, "paint", "painted", "paint-doc")
    teach_relation(generic_only, "clap", "clap", "clap-doc")
    if any(item.relation == "clap" for item in generic_only.propose_facts(
            "Sage claped Sculpture", source="review:no-cvc-evidence")):
        raise SystemExit("plain -ed guessed an unlicensed CVC spelling")

    print("CVC doubling morphology diagnostic: PASS")
    print("cross-document rule discovery, -s/-ed contrast, review-only proposal, and unlicensed CVC abstention controls: PASS")


if __name__ == "__main__":
    main()
