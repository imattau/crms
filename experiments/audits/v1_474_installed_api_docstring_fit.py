"""Read-only corpus-fit audit over installed NumPy and pandas API docs.

Run directly with:
    python3 experiments/audits/v1_474_installed_api_docstring_fit.py

This audit requires the package versions recorded in its JSON output. It scans
complete public callable docstrings, never persists the source text, and does
not accept candidates or modify any CRMS store. The docstrings are API
reference units, not complete documentation websites or independent publishers.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib
from importlib import metadata
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_research import CRMSResearchIndex, _sentence_spans


PACKAGES = {
    "numpy": {
        "template": "https://numpy.org/doc/stable/reference/generated/numpy.{name}.html",
    },
    "pandas": {
        "template": "https://pandas.pydata.org/docs/reference/api/pandas.{name}.html",
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def scan_package(package: str, url_template: str) -> dict[str, object]:
    module = importlib.import_module(package)
    distribution = metadata.distribution(package)
    license_label = (distribution.metadata.get("License-Expression")
                     or (distribution.metadata.get("License") or "").splitlines()[0]
                     or None)
    exports = sorted(set(getattr(module, "__all__", ())))
    units: dict[tuple[str, str, str], tuple[str, str, str]] = {}

    for export in exports:
        try:
            obj = getattr(module, export)
            doc = inspect.getdoc(obj)
        except Exception:
            continue
        if not callable(obj) or not doc or len(doc) < 80:
            continue
        module_name = getattr(obj, "__module__", package)
        qualified_name = getattr(obj, "__qualname__", export)
        key = (module_name, qualified_name, doc)
        if key in units:
            continue
        url = url_template.format(name=export)
        units[key] = (export, doc, url)

    index = CRMSResearchIndex()
    prepared = []
    corpus_digest = hashlib.sha256()
    sentence_total = 0

    for (module_name, qualified_name, doc), (export, _text, url) in sorted(
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
        title = f"{package} {export} API reference"
        index.add_document(document_id, title, doc, url)
        spans = _sentence_spans(doc)
        sentence_total += len(spans)
        prepared.append((document_id, export, doc, digest, url, spans))

    candidates = []
    for document_id, export, doc, digest, url, spans in prepared:
        for start, end in spans:
            sentence = doc[start:end]
            citation = (f"{document_id}#sha256={digest}"
                        f"&chars={start}:{end}")
            proposals = propose_procedure_phrase_candidates(
                sentence, source_citation=citation)
            for proposal in proposals:
                require(index.resolve_citation(citation) == sentence,
                        f"citation failed to resolve for {document_id}")
                candidates.append((export, url, proposal))

    normalized = Counter(
        (" ".join(proposal.subject.casefold().split()),
         " ".join(proposal.predicate_phrase.casefold().split()),
         proposal.polarity, proposal.quoted, proposal.assertion_status)
        for _, _, proposal in candidates)
    candidate_exports = {export for export, _, _ in candidates}
    top_patterns = [
        {
            "count": count,
            "subject": subject,
            "predicate": predicate,
            "positive": polarity,
            "quoted": quoted,
            "assertion_status": assertion_status,
        }
        for ((subject, predicate, polarity, quoted, assertion_status), count)
        in normalized.most_common(12)
    ]

    return {
        "package": package,
        "version": distribution.version,
        "license_label": license_label,
        "public_callable_docstrings": len(prepared),
        "source_sentences": sentence_total,
        "candidate_sentences": len(candidates),
        "candidate_api_units": len(candidate_exports),
        "unique_normalized_candidates": len(normalized),
        "corpus_sha256": corpus_digest.hexdigest(),
        "top_repeated_patterns": top_patterns,
    }


def replay_numpy_add_in_fresh_chat() -> dict[str, object]:
    import numpy as np

    from crms_knowledge import CRMSKnowledgeBase
    from crms_math import CRMSMath
    from crms_model import CRMSModel
    from crms_translation import CRMSTranslation

    doc = inspect.getdoc(np.add)
    require(bool(doc), "installed numpy.add docstring is unavailable")
    sentence = next((doc[start:end] for start, end in _sentence_spans(doc)
                     if "out" in doc[start:end].casefold()
                     and "ufunc result" in doc[start:end].casefold()
                     and "will be set" in doc[start:end].casefold()), None)
    require(sentence is not None,
            "numpy.add docstring lacks the expected out-array statement")

    digest = hashlib.sha256(doc.encode("utf-8")).hexdigest()
    offset = doc.index(sentence)
    citation = (f"numpy:add#sha256={digest}"
                f"&chars={offset}:{offset + len(sentence)}")
    candidates = propose_procedure_phrase_candidates(
        sentence, source_citation=citation)
    require(len(candidates) == 1,
            f"expected one numpy.add candidate, got {candidates!r}")
    candidate = candidates[0]

    with tempfile.TemporaryDirectory(prefix="crms-v1-474-chat-") as tmp:
        root = Path(tmp)
        index = CRMSResearchIndex()
        index.add_document(
            "numpy:add", "numpy.add API reference", doc,
            "https://numpy.org/doc/stable/reference/generated/numpy.add.html")
        require(index.resolve_citation(citation) == sentence,
                "numpy.add citation failed to resolve")
        index.save(root / "index.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSMath().save(root / "math.json")
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSTranslation().save(root / "translations.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--math", str(root / "math.json"),
            "--rules", str(root / "rules.json"),
            "--translations", str(root / "translations.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rule-session.json"),
        ]
        process = subprocess.run(
            command,
            input="/suggest-procedure-phrases out array ufunc result\n"
                  "/rules\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        require(candidate.predicate_phrase in process.stdout
                and sentence in process.stdout,
                "fresh chat did not show the candidate and exact evidence")
        require("No transformation rules are committed yet." in process.stdout,
                "review-only source candidate changed the rule store")
        subject_displayed = (
            f"{candidate.subject} — {candidate.predicate_phrase}" in process.stdout)

    return {
        "source": "numpy.add API docstring",
        "query": "/suggest-procedure-phrases out array ufunc result",
        "fresh_process_succeeded": True,
        "candidate_subject": candidate.subject,
        "candidate_predicate": candidate.predicate_phrase,
        "candidate_scope_notes": list(candidate.scope_notes),
        "renderer_displayed_subject": subject_displayed,
        "citation_resolved": True,
        "rule_store_unchanged": True,
    }


def main() -> None:
    report = {
        "audit": "v1_474_installed_api_docstring_fit",
        "method": (
            "Scan complete public callable docstrings for the frozen, "+
            "review-only subject-will-predicate grammar. Store no source "+
            "text; verify each generated sentence citation against the "+
            "in-memory research index."
        ),
        "limits": [
            "API docstrings are individual reference units, not complete documentation sites.",
            "The two packages are not independent publishers for transfer claims.",
            "Candidate counts do not measure semantic precision or useful rule yield.",
            "This audit does not label candidates, install rules, or validate learned mappings.",
            "Results depend on installed package versions and their published docstrings.",
        ],
        "packages": [
            scan_package(package, config["template"])
            for package, config in PACKAGES.items()
        ],
        "chat_replay": replay_numpy_add_in_fresh_chat(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
