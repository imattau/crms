"""Compare dependency-based review proposals with the frozen SciPy sample.

Requires the optional ``spacy`` package and ``en_core_web_sm`` model. This is
development evidence only; it does not change the CRMS runtime or accept
source claims.
"""
from __future__ import annotations

import importlib.metadata
import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments" / "prototypes"))

import spacy

from procedure_discovery_spacy import (
    propose_dependency_procedure_phrase_candidates,
)


def candidate_record(candidate: object) -> dict[str, object]:
    return {
        "subject": candidate.subject,
        "predicate_phrase": candidate.predicate_phrase,
        "polarity": candidate.polarity,
        "quoted": candidate.quoted,
        "scope_notes": list(candidate.scope_notes),
        "assertion_status": candidate.assertion_status,
        "status": candidate.status,
    }


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_controls(nlp: object) -> None:
    citation = "control#sha256=0123456789&chars=0:100"
    cases = (
        ("The algorithm will not accumulate weight decay in the momentum if "
         "decoupled weight decay is enabled.", "The algorithm", False,
         "condition: if decoupled weight decay is enabled"),
        ("If a NaN is present, a ValueError will be raised.",
         "a ValueError", True, "condition: If a NaN is present"),
        ("NaNs will be omitted when performing the calculation.",
         "NaNs", True, "condition: when performing the calculation"),
        ("If None, the input will be raveled before computing the statistic.",
         "the input", True, "condition: If None"),
        ("By default an array of the same dtype as input will be created.",
         "an array of the same dtype as input", True, "context: By default"),
        ("If a NaN is present, a ``ValueError`` will be raised.",
         "a ``ValueError``", True, "condition: If a NaN is present"),
        ("The final ``x`` will usually have fewer correct digits, depending "
         "on ``cond(A)`` and the size of LAMBDA.",
         "The final ``x``", True, ""),
    )
    for sentence, expected_subject, expected_polarity, expected_scope in cases:
        candidates = propose_dependency_procedure_phrase_candidates(
            nlp, sentence, source_citation=citation)
        if not any(
                candidate.subject == expected_subject
                and candidate.polarity is expected_polarity
                and (not expected_scope or expected_scope in candidate.scope_notes)
                for candidate in candidates):
            raise SystemExit(
                f"dependency parser control failed: {sentence!r}: {candidates!r}")

    denied = propose_dependency_procedure_phrase_candidates(
        nlp,
        "This step does not guarantee that properties will be conserved.",
        source_citation=citation)
    if not denied or not all(
            candidate.assertion_status == "denied"
            and candidate.status == "needs_review" for candidate in denied):
        raise SystemExit("embedded denial was not marked review-only")
    if propose_dependency_procedure_phrase_candidates(
            nlp, "If not given a reasonable set will be calculated.",
            source_citation=citation):
        raise SystemExit("missing subject control should abstain")


def main() -> None:
    source_report = json.loads((PROJECT / "experiments" / "reports"
                               / "v1_486_scipy_will_claim_fit.json")
                              .read_text(encoding="utf-8"))
    nlp = spacy.load("en_core_web_sm")
    check_controls(nlp)
    groups = {}
    for name in ("candidate_sample", "unhandled_sample"):
        rows = []
        for row in source_report[name]:
            candidates = propose_dependency_procedure_phrase_candidates(
                nlp, row["sentence"],
                source_citation=row["source_citation"])
            rows.append({
                **row,
                "dependency_candidates": [candidate_record(item)
                                          for item in candidates],
            })
        groups[name] = rows

    report = {
        "audit": "v1_487",
        "purpose": "prototype comparison on SciPy development controls",
        "source_audit": "v1_486",
        "parser": {
            "library": "spaCy",
            "version": spacy.__version__,
            "model": "en_core_web_sm",
            "model_version": importlib.metadata.version("en-core-web-sm"),
        },
        "implementation_sha256": {
            "prototype": file_digest(
                PROJECT / "experiments" / "prototypes"
                / "procedure_discovery_spacy.py"),
            "core_assertion_status": file_digest(
                PROJECT / "crms_procedure_discovery.py"),
        },
        "method": (
            "For each AUX 'will', use dependency subject roots, remove simple "
            "condition subtrees from the predicate span, and preserve exact "
            "source text and citation. Candidates remain needs_review."),
        "samples": groups,
        "observations": [
            "Synthetic controls preserve passive and inline-code subjects, explicit parameter conditions, by-default context, and simple if/when scope; an embedded denial is flagged and a subjectless passive abstains.",
            "Dependency subjects recover several passive subjects and simple output relations; equal-length Markdown stripping preserves offsets and fixes several inline-code boundaries.",
            "The prototype still misbinds or truncates subjects around some inline code, fragments, contrast, ellipsis, and documentation metadata.",
            "Conditions and shared subjects are not consistently separated from the proposition.",
            "This sample was used for prototype inspection and is development data, not a holdout.",
        ],
        "limitations": [
            "Single-rater diagnostic on 40 hash-selected rows from SciPy docstrings.",
            "Does not estimate precision or recall and does not establish transfer.",
            "The parser/model are optional development dependencies; no CRMS runtime path depends on them.",
            "No candidates are accepted or installed as rules.",
        ],
        "manual_review": {
            "reviewer": "Codex",
            "candidate_sample_structurally_coherent": 11,
            "candidate_sample_size": len(groups["candidate_sample"]),
            "unhandled_sample_plausible_dependency_claims": 7,
            "unhandled_sample_size": len(groups["unhandled_sample"]),
            "basis": (
                "A coherent candidate has a source-supported subject, a "
                "predicate that preserves the stated relation, and explicit "
                "conditions represented without guessing an antecedent."),
            "interpretation": (
                "Single-rater diagnostic on a development sample; not a "
                "precision/recall estimate. All outputs remain review-only."),
        },
    }
    out = PROJECT / "experiments" / "reports" / "v1_487_spacy_dependency_prototype.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}")
    for name, rows in groups.items():
        produced = sum(bool(row["dependency_candidates"]) for row in rows)
        print(f"{name}: {produced}/{len(rows)} rows produced review candidates")
    print("manual review: 11/20 existing candidates structurally coherent; "
          "7/20 no-candidate rows gain plausible dependency proposals")
    print("scope: development-only parser comparison; no transfer claim")


if __name__ == "__main__":
    main()
