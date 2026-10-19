"""Check the opt-in sentence-ranker pilot without changing chat behavior.

This mechanism fixture proves only deterministic training, record round-trip,
gate-preserving candidate selection, and threshold abstention. It is not a
quality benchmark and does not satisfy the ranker's deployment conditions.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_nl_gate import gate_quoted_evidence
from crms_sentence_ranker import (
    FEATURE_NAMES, SentenceRanker, feature_vector, fit_ranker,
    rank_candidates, rank_gated_candidates,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    training = []
    sources = []
    for number in range(24):
        entity = f"Meridian Engine {number:02d}"
        question = f"Who designed {entity}?"
        positive = {
            "text": f"Ada {number:02d} designed {entity} after testing.",
            "citation": f"fixture:positive-{number}",
            "paragraph_first_sentence": True,
        }
        negative = {
            "text": f"Zed {number:02d} designed {entity} for Ada {number:02d}.",
            "citation": f"fixture:negative-{number}",
            "paragraph_first_sentence": False,
        }
        docs = [positive["text"], negative["text"]]
        training.extend([
            (feature_vector(question, positive, candidate_count=2,
                            candidate_documents=docs), 1),
            (feature_vector(question, negative, candidate_count=2,
                            candidate_documents=docs), 0),
        ])
        sources.extend((positive["citation"], negative["citation"]))

    model = fit_ranker(training, training_source_ids=sources,
                       trained_on="2026-10-19", threshold=0.3)
    record = model.as_dict()
    restored = SentenceRanker.from_dict(json.loads(json.dumps(record)))
    require(tuple(record["feature_names"]) == FEATURE_NAMES,
            "model record did not retain its feature schema")
    require(restored == model, "model record did not round-trip exactly")
    require(record["training_source_ids"] == sorted(sources),
            "model record omitted training source provenance")

    question = "Who designed Meridian Engine 99?"
    candidates = [
        {"text": "Ada 99 designed Meridian Engine 99 after testing.",
         "citation": "heldout:positive",
         "paragraph_first_sentence": True},
        {"text": "Zed 99 designed Meridian Engine 99 for Ada 99.",
         "citation": "heldout:negative",
         "paragraph_first_sentence": False},
    ]
    baseline = gate_quoted_evidence(question, candidates)
    require(baseline["status"] == "ambiguous",
            f"fixture did not create the intended gate tie: {baseline}")
    ranked, selected = rank_gated_candidates(question, candidates, restored)
    require(len(ranked) == 2 and selected is not None
            and selected["citation"] == "heldout:positive"
            and set(selected["ranker_features"]) == set(FEATURE_NAMES),
            f"opt-in ranker failed to select with an inspectable trace: {ranked}")

    rejected, no_selection = rank_gated_candidates(
        "Who destroyed Meridian Engine 99?", candidates, restored)
    require(not rejected and no_selection is None,
            "ranker introduced candidates that failed the unchanged gate")
    require(not rank_candidates("Who destroyed Meridian Engine 99?",
                                candidates, restored),
            "public rank_candidates bypassed the evidence gate")
    low_threshold_model = SentenceRanker(
        restored.weights, restored.bias, 0.999999, restored.training_examples,
        restored.positive_examples, restored.training_data_sha256,
        restored.training_source_ids, restored.trained_on,
        restored.training_parameters, restored.training_method,
        restored.version)
    _ranked, abstained = rank_gated_candidates(
        question, candidates, low_threshold_model)
    require(abstained is None,
            "ranker threshold did not preserve an abstention outcome")

    repeated = fit_ranker(training, training_source_ids=sources,
                          trained_on="2026-10-19", threshold=0.3)
    require(repeated == model, "training was not deterministic")
    print("sentence-ranker pilot mechanism: PASS")
    print("gate-preserving candidate set, deterministic training, source-aware "
          "model record, feature trace, threshold abstention: PASS")
    print("quality, FTS retrieval, fresh-corpus, hand-written-set, domain, and "
          "latency checks remain open; production chat remains unchanged")


if __name__ == "__main__":
    main()
