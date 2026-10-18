"""Check source-specific fact correction and derived-proof invalidation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "works at", "Studio", "source:employment")
    kb.add_fact("Studio", "located in", "Paris", "source:address")
    kb.add_fact("Paris", "in country", "France", "source:old-country")
    kb.add_fact("Paris", "in country", "France", "source:corroboration")
    kb.add_inference_rule("work-location", "works at", "located in",
                          "works in")
    kb.add_inference_rule("location-country", "works in", "in country",
                          "works in country")

    if kb.practice_relation("Ada", "works in country", "France").status != "answered":
        raise SystemExit("could not practice the initially supported conclusion")

    if not kb.remove_fact("Paris", "in country", "France", "source:old-country"):
        raise SystemExit("could not retract the corrected source")
    still_supported = kb.retrieve_derived_case(
        "Ada", "works in country", "France")
    if still_supported is None:
        raise SystemExit("removing one citation invalidated independent support")
    if still_supported["lineage"]["sources"] != [
            "source:address", "source:corroboration", "source:employment"]:
        raise SystemExit("revalidated lineage retained the retracted citation")

    if not kb.remove_fact("Paris", "in country", "France", "source:corroboration"):
        raise SystemExit("could not retract the remaining outdated support")
    if kb.retrieve_derived_case("Ada", "works in country", "France") is not None:
        raise SystemExit("old conclusion remained available after correction")
    if kb.remove_fact("Paris", "in country", "France", "source:corroboration"):
        raise SystemExit("retracting an absent source unexpectedly changed evidence")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        if restored.retrieve_derived_case(
                "Ada", "works in country", "France") is not None:
            raise SystemExit("removed conclusion returned after persistence")
        kb = restored

    kb.add_fact("Paris", "in country", "Spain", "source:corrected-country")
    if kb.practice_relation("Ada", "works in country", "Spain").status != "answered":
        raise SystemExit("corrected source did not support a new derivation")
    if kb.retrieve_derived_case("Ada", "works in country", "Spain") is None:
        raise SystemExit("newly practiced corrected conclusion was not reusable")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        if restored.retrieve_derived_case(
                "Ada", "works in country", "Spain") is None:
            raise SystemExit("corrected derivation did not survive persistence")

    kb.add_negative_fact("Ada", "works in country", "France", "source:neg")
    if not kb.remove_negative_fact(
            "Ada", "works in country", "France", "source:neg"):
        raise SystemExit("could not retract an explicit negative fact")
    if kb.negative_facts():
        raise SystemExit("negative source support remained after retraction")

    print("corrected fact revalidation diagnostic: PASS")
    print("source-level support, stale derivation abstention, corrected practice and reuse: PASS")


if __name__ == "__main__":
    main()
