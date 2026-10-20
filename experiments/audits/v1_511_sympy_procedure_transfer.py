"""Freeze a new-package transfer sample for source procedure candidates.

This audit mirrors the frozen SciPy probe but targets installed SymPy API
docstrings that have not been used as development material. It writes a
manifest before manual review; it is a package-level diagnostic, not an
estimate of precision/recall or a full documentation-publisher test.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import inspect
import io
import json
import pkgutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

import sympy

from crms_procedure_discovery import (
    nearest_parameter_heading,
    propose_contextual_procedure_phrase_candidates,
    propose_procedure_phrase_candidates,
)
from crms_research import _sentence_spans


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def package_modules() -> list[object]:
    modules: list[object] = [sympy]
    with contextlib.redirect_stdout(io.StringIO()):
        for info in pkgutil.walk_packages(
                sympy.__path__, sympy.__name__ + "."):
            if ".tests" in info.name or ".conftest" in info.name:
                continue
            try:
                modules.append(importlib.import_module(info.name))
            except Exception:
                continue
    return modules


def select_sample(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    seen_units: set[str] = set()
    seen_text: set[str] = set()
    for row in sorted(rows, key=lambda item: str(item["sample_key"])):
        unit = str(row["api_unit"])
        text_key = " ".join(str(row["sentence"]).casefold().split())
        if unit in seen_units or text_key in seen_text:
            continue
        seen_units.add(unit)
        seen_text.add(text_key)
        selected.append(row)
        if len(selected) == 20:
            break
    return selected


def main() -> None:
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"

    modules = package_modules()
    inspected: set[int] = set()
    unit_count = sentence_count = will_count = direct_count = 0
    contextual_count = 0
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
            if not doc or id(obj) in inspected:
                continue
            inspected.add(id(obj))
            unit_count += 1
            unit = f"{module.__name__}.{name}"
            doc_hash = digest(doc)
            for start, end in _sentence_spans(doc):
                sentence = doc[start:end].strip()
                if not sentence:
                    continue
                sentence_count += 1
                if "will" not in sentence.casefold():
                    continue
                will_count += 1
                citation = (
                    f"{unit}#sha256={doc_hash}&chars={start}:{end}")
                direct = propose_procedure_phrase_candidates(
                    sentence, source_citation=citation)
                direct_count += bool(direct)
                contextual = ()
                heading = nearest_parameter_heading(doc, start)
                if heading is not None:
                    _name, context_start, context_end = heading
                    contextual = propose_contextual_procedure_phrase_candidates(
                        sentence, source_citation=citation,
                        context_text=doc[context_start:context_end],
                        context_citation=(
                            f"{unit}#sha256={doc_hash}&chars="
                            f"{context_start}:{context_end}"))
                contextual_count += bool(contextual)
                row: dict[str, object] = {
                    "sample_key": digest(f"{unit}\0{start}\0{sentence}"),
                    "api_unit": unit,
                    "sentence_start": start,
                    "sentence_end": end,
                    "docstring_sha256": doc_hash,
                    "source_citation": citation,
                    "sentence": sentence,
                }
                proposals = list(direct) + list(contextual)
                if proposals:
                    fields_by_key = {}
                    for proposal in proposals:
                        fields = {
                            "subject": proposal.subject,
                            "predicate_phrase": proposal.predicate_phrase,
                            "polarity": proposal.polarity,
                            "scope_notes": list(proposal.scope_notes),
                            "context_basis": proposal.context_basis,
                            "status": proposal.status,
                        }
                        fields_by_key[json.dumps(fields, sort_keys=True)] = fields
                    row["proposals"] = list(fields_by_key.values())
                    candidate_rows.append(row)
                else:
                    unhandled_rows.append(row)

    candidate_sample = select_sample(candidate_rows)
    unhandled_sample = select_sample(unhandled_rows)
    try:
        from importlib.metadata import metadata
        license_metadata = metadata("sympy").get("License-Expression") or metadata(
            "sympy").get("License")
    except Exception:
        license_metadata = None

    report = {
        "audit": "v1_511",
        "purpose": "frozen new-package transfer diagnostic; no source claims accepted",
        "package": "SymPy",
        "package_version": sympy.__version__,
        "package_license_metadata": license_metadata,
        "method_revision": revision,
        "method": [
            "propose_procedure_phrase_candidates",
            "nearest_parameter_heading",
            "propose_contextual_procedure_phrase_candidates",
        ],
        "corpus_scope": (
            "Importable public functions and classes with docstrings in the "
            "installed sympy package; repeated Python object identities are "
            "counted once. This is not the complete online documentation."),
        "counts": {
            "importable_modules": len(modules),
            "api_units_with_docstrings": unit_count,
            "sentences": sentence_count,
            "sentences_containing_will": will_count,
            "sentences_with_direct_proposal": direct_count,
            "sentences_with_parameter_context_proposal": contextual_count,
            "sentences_with_any_proposal": len(candidate_rows),
            "unhandled_will_sentences": len(unhandled_rows),
            "candidate_sample_size": len(candidate_sample),
            "unhandled_sample_size": len(unhandled_sample),
        },
        "sample_selection": (
            "Separately sort candidate and unhandled rows by SHA-256 of API "
            "unit, sentence offset, and text; keep the first row per API unit "
            "and normalized sentence, up to 20 per group."),
        "candidate_sample": candidate_sample,
        "unhandled_sample": unhandled_sample,
        "manual_review": None,
        "limitations": [
            "This is a package-level sample, not a complete documentation-publisher test.",
            "Only sentence spans containing 'will' are in scope.",
            "The deterministic sample is diagnostic, not a precision/recall estimate.",
            "The method was not changed in response to this sample.",
        ],
    }
    out = PROJECT / "experiments" / "reports" / "v1_511_sympy_procedure_transfer.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"SymPy {sympy.__version__}: {unit_count} API docstrings, "
          f"{will_count} 'will' spans, {len(candidate_rows)} proposals, "
          f"{len(unhandled_rows)} unhandled; frozen samples "
          f"{len(candidate_sample)}/{len(unhandled_sample)}")
    print(f"Wrote {out.relative_to(PROJECT)}")


if __name__ == "__main__":
    main()
