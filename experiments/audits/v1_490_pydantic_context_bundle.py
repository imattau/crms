"""Test separately cited source context for frozen Pydantic claim candidates.

This is a review-only analysis of the v1_489 sample. Context is attached as
separate evidence spans and never changes candidate status or teaches a rule.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import inspect
import io
import json
import pkgutil
import re
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
import pydantic
from crms_research import _sentence_spans

SOURCE_REPORT = PROJECT / "experiments/reports/v1_489_pydantic_dependency_transfer.json"
OUTPUT_REPORT = PROJECT / "experiments/reports/v1_490_pydantic_context_bundle.json"
_CONTEXT_REVIEW = {
    "pydantic.NatsDsn": "metadata_only_anchor",
    "pydantic.Field": "does_not_fix_in_sentence_boundary_error",
    "pydantic.field_serializer": "no_external_context_needed_for_subject",
    "pydantic.TypeAdapter": "no_external_context_needed_for_subject",
    "pydantic.Tag": "context_supplies_failing_antecedent",
    "pydantic._internal._discriminated_union.apply_discriminator": "no_external_context_needed_for_subject",
    "pydantic.WrapSerializer": "context_does_not_resolve_it",
    "pydantic.v1.schema.get_flat_models_from_field": "context_supplies_operation_and_conditions",
    "pydantic.SnowflakeDsn": "metadata_only_anchor",
    "pydantic._internal._decorators.is_instance_method_from_sig": "metadata_only_anchor",
    "pydantic._internal._typing_extra.try_eval_type": "context_supplies_value_antecedent",
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_docs() -> dict[str, str]:
    modules: list[object] = [pydantic]
    with contextlib.redirect_stdout(io.StringIO()):
        for info in pkgutil.walk_packages(
                pydantic.__path__, pydantic.__name__ + "."):
            if ".tests" in info.name or ".test" in info.name:
                continue
            try:
                modules.append(importlib.import_module(info.name))
            except Exception:
                continue
    docs: dict[str, str] = {}
    seen: set[int] = set()
    for module in modules:
        for name, obj in inspect.getmembers(module):
            if name.startswith("_") or not (
                    inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            try:
                doc = inspect.getdoc(obj)
            except Exception:
                continue
            if doc and id(obj) not in seen:
                seen.add(id(obj))
                docs[f"{module.__name__}.{name}"] = doc
    return docs


def citation(api_unit: str, doc: str, start: int, end: int) -> str:
    return (f"pydantic:{api_unit}#sha256={digest(doc)}"
            f"&chars={start}:{end}")


def bundle(api_unit: str, doc: str, anchor_start: int,
           anchor_end: int) -> list[dict[str, object]]:
    """Return adjacent same-paragraph sentences and nearest section heading."""
    spans = _sentence_spans(doc)
    anchor_index = next((i for i, (start, end) in enumerate(spans)
                         if start <= anchor_start and anchor_end <= end), None)
    if anchor_index is None:
        raise ValueError(f"anchor is not an exact sentence span: {api_unit}")
    prior_break = doc.rfind("\n\n", 0, anchor_start)
    para_start = prior_break + 2 if prior_break >= 0 else 0
    para_end = doc.find("\n\n", anchor_end)
    if para_end < 0:
        para_end = len(doc)
    items: list[dict[str, object]] = []
    paragraph = doc[para_start:para_end]
    if len(paragraph) <= 1800:
        items.append({
            "kind": "paragraph_context",
            "text": paragraph,
            "citation": citation(api_unit, doc, para_start, para_end),
        })
    else:
        # Long API sections are represented as two bounded, separately cited
        # windows. Never silently truncate a citation or combine offset ranges.
        before_start = max(para_start, anchor_start - 500)
        after_end = min(para_end, anchor_end + 500)
        if before_start < anchor_start:
            items.append({
                "kind": "preceding_context_window",
                "text": doc[before_start:anchor_start],
                "citation": citation(api_unit, doc, before_start, anchor_start),
            })
        if anchor_end < after_end:
            items.append({
                "kind": "following_context_window",
                "text": doc[anchor_end:after_end],
                "citation": citation(api_unit, doc, anchor_end, after_end),
            })
    for index in (anchor_index - 1, anchor_index + 1):
        if not 0 <= index < len(spans):
            continue
        start, end = spans[index]
        if start < para_start or end > para_end:
            continue
        items.append({
            "kind": "adjacent_sentence",
            "text": doc[start:end],
            "citation": citation(api_unit, doc, start, end),
        })
    # Keep the closest reStructuredText/Markdown section heading distinct.
    prior = doc[:anchor_start]
    heading_matches = list(re.finditer(
        r"(?m)^(?P<title>[^\n]{1,100})\n(?P<underline>[-=~^#+*]{3,})\s*$",
        prior))
    heading_matches = [match for match in heading_matches
                       if match.start() >= max(0, anchor_start - 2400)
                       and match.group("title").strip()
                       and not any(char in match.group("title")
                                   for char in "{}[]`\\")]
    markdown_heading = list(re.finditer(
        r"(?m)^(?P<title>#{1,6} [^\n]{1,100})$", prior))
    markdown_heading = [match for match in markdown_heading
                        if match.start() >= max(0, anchor_start - 2400)]
    if markdown_heading and (not heading_matches or
                             markdown_heading[-1].start() > heading_matches[-1].start()):
        match = markdown_heading[-1]
        heading_matches = [match]
        start, end = match.start("title"), match.end("title")
    else:
        start = end = -1
    if heading_matches:
        match = heading_matches[-1]
        if start < 0:
            start, end = match.start("title"), match.end("underline")
        items.append({
            "kind": "section_heading",
            "text": doc[start:end],
            "citation": citation(api_unit, doc, start, end),
        })
    items.append({
        "kind": "api_unit_metadata",
        "text": api_unit,
        "citation": None,
        "note": "symbol identity from the imported package, not a cited claim",
    })
    return items


def main() -> None:
    source = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))
    docs = load_docs()
    rows = []
    for row in source["proposal_sample"]:
        if row.get("manual_label") != "context_needed":
            continue
        unit = row["api_unit"]
        doc = docs[unit]
        start, end = int(row["sentence_start"]), int(row["sentence_end"])
        exact = doc[start:end]
        if exact.strip() != row["sentence"].strip():
            raise ValueError(f"source sentence mismatch for {unit}")
        for item in bundle(unit, doc, start, end):
            if item.get("citation"):
                cited = str(item["citation"])
                cited_start, cited_end = map(
                    int, cited.rsplit("&chars=", 1)[1].split(":", 1))
                if (doc[cited_start:cited_end] != item["text"]
                        or digest(doc) not in cited):
                    raise ValueError(f"context citation mismatch for {unit}")
        rows.append({
            "api_unit": unit,
            "anchor_sentence": row["sentence"],
            "anchor_citation": row["source_citation"],
            "proposal": row["proposals"],
            "original_review_label": row["manual_label"],
            "context_review": _CONTEXT_REVIEW[unit],
            "context_bundle": bundle(unit, doc, start, end),
        })
    report = {
        "audit": "v1_490",
        "purpose": "review-only source-context bundling probe",
        "source_audit": "v1_489",
        "package": "Pydantic",
        "package_version": pydantic.__version__,
        "sample_size": len(rows),
        "context_review_counts": {
            label: sum(row["context_review"] == label for row in rows)
            for label in sorted(set(_CONTEXT_REVIEW.values()))
        },
        "context_reviewer": "Codex, single rater",
        "context_review_definitions": {
            "context_supplies_failing_antecedent": "Newly cited adjacent source text identifies what 'failing to do so' refers to.",
            "context_supplies_operation_and_conditions": "Newly cited paragraph gives the operation description and the nested field conditions.",
            "context_supplies_value_antecedent": "Newly cited Args text binds 'it' to the value parameter.",
            "metadata_only_anchor": "Package symbol identity may help orient a reader but does not independently cite the identity-to-claim relation.",
            "does_not_fix_in_sentence_boundary_error": "The problematic role is already in the anchor sentence; more context does not repair the extraction boundary.",
            "context_does_not_resolve_it": "The surrounding cited attribute text does not identify the pronoun antecedent.",
            "no_external_context_needed_for_subject": "The anchor sentence itself supplies the candidate subject; the previous context-needed label appears overcautious for subject resolution.",
        },
        "bundle_policy": (
            "Attach immediate same-paragraph sentence neighbors, the nearest "
            "preceding section heading, and package API-unit metadata. Every "
            "text span is separately cited to the original docstring hash and "
            "character offsets. No merging, inference, or rule acceptance."),
        "rows": rows,
        "limitations": [
            "Reuses a small single-rater development sample; not transfer evidence.",
            "Nearby text may be irrelevant or insufficient to resolve an antecedent.",
            "API-unit identity is metadata, not sentence-level source evidence.",
            "Candidate extraction and semantic correctness are unchanged.",
        ],
    }
    OUTPUT_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(f"wrote {OUTPUT_REPORT}")
    print(f"bundled {len(rows)} previously context-needed candidates")
    for row in rows:
        print("\n" + row["api_unit"] + ": " + row["anchor_sentence"])
        for item in row["context_bundle"]:
            print(f"  {item['kind']}: {item['text']}")


if __name__ == "__main__":
    main()
