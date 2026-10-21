#!/usr/bin/env python3
"""Interactively review pending document-derived claims.

Each decision records the reviewer identity and the measured wall-clock seconds
between displaying the candidate and receiving the decision. Candidate text is
shown with its exact citation, roles, conditions, and status so review never
has to reopen the source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_document_learning import (  # noqa: E402
    ReviewQueue, extract_corpus_claims, load_corpus,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path,
        default=PROJECT / "corpus" / "phase3_eval" / "manifest.json")
    parser.add_argument("--queue", type=Path,
                        default=PROJECT / "phase3_review.sqlite")
    parser.add_argument("--reviewer", default="")
    args = parser.parse_args()

    queue = ReviewQueue(args.queue)
    if not queue.pending():
        corpus = load_corpus(args.corpus)
        queue.add(extract_corpus_claims(corpus))
    reviewer = args.reviewer.strip() or input("Reviewer identity: ").strip()
    if not reviewer:
        raise SystemExit("a reviewer identity is required")
    try:
        while True:
            pending = queue.pending()
            if not pending:
                break
            row = pending[0]
            payload = row["payload"]
            print("\n" + "=" * 72)
            print(f"Candidate {row['candidate_id']}  {row['source_id']}")
            print(f"Family: {row['family']}  Status: {row['status']}")
            print(f"Statement: {payload['statement']}")
            print(f"Roles: {payload.get('roles')}")
            if payload.get("conditions"):
                print(f"Conditions: {payload['conditions']}")
            if payload.get("antecedent"):
                print(f"Antecedent: {payload['antecedent']}")
            print(f"Citation: {payload['citation']}")
            print(f"Source: {payload['sentence']}")
            begun = time.perf_counter()
            answer = input("[a]ccept / [r]eject / [s]kip / [q]uit: ").strip().casefold()
            elapsed = time.perf_counter() - begun
            if answer in {"q", "quit"}:
                break
            if answer in {"s", "skip"}:
                print("Skipped; candidate remains pending.")
                continue
            if answer not in {"a", "accept", "r", "reject"}:
                print("Unknown decision; candidate remains pending.")
                continue
            taxonomy = ""
            if answer.startswith("r"):
                taxonomy = input("False-positive taxonomy (optional): ").strip()
            queue.review(
                row["candidate_id"],
                decision="accept" if answer.startswith("a") else "reject",
                reviewer=reviewer, seconds=elapsed, taxonomy=taxonomy)
            print(f"Recorded {answer} in {elapsed:.1f}s")
    finally:
        queue.close()
    metrics_queue = ReviewQueue(args.queue)
    try:
        print(json.dumps(metrics_queue.metrics(), indent=2))
    finally:
        metrics_queue.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
