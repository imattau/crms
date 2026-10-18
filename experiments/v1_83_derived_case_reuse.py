"""Measure safe proof reuse and invalidation in a stable knowledge snapshot."""

from __future__ import annotations

import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    taught_only = CRMSKnowledgeBase()
    taught_only.add_fact("Ada", "designed", "Engine", "source:design")
    taught_only.practice_relation("Ada", "designed", "Engine")
    if taught_only.derived_cases():
        raise SystemExit("a taught fact was copied into derived memory")

    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "works at", "Studio", "source:employment")
    kb.add_fact("Studio", "located in", "Paris", "source:address")
    kb.add_fact("Paris", "in country", "France", "source:country")
    kb.add_inference_rule("work-location", "works at", "located in",
                          "works in")
    kb.add_inference_rule("location-country", "works in", "in country",
                          "works in country")
    if kb.practice_relation("Ada", "works in country", "France").status != "answered":
        raise SystemExit("practice did not produce a verified result")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        cached_result = restored.infer_relation(
            "Ada", "works in country", "France")
        if cached_result.status != "answered" or cached_result.expansions != 0:
            raise SystemExit("exact inference query did not reuse the practiced case")
        wider_result = restored.infer_relation(
            "Ada", "works in country", "France", max_depth=9)
        if wider_result.status != "answered" or wider_result.expansions == 0:
            raise SystemExit("cache was reused beyond the bounds it had validated")
        original_infer = restored.infer_relation
        calls = 0

        def counted_infer(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original_infer(*args, **kwargs)

        restored.infer_relation = counted_infer  # type: ignore[method-assign]
        too_shallow = restored.retrieve_derived_case(
            "Ada", "works in country", "France", max_depth=1)
        if too_shallow is not None or calls != 0:
            raise SystemExit("cache reuse bypassed the caller's proof-depth bound")
        reused = restored.retrieve_derived_case(
            "Ada", "works in country", "France")
        if reused is None or reused["status"] != "verified" or calls != 0:
            raise SystemExit("unchanged snapshot did not reuse its saved proof")

        # Any change to inference-relevant state forces a fresh, bounded search.
        restored.add_fact("Bea", "works at", "Library", "source:unrelated")
        still_valid = restored.retrieve_derived_case(
            "Ada", "works in country", "France")
        if still_valid is None or calls != 1:
            raise SystemExit("changed snapshot did not revalidate by inference")

        restored.add_negative_fact("Ada", "works in country", "France",
                                   "source:counterexample")
        conflicted = restored.retrieve_derived_case(
            "Ada", "works in country", "France")
        if conflicted is not None or calls != 2:
            raise SystemExit("new conflict was missed by snapshot invalidation")

    print("derived case reuse diagnostic: PASS")
    print("query-level proof reuse, bounds, state revalidation, conflict invalidation: PASS")


if __name__ == "__main__":
    main()
