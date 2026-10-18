"""Check symbolic support classes for distinct verified rule-proof lineages."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("A", "owns", "B", "doc-1")
    kb.add_fact("B", "part of", "C", "doc-2")
    kb.add_fact("A", "owns", "D", "doc-3")
    kb.add_fact("D", "part of", "C", "doc-4")
    kb.add_inference_rule("ownership-part", "owns", "part of", "contains")

    result = kb.infer_relation("A", "contains", "C")
    require(result.status == "answered" and result.complete,
            "two-lineage query did not return a complete supported result")
    require(result.lineage_count == 2 and result.support_class == "redundant",
            f"distinct proof lineages were not classified as redundant: {result}")
    require(result.source_count == 4 and result.source_documents ==
            ("doc-1", "doc-2", "doc-3", "doc-4"),
            f"distinct leaf sources were counted incorrectly: {result}")

    unique = CRMSKnowledgeBase()
    unique.add_fact("X", "owns", "Y", "doc-a")
    unique.add_fact("Y", "part of", "Z", "doc-b")
    unique.add_inference_rule("ownership-part", "owns", "part of", "contains")
    one = unique.infer_relation("X", "contains", "Z")
    require(one.support_class == "unique" and one.lineage_count == 1
            and one.source_count == 2, f"single lineage was misclassified: {one}")
    unique.add_negative_fact("X", "contains", "Z", "counter-doc")
    contested = unique.infer_relation("X", "contains", "Z")
    require(contested.status == "ambiguous" and contested.support_class == "contested"
            and contested.lineage_count == 1 and contested.source_count == 2,
            f"contradiction did not take precedence over support count: {contested}")

    practiced_kb = CRMSKnowledgeBase()
    practiced_kb.add_fact("M", "owns", "N", "doc-mn")
    practiced_kb.add_fact("N", "part of", "O", "doc-no")
    practiced_kb.add_inference_rule("ownership-part", "owns", "part of", "contains")
    practiced = practiced_kb.practice_relation("M", "contains", "O")
    reused = practiced_kb.infer_relation("M", "contains", "O")
    require(practiced.support_class == "unique" and reused.support_class == "unique"
            and reused.lineage_count == 1 and reused.source_documents ==
            ("doc-mn", "doc-no"),
            "cached practiced derivation lost its support summary")

    unsupported = unique.infer_relation("X", "contains", "missing")
    require(unsupported.status == "unknown" and unsupported.support_class == "none"
            and unsupported.lineage_count == 0 and unsupported.source_count == 0,
            "unsupported result reported non-existent support")

    print("symbolic support classes diagnostic: PASS")
    print("unique/redundant/contested, lineage counts, leaf sources, cache reuse, and no-support cases: PASS")


if __name__ == "__main__":
    main()
