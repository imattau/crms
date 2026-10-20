"""Measure exact endpoint-pair overlap in map-free phrase candidates.

This reruns the v1_464 report-only discovery scan and asks whether the same
normalized subject/object pair is supported by both the candidate phrase and
the dominant phrase. Zero overlap is not a rejection signal: paraphrases may
occur on different pages. The accompanying lexical review is explicitly
post-hoc and unblinded, so it is exploratory rather than a precision estimate.

Run:
    python3 experiments/v1_468_pair_overlap_discovery.py [INDEX]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_464_unmapped_structured_predicate_discovery import (  # noqa: E402
    DEFAULT_INDEX,
    run as run_discovery,
)
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402

REVIEW_PATH = PROJECT / "experiments" / "reports" / (
    "v1_464_unmapped_structured_predicate_review.json")
OUTPUT_PATH = PROJECT / "experiments" / "reports" / (
    "v1_468_pair_overlap_discovery.json")
_FUNCTION_WORDS = {
    "a", "an", "the", "of", "in", "on", "at", "by", "to", "for",
    "is", "was", "were", "are", "be", "and", "as", "with",
}


def _content_words(phrase: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", phrase.casefold())
            if word not in _FUNCTION_WORDS}


def _review_lexical_filter(discovery: dict[str, Any],
                           review: dict[str, Any]) -> dict[str, Any]:
    judgments = {
        (item["field"], item["title_role"],
         item["dominant_training_phrase"], item["candidate_phrase"]):
        item["judgment"]
        for item in review["candidates"]
    }
    retained: dict[str, int] = {}
    threshold = 0.75
    retained_count = 0
    for candidate in discovery["candidates"]:
        dominant = _content_words(candidate["dominant_training_phrase"])
        variant = _content_words(candidate["candidate_phrase"])
        coefficient = (len(dominant & variant) / max(1, min(
            len(dominant), len(variant))))
        key = (candidate["field"], candidate["title_role"],
               candidate["dominant_training_phrase"],
               candidate["candidate_phrase"])
        judgment = judgments.get(key, "unreviewed")
        if coefficient >= threshold:
            retained_count += 1
            retained[judgment] = retained.get(judgment, 0) + 1
    return {
        "review_file": str(REVIEW_PATH.relative_to(PROJECT)),
        "review_blinded": bool(review.get("blinded")),
        "review_independent": bool(
            review.get("independent_of_candidate_generation")),
        "filter": "content-word overlap coefficient >= 0.75",
        "threshold_status": "post-hoc exploratory; inspected against these labels",
        "retained_groups": retained_count,
        "retained_judgments": retained,
        "interpretation": (
            "This filter cannot establish precision or serve as a promotion "
            "gate because the review is unblinded and the threshold is "
            "post-hoc. Use only to formulate a future frozen-candidate study."
        ),
    }


def _audit_citations(index_path: Path,
                     candidates: list[dict[str, Any]]) -> dict[str, int]:
    index = CRMSSQLiteResearchIndex(index_path, read_only=True)
    checked = 0
    try:
        for candidate in candidates:
            for key in ("support", "heldout_support", "dominant_examples",
                        "same_pair_examples", "same_pair_heldout_examples"):
                for row in candidate.get(key, []):
                    for citation_key, text_key in (
                            ("sentence_citation", "sentence"),
                            ("field_citation", "field_line")):
                        citation = row.get(citation_key)
                        if citation:
                            if index.resolve_citation(citation) != row[text_key]:
                                raise ValueError(
                                    f"citation does not resolve to exact text: {citation}")
                            checked += 1
    finally:
        index.close()
    return {"spans_checked": checked,
            "exact_source_hash_and_text_matches": checked}


def run(index_path: Path, output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    discovery = run_discovery(index_path)
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    candidates = discovery["candidates"]
    discovery["experiment"] = "v1_468_pair_overlap_discovery"
    discovery["baseline_experiment"] = (
        "v1_464_unmapped_structured_predicate_discovery")
    discovery["pair_overlap_summary"] = {
        "candidate_groups": len(candidates),
        "candidate_groups_with_training_pair_overlap": sum(
            bool(item.get("same_pair_training_support")) for item in candidates),
        "candidate_groups_with_holdout_pair_overlap": sum(
            bool(item.get("same_pair_holdout_support")) for item in candidates),
        "training_pair_overlap_total": sum(
            item.get("same_pair_training_support", 0) for item in candidates),
        "holdout_pair_overlap_total": sum(
            item.get("same_pair_holdout_support", 0) for item in candidates),
        "meaning": "Exact same subject/object pairs were never supported by both phrases.",
    }
    discovery["posthoc_lexical_audit"] = _review_lexical_filter(
        discovery, review)
    discovery["citation_audit"] = _audit_citations(index_path, candidates)
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT,
            text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    discovery["source_revision"] = revision
    discovery["run_configuration"] = {
        "index": str(index_path),
        "documents_scanned": discovery["documents_scanned"],
        "split": discovery["split"],
    }
    discovery["interpretation"] = (
        "The full corpus rerun found no exact endpoint-pair overlap between "
        "the surfaced variant and dominant phrase groups. This strict signal "
        "does not distinguish useful candidates here; phrases may occur on "
        "different pages. The lexical audit is post-hoc and unblinded, so it "
        "does not estimate precision or license promotion. Keep candidates "
        "report-only and test a frozen feature set with blinded review."
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(discovery, indent=2, ensure_ascii=False)
                           + "\n", encoding="utf-8")
    return discovery


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("index", nargs="?", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--json-out", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    result = run(args.index, args.json_out)
    print("PAIR OVERLAP", json.dumps(result["pair_overlap_summary"], sort_keys=True))
    print("LEXICAL AUDIT", json.dumps(result["posthoc_lexical_audit"], sort_keys=True))
    print("REPORT", args.json_out)


if __name__ == "__main__":
    main()
