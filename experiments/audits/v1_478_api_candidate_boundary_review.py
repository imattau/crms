"""Reproduce the fixed Codex review sample for the v1_477 API corpus.

Run with:
    python3 experiments/audits/v1_478_api_candidate_boundary_review.py

The sample and labels are development diagnostics. Codex labels are unblinded
single-rater supervision, not independent validation or a probability sample.
The output stores citations and hashes, not copied documentation text.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib
from importlib import metadata
import inspect
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_research import _sentence_spans


EXPECTED_CORPORA = {
    "numpy": {
        "version": "2.5.1",
        "sha256": "e0de3744dad3b18a02a455b04bcb31ec59c7d51543b21674cea6496b930f6567",
    },
    "pandas": {
        "version": "3.0.5",
        "sha256": "77c2241d955527380a76b6a493e2341e52e3db1b06c37255f730aa1ae6f2cbc1",
    },
}

# Labels keyed by the first 12 hex digits of the SHA-256 sample key. The
# script checks these prefixes are unique in the selected rows.
LABELS = {
    "candidate": {
        "numpy": {
            "0092c4863463": ("context_needed", "The local subject contains 'it'; the condition supplies its antecedent."),
            "00a2a9cd4533": ("reviewable", "The out-array role and Elsewhere scope are explicit."),
            "00a55ee875ac": ("context_needed", "'Within it' refers to the out array in the condition."),
            "01c525eb5bb1": ("boundary_error", "A time qualifier was absorbed into the subject and a second clause into the predicate."),
            "02d83245e0ff": ("context_needed", "The subject contains 'it'; its referent is in the condition."),
            "03732e94f67b": ("reviewable", "The out-array role and Elsewhere scope are explicit."),
            "0376c7d14686": ("reviewable", "The out-array role and Elsewhere scope are explicit."),
            "03c2cc2b6854": ("context_needed", "'Within it' refers to the out array in the condition."),
            "04e2c8a77495": ("boundary_error", "The parameter axis was selected as subject although unwrap is the actor of 'operate'."),
            "053a500be659": ("reviewable", "The result-dtype subject and both conditions are preserved."),
        },
        "pandas": {
            "00bc8ce084d6": ("reviewable", "The resulting categorical subject and If True condition are preserved."),
            "00fc3767fad2": ("reviewable", "The IntervalIndex subject and omitted-frequency condition are preserved."),
            "01cf2e423b48": ("boundary_error", "Parameter metadata and the If True condition are absorbed into the subject."),
            "035c7cb00cba": ("reviewable", "The presence of out-of-bounds values is the explicit subject."),
            "04da80eeb27d": ("reviewable", "The quoted option label and KeyError behavior are recoverable from the cited bullet."),
            "052baca6d38d": ("boundary_error", "The condition 'If passed columns' is presented as the subject; the action subject is omitted."),
            "06951433e97d": ("context_needed", "'These' refers to other columns named in the preceding condition."),
            "06dd758e89bb": ("reviewable", "The datetime-values subject and conversion result are explicit."),
            "092e974098a9": ("reviewable", "The NA-values subject and If False condition are preserved."),
            "093dc5d6df91": ("boundary_error", "The leading If condition and 'it' were combined into the subject."),
        },
    },
    "no_candidate": {
        "numpy": {
            "017788c48957": ("context_dependent", "A conditional behavior is stated, but its subject is omitted."),
            "049c0649ef04": ("not_a_behavior_claim", "The span is a bibliographic citation, not an API behavior claim."),
            "062c21b37a1c": ("context_dependent", "A conditional behavior is stated, but its subject is omitted."),
            "0d413ce7dd03": ("incomplete_source_fragment", "The docstring span ends with an incomplete 'will be' clause."),
            "11da4c23b75d": ("incomplete_source_fragment", "The docstring span ends with an incomplete 'will be' clause."),
            "1a3a635b37a4": ("context_dependent", "The future passive clause has no local subject."),
            "362788a8e98c": ("incomplete_source_fragment", "The docstring span ends with an incomplete 'will be' clause."),
            "3caaa16cf400": ("incomplete_source_fragment", "The docstring span ends with an incomplete 'will be' clause."),
            "40973aa3dd25": ("incomplete_source_fragment", "The docstring span ends with an incomplete 'will be' clause."),
            "4a82b3610c3c": ("context_dependent", "The later 'will use' clause omits the subject supplied by its surrounding description."),
        },
        "pandas": {
            "284f749214a7": ("context_dependent", "A bullet states behavior but omits the object that will normalize."),
            "2a53566ba8e7": ("context_dependent", "The condition is explicit but the returning subject is omitted."),
            "49d68912323a": ("shared_subject", "The coordinated 'will be removed' clause inherits 'This keyword'."),
            "6223478278f7": ("shared_subject", "The coordinated 'will be removed' clause inherits 'This keyword'."),
            "623de14c34c0": ("shared_subject", "The 'will prefer' clause inherits the dayfirst argument from the preceding clause."),
            "75e650cd9dda": ("context_dependent", "The selection action is stated, but its subject is omitted."),
            "79d7eb7ec6f0": ("shared_subject", "The 'will not be shown' clause inherits the c/f subject from the preceding clause."),
            "83b389e0822f": ("context_dependent", "A conditional behavior is stated but the subject is omitted."),
            "93850b1c4011": ("complex_scope", "The claim is present but nested conditions and a long lead-in exceed this sentence-local boundary method."),
            "a05decf08a77": ("shared_subject", "The 'will prefer' clause inherits the yearfirst argument from the preceding clause."),
        },
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def scan_package(package: str) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    module = importlib.import_module(package)
    units: dict[tuple[str, str, str], tuple[str, str]] = {}
    for export in sorted(set(getattr(module, "__all__", ()))):
        try:
            obj = getattr(module, export)
            doc = inspect.getdoc(obj)
        except Exception:
            continue
        if not callable(obj) or not doc or len(doc) < 80:
            continue
        module_name = getattr(obj, "__module__", package)
        qualified_name = getattr(obj, "__qualname__", export)
        units[(module_name, qualified_name, doc)] = (export, doc)

    corpus_digest = hashlib.sha256()
    all_rows: dict[str, list[dict[str, object]]] = {
        "candidate": [], "no_candidate": []}
    candidate_proposal_count = 0
    for (module_name, qualified_name, doc), (export, _) in sorted(
            units.items(), key=lambda item: item[0]):
        digest = hashlib.sha256(doc.encode("utf-8")).hexdigest()
        corpus_digest.update(module_name.encode("utf-8"))
        corpus_digest.update(b"\0")
        corpus_digest.update(qualified_name.encode("utf-8"))
        corpus_digest.update(b"\0")
        corpus_digest.update(doc.encode("utf-8"))
        corpus_digest.update(b"\0")
        document_id = (f"{package}:{module_name}.{qualified_name}:"
                       f"{digest[:12]}")
        for start, end in _sentence_spans(doc):
            sentence = doc[start:end]
            if "will" not in sentence.casefold():
                continue
            citation = (f"{document_id}#sha256={digest}"
                        f"&chars={start}:{end}")
            require(doc[start:end] == sentence,
                    f"citation span failed for {document_id}")
            proposals = propose_procedure_phrase_candidates(
                sentence, source_citation=citation)
            candidate_proposal_count += len(proposals)
            sample_key = hashlib.sha256(
                (package + "\0" + document_id + "\0" + sentence)
                .encode("utf-8")).hexdigest()
            row: dict[str, object] = {
                "sample_key": sample_key,
                "api_export": export,
                "sentence_sha256": hashlib.sha256(
                    sentence.encode("utf-8")).hexdigest(),
                "source_citation": citation,
            }
            if proposals:
                row["candidate_fields"] = [
                    {
                        "subject": item.subject,
                        "predicate": item.predicate_phrase,
                        "scope": list(item.scope_notes),
                        "positive": item.polarity,
                        "quoted": item.quoted,
                        "assertion_status": item.assertion_status,
                    }
                    for item in proposals
                ]
                all_rows["candidate"].append(row)
            else:
                all_rows["no_candidate"].append(row)

    version = metadata.version(package)
    expected = EXPECTED_CORPORA[package]
    require(version == expected["version"],
            f"{package} version changed: {version}")
    require(corpus_digest.hexdigest() == expected["sha256"],
            f"{package} corpus fingerprint changed")
    return ({"package": package,
             "version": version,
             "corpus_sha256": corpus_digest.hexdigest(),
             "candidate_sentence_count": len(all_rows["candidate"]),
             "candidate_proposal_count": candidate_proposal_count,
             "no_candidate_count": len(all_rows["no_candidate"])}, all_rows)


def main() -> None:
    package_summaries = []
    review_rows = []
    for package in ("numpy", "pandas"):
        package_summary, groups = scan_package(package)
        package_summaries.append(package_summary)
        for sample_class, rows in groups.items():
            sample = sorted(rows, key=lambda row: str(row["sample_key"]))[:10]
            labels = LABELS[sample_class][package]
            require(len({str(row["sample_key"])[:12] for row in sample})
                    == len(sample), f"sample-key prefix collision in {package}")
            require(set(labels) == {str(row["sample_key"])[:12]
                                    for row in sample},
                    f"label set does not match frozen {package} {sample_class} sample")
            for row in sample:
                prefix = str(row["sample_key"])[:12]
                label, rationale = labels[prefix]
                review_rows.append({
                    "package": package,
                    "sample_class": sample_class,
                    **row,
                    "codex_review_label": label,
                    "review_note": rationale,
                })

    label_counts: dict[str, dict[str, int]] = {}
    for sample_class in ("candidate", "no_candidate"):
        counts = Counter(row["codex_review_label"] for row in review_rows
                         if row["sample_class"] == sample_class)
        label_counts[sample_class] = dict(sorted(counts.items()))

    report = {
        "audit": "v1_478_api_candidate_boundary_review",
        "date": "2026-10-20",
        "method": (
            "For each pinned package and each candidate/no-candidate class, "
            "select the ten lowest SHA-256 keys of deduplicated public API "
            "docstring sentences containing 'will'. Keys bind package, "
            "document identity, and exact sentence. Sample generation and "
            "citations are checked against the complete v1_477 corpus hashes."),
        "label_protocol": (
            "Codex reviewed the exact cited sentence and extracted fields in "
            "one unblinded pass. Labels are single-rater development feedback, "
            "not independent validation and not a probability-sample estimate."),
        "limits": [
            "The two pinned package corpora are development data, not held-out publishers.",
            "The sample is deterministic but not a probability sample.",
            "A source sentence can contain relevant context outside its cited span.",
            "Review labels diagnose extraction boundaries; they do not validate a learned rule.",
            "No source candidate was accepted or installed as a rule.",
        ],
        "packages": package_summaries,
        "selected_rows": len(review_rows),
        "label_counts": label_counts,
        "rows": review_rows,
    }
    out = PROJECT / "experiments/reports/v1_478_api_candidate_boundary_review.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"Wrote {out.relative_to(PROJECT)} with {len(review_rows)} cited rows")
    print(json.dumps(label_counts, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
