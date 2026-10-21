#!/usr/bin/env python3
"""Run the frozen Phase 3 document-learning evaluation and gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_document_learning import (  # noqa: E402
    ReviewQueue, apply_gate, extract_corpus_claims, load_corpus,
    phase3_metrics, promote_accepted, propose_claims_to_registry,
    review_with_frozen_oracle,
)
from crms_research import CRMSResearchIndex  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path,
        default=PROJECT / "corpus" / "phase3_eval" / "manifest.json")
    parser.add_argument(
        "--out", type=Path,
        default=PROJECT / "experiments" / "reports" /
        "phase3_document_learning.json")
    parser.add_argument("--registry", type=Path, default=None,
                        help="where to save the governed proposal registry")
    parser.add_argument("--queue", type=Path, default=None,
                        help="where to save the review ledger")
    parser.add_argument("--learning-publisher", default="northwind-docs",
                        help="publisher whose reviewed rules are transferred")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    claims = extract_corpus_claims(corpus)
    registry = RuleRegistry()
    proposed_ids = propose_claims_to_registry(claims, registry)
    pre_review_active = [
        record.id for record in registry.records(state="active")
        if record.id.startswith("phase3-")
    ]
    if pre_review_active:
        raise SystemExit("a document candidate affected runtime before review")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    registry_path = args.registry or args.out.with_name(
        "phase3_registry.sqlite")
    queue_path = args.queue or args.out.with_name("phase3_review.sqlite")
    for path in (registry_path, queue_path):
        if path.exists():
            path.unlink()

    queue = ReviewQueue(queue_path)
    try:
        queue.add(claims)
        reviewed = review_with_frozen_oracle(queue, corpus)
        promotion = promote_accepted(queue, registry)
        index = CRMSResearchIndex()
        for document in corpus.documents:
            index.add_document(
                document.id, document.title, document.text, document.url)
        metrics = phase3_metrics(
            corpus, queue, registry, claims,
            learning_publisher=args.learning_publisher, index=index)
        metrics = apply_gate(metrics)
        metrics["pre_review"] = {
            "proposed": len(proposed_ids),
            "active": len(pre_review_active),
            "reviewed": reviewed["reviewed"],
            "promoted": promotion,
        }
        metrics["registry_path"] = _display_path(registry_path)
        metrics["queue_path"] = _display_path(queue_path)
        metrics["corpus_path"] = _display_path(args.corpus)
        metrics["review_protocol"] = (
            "frozen adjudication ledger; use run_phase3_review.py for "
            "wall-clock human review")
        registry.save(registry_path)
        args.out.write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    finally:
        queue.close()

    review = metrics["review"]
    print(f"Corpus: {metrics['documents']} documents, "
          f"{metrics['publishers']} publishers, {metrics['genres']} genres")
    print(f"Candidates: {metrics['claims']} claims; "
          f"{review['reviewed']} reviewed; {review['accepted']} accepted")
    print(f"Precision: {review['precision']:.1%}; "
          f"seeded recall: {metrics['seeded_recall']['recall']:.1%}; "
          f"controls: {metrics['controls']['passed']}/"
          f"{metrics['controls']['total']}")
    print(f"Transfer: {metrics['transfer']['coverage']:.1%}; "
          f"retention: {metrics['retention']['retention']:.1%}; "
          f"review minutes/claim: {review['review_minutes_per_claim']:.2f}")
    print(f"Gate: {'PASS' if metrics['gate_passed'] else 'FAIL'} "
          f"{metrics['gate']}")
    print(f"Report: {args.out}")
    return 0 if metrics["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
