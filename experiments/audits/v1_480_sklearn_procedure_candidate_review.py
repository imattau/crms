"""Exploratory third-source review of procedure phrase candidates.

Run with:
    python3 experiments/audits/v1_480_sklearn_procedure_candidate_review.py

This is a source-disjoint diagnostic against installed scikit-learn API
docstrings, not held-out transfer: the corpus was inspected before the sample
was frozen. It stores exact sentence/context citations and a deterministic
one-per-API-unit review sample. Codex labels are unblinded, single-rater
diagnostics and are not a precision estimate.
"""
from __future__ import annotations

from collections import Counter
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


EXPECTED_VERSION = "1.9.0"
MODULE_NAMES = (
    "sklearn.model_selection", "sklearn.preprocessing", "sklearn.pipeline",
    "sklearn.metrics", "sklearn.ensemble", "sklearn.decomposition",
)

# Labels are keyed by prefixes of the hash over (canonical API unit, sentence).
LABELS = {
    "0128daea8920": (
        "boundary_error",
        "A bullet conditional is absorbed into the subject and the predicate is truncated.",
    ),
    "02e256f99359": (
        "reviewable",
        "The average parameter is recovered from its adjacent heading; its citation is separate.",
    ),
    "0307a87b7d9b": (
        "context_needed",
        "The pronoun This has no antecedent in the cited sentence.",
    ),
    "037fa38079df": (
        "reviewable",
        "The complete feature-value subject and mapped output bounds are retained.",
    ),
    "039d2165e8c4": (
        "reviewable",
        "The split-point subject and its min_samples_leaf condition are retained.",
    ),
    "054d816d428f": (
        "reviewable",
        "The ccp_alpha subject and selected-value predicate are explicit.",
    ),
    "06c390951518": (
        "reviewable",
        "The group subject and exactly-once test-fold behavior are explicit.",
    ),
    "0786bb624976": (
        "boundary_error",
        "The parameter declaration contaminates the subject; the claim subject is a node.",
    ),
    "08f5658bad7f": (
        "reviewable",
        "The infrequent-category subject and target position are explicit.",
    ),
    "09deebce0307": (
        "context_needed",
        "The contrast clause leaves it unresolved in the sentence-local candidate.",
    ),
    "0aa67ec8ce0a": (
        "context_needed",
        "This depends on earlier source context; the candidate does not resolve it.",
    ),
    "0b4c49b2167d": (
        "boundary_error",
        "The subordinate as-clause is extracted with a malformed subject boundary.",
    ),
}


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
                    or not source_module.startswith("sklearn.")):
                continue
            units[(source_module, qualified_name, doc)] = (
                source_module, qualified_name, doc)
    return units


def main() -> None:
    version = importlib.metadata.version("scikit-learn")
    require(version == EXPECTED_VERSION,
            f"scikit-learn version changed: expected {EXPECTED_VERSION}, got {version}")
    units = collect_units()
    corpus_digest = hashlib.sha256()
    candidates = []
    sentence_count = direct_count = contextual_count = no_candidate_count = 0

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
            sentence_count += 1
            sentence_citation = (
                f"{document_id}#sha256={document_hash}&chars={start}:{end}")
            require(doc[start:end] == sentence,
                    f"sentence span mismatch for {document_id}")
            proposals = propose_procedure_phrase_candidates(
                sentence, source_citation=sentence_citation)
            context_citation = context_text = None
            basis = "direct"
            if not proposals:
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
                    basis = "contextual" if proposals else "none"
                else:
                    basis = "none"

            if not proposals:
                no_candidate_count += 1
                continue
            if basis == "direct":
                direct_count += 1
            else:
                contextual_count += 1
            for proposal in proposals:
                key = hashlib.sha256(
                    (document_id + "\0" + sentence).encode("utf-8")
                ).hexdigest()
                candidates.append({
                    "sample_key": key,
                    "api_unit": document_id,
                    "sentence_sha256": hashlib.sha256(
                        sentence.encode("utf-8")).hexdigest(),
                    "source_citation": sentence_citation,
                    "source_sentence": sentence,
                    "candidate": {
                        "subject": proposal.subject,
                        "predicate": proposal.predicate_phrase,
                        "positive": proposal.polarity,
                        "scope": list(proposal.scope_notes),
                        "basis": proposal.context_basis or "direct",
                        "context_text": context_text,
                        "context_citation": context_citation,
                    },
                })

    # Keep at most one sentence per API unit so duplicated text in a long
    # docstring cannot dominate the diagnostic sample.
    selected = []
    sampled_units = set()
    for row in sorted(candidates, key=lambda item: item["sample_key"]):
        if row["api_unit"] in sampled_units:
            continue
        sampled_units.add(row["api_unit"])
        prefix = row["sample_key"][:12]
        require(prefix in LABELS,
                f"new selected sample row requires review: {prefix}")
        label, rationale = LABELS[prefix]
        row["codex_review_label"] = label
        row["review_note"] = rationale
        selected.append(row)
        if len(selected) == len(LABELS):
            break
    require(len(selected) == len(LABELS), "sample size changed")
    require({row["sample_key"][:12] for row in selected} == set(LABELS),
            "sample membership changed; re-review before updating labels")

    report = {
        "audit": "v1_480_sklearn_procedure_candidate_review",
        "date": "2026-10-20",
        "source": {
            "distribution": "scikit-learn",
            "version": version,
            "license": "BSD-3-Clause",
            "scope": "complete installed callable docstrings from six public API modules",
            "canonical_units": len(units),
            "corpus_sha256": corpus_digest.hexdigest(),
        },
        "scan": {
            "sentence_universe": "sentences containing the literal token 'will'",
            "sentences": sentence_count,
            "direct_candidate_sentences": direct_count,
            "contextual_candidate_sentences": contextual_count,
            "candidate_proposals": len(candidates),
            "no_candidate_sentences": no_candidate_count,
        },
        "sample": {
            "method": "lowest SHA-256 keys, one candidate sentence per canonical API unit",
            "selected": len(selected),
            "label_counts": dict(sorted(Counter(
                row["codex_review_label"] for row in selected).items())),
            "label_protocol": (
                "Unblinded, single Codex review of exact sentence and fields. "
                "Labels are a diagnostic, not independent validation or a "
                "probability-sample precision estimate."),
            "rows": selected,
        },
        "limits": [
            "The corpus was scanned and sample sentences inspected before this sample was frozen; it is exploratory, not untouched transfer.",
            "Docstrings are complete callable reference units, not complete documentation pages.",
            "The scan conditions on sentences containing 'will'; it says nothing about other constructions.",
            "High candidate yield is not semantic precision, useful rule yield, or recall.",
            "No candidate was accepted, installed, or used to tune the parser.",
            "The sample is deterministic and one-per-unit, but not a probability sample.",
        ],
    }
    output = PROJECT / "experiments/reports/v1_480_sklearn_procedure_candidate_review.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(f"Wrote {output.relative_to(PROJECT)}")
    print(json.dumps(report["scan"], indent=2, sort_keys=True))
    print(json.dumps(report["sample"]["label_counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
