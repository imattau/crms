"""Freeze a package-disjoint Pydantic API-docstring transfer sample.

This applies the spaCy dependency proposal path frozen before inspection of
Pydantic. It records both candidate and non-candidate sentences; no rule is
accepted or taught. It is a package-docstring transfer diagnostic, not a test
of the full online documentation site.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.metadata
import inspect
import io
import json
import pkgutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments" / "prototypes"))

import pydantic
import spacy

from procedure_discovery_spacy import (
    propose_dependency_procedure_phrase_candidates,
)
from crms_research import _sentence_spans


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_modules() -> list[object]:
    modules: list[object] = [pydantic]
    with contextlib.redirect_stdout(io.StringIO()):
        for info in pkgutil.walk_packages(
                pydantic.__path__, pydantic.__name__ + "."):
            if ".tests" in info.name or ".test" in info.name:
                continue
            try:
                modules.append(importlib.import_module(info.name))
            except Exception:
                # Scope is the set of installed modules that import cleanly.
                continue
    return modules


def proposal_record(candidate: object) -> dict[str, object]:
    return {
        "subject": candidate.subject,
        "predicate_phrase": candidate.predicate_phrase,
        "polarity": candidate.polarity,
        "quoted": candidate.quoted,
        "scope_notes": list(candidate.scope_notes),
        "assertion_status": candidate.assertion_status,
        "status": candidate.status,
    }


_CANDIDATE_REVIEW = {
    "pydantic._internal._dataclasses.patch_base_fields": "structurally_usable",
    "pydantic.MongoDsn": "structurally_usable",
    "pydantic.v1.Field": "boundary_error",
    "pydantic.NatsDsn": "context_needed",
    "pydantic.Field": "context_needed",
    "pydantic.v1.AmqpDsn": "boundary_error",
    "pydantic.field_serializer": "context_needed",
    "pydantic.model_serializer": "boundary_error",
    "pydantic.v1.generics.WeakKeyDictionary": "structurally_usable",
    "pydantic.TypeAdapter": "context_needed",
    "pydantic.Secret": "boundary_error",
    "pydantic.ImportString": "boundary_error",
    "pydantic.Tag": "context_needed",
    "pydantic._internal._discriminated_union.apply_discriminator": "context_needed",
    "pydantic._internal._model_construction.ABCMeta": "boundary_error",
    "pydantic.WrapSerializer": "context_needed",
    "pydantic.v1.schema.get_flat_models_from_field": "context_needed",
    "pydantic.SnowflakeDsn": "context_needed",
    "pydantic._internal._decorators.is_instance_method_from_sig": "context_needed",
    "pydantic._internal._typing_extra.try_eval_type": "context_needed",
}
_UNHANDLED_REVIEW = {
    "pydantic._internal._decorators.islice": "context_needed_behavior_claim",
    "pydantic._internal._dataclasses.FieldInfo": "not_target_claim",
    "pydantic.WithJsonSchema": "plausible_behavior_claim",
    "pydantic.v1.annotated_types.is_typeddict": "plausible_behavior_claim",
    "pydantic.v1.generics.get_caller_frame_info": "context_needed_behavior_claim",
    "pydantic._internal._core_utils.pps": "plausible_behavior_claim",
    "pydantic.ByteSize": "plausible_behavior_claim",
    "pydantic._internal._generate_schema.Fraction": "plausible_behavior_claim",
}


def main() -> None:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
    prototype_path = (PROJECT / "experiments" / "prototypes"
                      / "procedure_discovery_spacy.py")
    status_path = PROJECT / "crms_procedure_discovery.py"
    nlp = spacy.load("en_core_web_sm")
    modules = load_modules()
    seen_objects: set[int] = set()
    unit_count = sentence_count = will_count = 0
    candidate_rows: list[dict[str, object]] = []
    unhandled_rows: list[dict[str, object]] = []

    for module in modules:
        for name, obj in inspect.getmembers(module):
            if name.startswith("_") or not (
                    inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            try:
                doc = inspect.getdoc(obj)
            except Exception:
                continue
            if not doc or id(obj) in seen_objects:
                continue
            seen_objects.add(id(obj))
            unit_count += 1
            api_unit = f"{module.__name__}.{name}"
            source_hash = digest(doc)
            for start, end in _sentence_spans(doc):
                sentence = doc[start:end].strip()
                if not sentence:
                    continue
                sentence_count += 1
                if "will" not in sentence.casefold():
                    continue
                will_count += 1
                citation = (
                    f"pydantic:{api_unit}#sha256={source_hash}"
                    f"&chars={start}:{end}")
                candidates = propose_dependency_procedure_phrase_candidates(
                    nlp, sentence, source_citation=citation)
                row: dict[str, object] = {
                    "sample_key": digest(
                        f"{api_unit}\0{start}\0{sentence}"),
                    "api_unit": api_unit,
                    "sentence_start": start,
                    "sentence_end": end,
                    "docstring_sha256": source_hash,
                    "source_citation": citation,
                    "sentence": sentence,
                }
                if candidates:
                    row["proposals"] = [proposal_record(candidate)
                                         for candidate in candidates]
                    candidate_rows.append(row)
                else:
                    unhandled_rows.append(row)

    def sample(rows: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
        selected: list[dict[str, object]] = []
        seen_units: set[str] = set()
        seen_text: set[str] = set()
        for row in sorted(rows, key=lambda item: str(item["sample_key"])):
            unit = str(row["api_unit"])
            normalized = " ".join(str(row["sentence"]).casefold().split())
            if unit in seen_units or normalized in seen_text:
                continue
            seen_units.add(unit)
            seen_text.add(normalized)
            selected.append(row)
            if len(selected) == limit:
                break
        return selected

    proposal_sample = sample(candidate_rows, 20)
    unhandled_sample = sample(unhandled_rows, 20)
    for row in proposal_sample:
        row["manual_label"] = _CANDIDATE_REVIEW.get(
            str(row["api_unit"]), "unreviewed")
    for row in unhandled_sample:
        row["manual_label"] = _UNHANDLED_REVIEW.get(
            str(row["api_unit"]), "unreviewed")
    candidate_labels: dict[str, int] = {}
    for row in proposal_sample:
        label = str(row["manual_label"])
        candidate_labels[label] = candidate_labels.get(label, 0) + 1
    unhandled_labels: dict[str, int] = {}
    for row in unhandled_sample:
        label = str(row["manual_label"])
        unhandled_labels[label] = unhandled_labels.get(label, 0) + 1
    report = {
        "audit": "v1_489",
        "purpose": "package-disjoint proposal transfer diagnostic",
        "package": "Pydantic",
        "package_version": pydantic.__version__,
        "installed_package_license": importlib.metadata.metadata(
            "pydantic").get("License-Expression")
            or importlib.metadata.metadata("pydantic").get("License"),
        "scope": (
            "Public importable functions and classes with docstrings in the "
            "installed package; not the complete online documentation site."),
        "frozen_method_revision": revision,
        "method_sha256": {
            "dependency_prototype": digest(prototype_path.read_text(
                encoding="utf-8")),
            "assertion_status": digest(status_path.read_text(encoding="utf-8")),
        },
        "parser": {
            "library": "spaCy",
            "version": spacy.__version__,
            "model": "en_core_web_sm",
            "model_version": importlib.metadata.version("en-core-web-sm"),
        },
        "counts": {
            "importable_modules": len(modules),
            "public_api_docstrings": unit_count,
            "sentence_spans": sentence_count,
            "sentences_with_will": will_count,
            "sentences_with_candidates": len(candidate_rows),
            "sentences_without_candidates": len(unhandled_rows),
            "candidate_sample_size": len(proposal_sample),
            "unhandled_sample_size": len(unhandled_sample),
        },
        "sampling": (
            "For candidate and non-candidate rows separately, sort by "
            "SHA-256(api unit, sentence offset, text), then keep the first "
            "row per API unit and exact normalized sentence, up to 20."),
        "proposal_sample": proposal_sample,
        "unhandled_sample": unhandled_sample,
        "manual_review": {
            "reviewer": "Codex",
            "candidate_sample_labels": candidate_labels,
            "unhandled_sample_labels": unhandled_labels,
            "candidate_label_definitions": {
                "structurally_usable": "Sentence citation alone gives a coherent subject, relation, and scope for review.",
                "context_needed": "Claim may be valid, but a pronoun, omitted subject, parameter heading, or antecedent needs cited context.",
                "boundary_error": "Extracted fields misbound the subject or predicate, merged clauses, or included markup/example debris.",
            },
            "interpretation": (
                "Single-rater review of a frozen sample; labels are not "
                "precision or recall estimates."),
        },
        "limitations": [
            "Package docstrings are not the complete publisher documentation.",
            "The sample is frozen before semantic review; candidate count is not precision.",
            "This evaluates one construction family containing 'will', not general source learning.",
            "All proposals remain review-only and no rule store is modified.",
        ],
    }
    out = PROJECT / "experiments" / "reports" / "v1_489_pydantic_dependency_transfer.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps(report["counts"], indent=2))
    print("manual review:", json.dumps(report["manual_review"]))


if __name__ == "__main__":
    main()
