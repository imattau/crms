"""Measure the frozen procedure-phrase grammar on SciPy API docstrings.

This is a corpus-fit audit, not a precision/recall or transfer benchmark. It
records every inspected docstring sentence containing ``will`` and a
deterministic, one-per-API-unit sample of sentences that the frozen parser
does not handle.
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

import scipy

from crms_procedure_discovery import (
    nearest_parameter_heading,
    propose_contextual_procedure_phrase_candidates,
    propose_procedure_phrase_candidates,
)
from crms_research import _sentence_spans


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def package_modules() -> list[object]:
    modules: list[object] = [scipy]
    with contextlib.redirect_stdout(io.StringIO()):
        for info in pkgutil.walk_packages(
                scipy.__path__, scipy.__name__ + "."):
            if ".tests" in info.name or ".conftest" in info.name:
                continue
            try:
                modules.append(importlib.import_module(info.name))
            except Exception:
                # The audit is limited to importable installed API modules.
                continue
    return modules


def main() -> None:
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"

    module_list = package_modules()
    inspected: set[int] = set()
    unit_count = sentence_count = will_count = direct_count = contextual_count = 0
    candidate_rows: list[dict[str, object]] = []
    unhandled_rows: list[dict[str, object]] = []
    for module in module_list:
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
            for start, end in _sentence_spans(doc):
                sentence = doc[start:end].strip()
                if not sentence:
                    continue
                sentence_count += 1
                if "will" not in sentence.casefold():
                    continue
                will_count += 1
                source_citation = (
                    f"{unit}#sha256={digest(doc)}&chars={start}:{end}")
                direct = propose_procedure_phrase_candidates(
                    sentence, source_citation=source_citation)
                direct_count += bool(direct)
                heading = nearest_parameter_heading(doc, start)
                contextual = ()
                if heading is not None:
                    _, context_start, context_end = heading
                    context_text = doc[context_start:context_end]
                    contextual = propose_contextual_procedure_phrase_candidates(
                        sentence, source_citation=source_citation,
                        context_text=context_text,
                        context_citation=(
                            f"{unit}#sha256={digest(doc)}&chars="
                            f"{context_start}:{context_end}"))
                contextual_count += bool(contextual)
                row_key = digest(f"{unit}\0{start}\0{sentence}")
                row: dict[str, object] = {
                    "sample_key": row_key,
                    "api_unit": unit,
                    "sentence_start": start,
                    "sentence_end": end,
                    "docstring_sha256": digest(doc),
                    "source_citation": source_citation,
                    "sentence": sentence,
                }
                proposals = list(direct) + list(contextual)
                if proposals:
                    proposal_rows = {}
                    for proposal in proposals:
                        fields = {
                            "subject": proposal.subject,
                            "predicate_phrase": proposal.predicate_phrase,
                            "polarity": proposal.polarity,
                            "scope_notes": list(proposal.scope_notes),
                            "context_basis": proposal.context_basis,
                            "status": proposal.status,
                        }
                        proposal_rows[json.dumps(fields, sort_keys=True)] = fields
                    row["proposals"] = list(proposal_rows.values())
                    candidate_rows.append(row)
                else:
                    unhandled_rows.append(row)

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

    candidate_sample = select_sample(candidate_rows)
    unhandled_sample = select_sample(unhandled_rows)

    try:
        from importlib.metadata import metadata
        license_name = metadata("scipy").get("License-Expression") or metadata(
            "scipy").get("License")
    except Exception:
        license_name = None

    report = {
        "audit": "v1_486",
        "purpose": "frozen grammar corpus-fit check only",
        "package": "SciPy",
        "package_version": scipy.__version__,
        "package_license_metadata": license_name,
        "method_revision": revision,
        "method": [
            "propose_procedure_phrase_candidates",
            "nearest_parameter_heading",
            "propose_contextual_procedure_phrase_candidates",
        ],
        "corpus_scope": (
            "Importable public functions and classes with docstrings in the "
            "installed scipy package; repeated Python object identities are "
            "counted once. Not the complete online documentation corpus."),
        "counts": {
            "importable_modules": len(module_list),
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
            "For proposals and non-proposals separately, sort rows by "
            "SHA-256(api_unit, sentence offset, text); keep the first row per "
            "API unit and exact normalized sentence until 20 rows are selected."),
        "candidate_sample": candidate_sample,
        "unhandled_sample": unhandled_sample,
        "manual_review": {
            "reviewer": "Codex",
            "candidate_rows_promotion_ready": 0,
            "candidate_rows_reviewed": len(candidate_sample),
            "candidate_observation": (
                "Every sampled field set needs human review before promotion; "
                "the sample contains malformed or overlong subjects, lost "
                "conditions/qualifiers, clause-boundary errors, or claims "
                "about documentation rather than API behavior."),
            "unhandled_rows_plausible_behavior_or_property": 13,
            "unhandled_rows_reviewed": len(unhandled_sample),
            "unhandled_observation": (
                "The frozen grammar missed several ordinary API claims, "
                "including zero-size-batch errors, output behavior, option "
                "conditions, warning behavior, and parameter forwarding."),
            "method": "single-rater, unblinded review of hash-selected rows",
            "interpretation": (
                "These are diagnostic sample counts, not estimates of "
                "precision or recall."),
        },
        "limitations": [
            "SciPy docstrings are an adjacent technical corpus, not an independent publisher-level test of complete documentation pages.",
            "The sample covers only sentences containing the token 'will'; it does not measure other constructions.",
            "The sample is a single-rater diagnostic and not a precision or recall estimate.",
            "No source claims are accepted or learned by this audit.",
        ],
    }
    out = PROJECT / "experiments" / "reports" / "v1_486_scipy_will_claim_fit.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps(report["counts"], indent=2))
    print("manual review: 0/20 candidate field sets promotion-ready; "
          "13/20 unhandled rows appear to describe behavior or properties")
    print(f"method revision: {revision}")


if __name__ == "__main__":
    main()
