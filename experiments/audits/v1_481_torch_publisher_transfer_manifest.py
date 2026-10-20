"""Freeze a source-disjoint PyTorch API-docstring review sample.

Run with:
    python3 experiments/audits/v1_481_torch_publisher_transfer_manifest.py

This writes the corpus fingerprint and candidate/non-candidate sample before
manual review. Do not tune the parser against this manifest and still call the
results held-out transfer. The sample is a diagnostic, not a probability
sample, and docstrings are not complete documentation pages.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from crms_procedure_discovery import (
    nearest_parameter_heading,
    propose_contextual_procedure_phrase_candidates,
    propose_procedure_phrase_candidates,
)
from crms_research import _sentence_spans


EXPECTED_VERSION = "2.13.0"
MODULE_NAMES = (
    "torch.nn", "torch.optim", "torch.utils.data", "torch.linalg",
)
SAMPLE_SIZE = 20


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def collect_units() -> dict[tuple[str, str, str], tuple[str, str, str]]:
    units = {}
    for module_name in MODULE_NAMES:
        module = importlib.import_module(module_name)
        for name in dir(module):
            if name.startswith("_"):
                continue
            try:
                obj = getattr(module, name)
                doc = inspect.getdoc(obj)
                source_module = getattr(obj, "__module__", "")
                qualified_name = getattr(obj, "__qualname__", name)
            except Exception:
                continue
            if (not callable(obj) or not doc or len(doc) < 80
                    or not source_module.startswith("torch.")):
                continue
            units[(source_module, qualified_name, doc)] = (
                source_module, qualified_name, doc)
    return units


def main() -> None:
    version = importlib.metadata.version("torch")
    require(version == EXPECTED_VERSION,
            f"torch version changed: expected {EXPECTED_VERSION}, got {version}")
    units = collect_units()
    corpus_digest = hashlib.sha256()
    candidates: list[dict[str, object]] = []
    non_candidates: list[dict[str, object]] = []
    counts = {
        "will_sentences": 0,
        "direct_candidate_sentences": 0,
        "contextual_candidate_sentences": 0,
        "candidate_proposals": 0,
        "no_candidate_sentences": 0,
    }

    for source_module, qualified_name, doc in sorted(units):
        corpus_digest.update(source_module.encode("utf-8"))
        corpus_digest.update(b"\0")
        corpus_digest.update(qualified_name.encode("utf-8"))
        corpus_digest.update(b"\0")
        corpus_digest.update(doc.encode("utf-8"))
        corpus_digest.update(b"\0")
        document_id = f"{source_module}.{qualified_name}"
        document_hash = hashlib.sha256(doc.encode("utf-8")).hexdigest()

        for start, end in _sentence_spans(doc):
            sentence = doc[start:end]
            if "will" not in sentence.casefold():
                continue
            counts["will_sentences"] += 1
            sentence_citation = (
                f"{document_id}#sha256={document_hash}&chars={start}:{end}")
            require(doc[start:end] == sentence,
                    f"sentence span mismatch for {document_id}")
            proposals = propose_procedure_phrase_candidates(
                sentence, source_citation=sentence_citation)
            context_text = context_citation = None
            method = "direct"
            if proposals:
                counts["direct_candidate_sentences"] += 1
            else:
                heading = nearest_parameter_heading(doc, start)
                if heading:
                    _, context_start, context_end = heading
                    context_text = doc[context_start:context_end]
                    context_citation = (
                        f"{document_id}#sha256={document_hash}"
                        f"&chars={context_start}:{context_end}")
                    require(doc[context_start:context_end] == context_text,
                            f"context span mismatch for {document_id}")
                    proposals = propose_contextual_procedure_phrase_candidates(
                        sentence, source_citation=sentence_citation,
                        context_text=context_text,
                        context_citation=context_citation)
                    if proposals:
                        method = "contextual"
                        counts["contextual_candidate_sentences"] += 1

            key = hashlib.sha256(
                (document_id + "\0" + sentence).encode("utf-8")
            ).hexdigest()
            if not proposals:
                counts["no_candidate_sentences"] += 1
                non_candidates.append({
                    "sample_key": key,
                    "api_unit": document_id,
                    "sentence_sha256": hashlib.sha256(
                        sentence.encode("utf-8")).hexdigest(),
                    "source_citation": sentence_citation,
                    "source_sentence": sentence,
                })
                continue

            counts["candidate_proposals"] += len(proposals)
            candidates.append({
                "sample_key": key,
                "api_unit": document_id,
                "sentence_sha256": hashlib.sha256(
                    sentence.encode("utf-8")).hexdigest(),
                "source_citation": sentence_citation,
                "source_sentence": sentence,
                "discovery_method": method,
                "context_text": context_text,
                "context_citation": context_citation,
                "candidate_fields": [
                    {
                        "subject": item.subject,
                        "predicate": item.predicate_phrase,
                        "positive": item.polarity,
                        "scope": list(item.scope_notes),
                        "assertion_status": item.assertion_status,
                        "quoted": item.quoted,
                        "review_status": item.status,
                    }
                    for item in proposals
                ],
            })

    def one_per_unit(rows: list[dict[str, object]], limit: int
                     ) -> list[dict[str, object]]:
        selected = []
        seen_units = set()
        for row in sorted(rows, key=lambda item: str(item["sample_key"])):
            unit = row["api_unit"]
            if unit in seen_units:
                continue
            selected.append(row)
            seen_units.add(unit)
            if len(selected) == limit:
                break
        return selected

    selected_candidates = one_per_unit(candidates, SAMPLE_SIZE)
    selected_non_candidates = one_per_unit(non_candidates, SAMPLE_SIZE)
    package = importlib.metadata.distribution("torch")
    report = {
        "audit": "v1_481_torch_publisher_transfer_manifest",
        "date": "2026-10-20",
        "status": "frozen_before review; labels intentionally absent",
        "source": {
            "distribution": "torch",
            "version": version,
            "license": package.metadata.get("License-Expression")
                or package.metadata.get("License"),
            "scope": "complete installed callable docstrings exposed by four API modules",
            "modules": list(MODULE_NAMES),
            "canonical_units": len(units),
            "corpus_sha256": corpus_digest.hexdigest(),
        },
        "scan": {
            "sentence_universe": "sentences containing the literal token 'will'",
            **counts,
        },
        "sample_method": (
            "Within candidate and no-candidate classes, sort by SHA-256 of "
            "canonical API unit plus exact sentence; select up to 20, with "
            "at most one sentence per API unit. Freeze before content review."),
        "candidate_sample": selected_candidates,
        "non_candidate_sample": selected_non_candidates,
        "limits": [
            "This is an exploratory source-disjoint diagnostic, not a probability sample or independent validation.",
            "Docstrings are complete callable reference units, not complete documentation pages.",
            "The scan is limited to sentences containing 'will'; other constructions are outside this measurement.",
            "Candidate status does not mean the sentence states useful behavior or that extracted fields are correct.",
            "Do not tune against this sample and still describe the result as held-out transfer.",
        ],
    }
    output = PROJECT / "experiments/reports/v1_481_torch_publisher_transfer_manifest.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(f"Wrote {output.relative_to(PROJECT)}")
    print(json.dumps({
        "source_version": version,
        "canonical_units": len(units),
        "corpus_sha256": corpus_digest.hexdigest(),
        "scan": counts,
        "sample_sizes": {
            "candidate": len(selected_candidates),
            "non_candidate": len(selected_non_candidates),
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
