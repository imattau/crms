"""Verify the frozen Codex review sample against its source corpus.

Run directly with:
    python3 experiments/audits/v1_475_api_candidate_sample_review.py

The candidate outcomes and labels are frozen in the accompanying JSON report
from the pre-v1_476 grammar. This script validates package versions, corpus
fingerprints, exact source citations, and sample sentence hashes; it does not
rerun the current candidate generator or relabel the old sample.
"""
from __future__ import annotations

import hashlib
import importlib
from importlib import metadata
import inspect
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    report_path = PROJECT / "experiments/reports/v1_475_api_candidate_sample_review.json"
    baseline_path = PROJECT / "experiments/reports/v1_474_installed_api_docstring_fit.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    index = CRMSResearchIndex()

    for package_row in baseline["packages"]:
        package = package_row["package"]
        module = importlib.import_module(package)
        require(metadata.version(package) == package_row["version"],
                f"{package} version differs from the frozen baseline")
        template = {
            "numpy": "https://numpy.org/doc/stable/reference/generated/numpy.{name}.html",
            "pandas": "https://pandas.pydata.org/docs/reference/api/pandas.{name}.html",
        }[package]
        units = {}
        for export in sorted(set(getattr(module, "__all__", ()))):
            try:
                obj = getattr(module, export)
                doc = inspect.getdoc(obj)
            except Exception:
                continue
            if not callable(obj) or not doc or len(doc) < 80:
                continue
            key = (getattr(obj, "__module__", package),
                   getattr(obj, "__qualname__", export), doc)
            units.setdefault(key, (export, doc))

        corpus_digest = hashlib.sha256()
        for (module_name, qualified_name, doc), (export, _text) in sorted(
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
            index.add_document(
                document_id, f"{package} {export} API reference", doc,
                template.format(name=export))
        require(corpus_digest.hexdigest() == package_row["corpus_sha256"],
                f"{package} docstring corpus differs from the frozen sample")

    rows = report["review"]
    require(len(rows) == 40, "frozen reviewed sample size changed")
    for row in rows:
        sentence = index.resolve_citation(row["source_citation"])
        require(hashlib.sha256(sentence.encode("utf-8")).hexdigest()
                == row["sentence_sha256"],
                f"source sentence hash differs for {row['api_export']}")
        if row["sample_class"] == "candidate":
            require(bool(row.get("candidate_subject"))
                    and bool(row.get("candidate_predicate"))
                    and row["extraction_outcome"]
                        == "requires_source_context_or_repair",
                    f"candidate review record is incomplete: {row!r}")
        else:
            require(row["source_behavior_label"] == "potential_api_behavior",
                    f"non-candidate review record is incomplete: {row!r}")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
