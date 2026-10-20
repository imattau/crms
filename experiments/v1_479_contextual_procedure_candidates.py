"""Check review-only procedure candidates recovered from cited API headings."""
from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _cited_sentence_evidence, _cited_source_span
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_procedure_discovery import (
    nearest_parameter_heading,
    propose_contextual_procedure_phrase_candidates,
    propose_procedure_phrase_candidates,
)
from crms_research import CRMSResearchIndex, _sentence_spans
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def cited_sentence(index: CRMSResearchIndex, doc_id: str,
                   phrase: str) -> tuple[str, str, int]:
    hit = next((item for item in index.search(phrase, limit=20, context_chars=0)
                if item.document_id == doc_id
                and item.match_start is not None), None)
    require(hit is not None, f"retrieval missed {doc_id}: {phrase}")
    document = index.document(doc_id)
    span = next(((start, end) for start, end in _sentence_spans(document.text)
                 if start <= hit.match_start < end
                 and hit.match_end <= end), None)
    require(span is not None, f"search hit did not resolve to a sentence in {doc_id}")
    evidence = _cited_sentence_evidence(index, hit, span[0], span[1],
                                        hit.matched_terms)
    require(evidence is not None, f"citation failed for {doc_id}")
    return evidence["text"], evidence["citation"], span[0]


def check_contextual_claims() -> tuple[CRMSResearchIndex, dict[str, tuple[str, str]]]:
    index = CRMSResearchIndex()
    subjects: dict[str, tuple[str, str]] = {}
    cases = (
        ("numpy:ediff1d", "numpy", "ediff1d",
         "If necessary, will be flattened before the differences are taken.",
         "ary", "the ary parameter", "be flattened before the differences are taken"),
        ("pandas:read_html", "pandas", "read_html",
         "If a sequence of integers or a slice is given, will skip the rows indexed by that sequence.",
         "skiprows", "the skiprows parameter", "skip the rows indexed by that sequence"),
    )
    for doc_id, package, name, needle, expected_parameter, expected_subject, expected_predicate in cases:
        doc = inspect.getdoc(getattr(importlib.import_module(package), name))
        require(bool(doc), f"missing {package}.{name} API docstring")
        index.add_document(doc_id, f"{package}.{name} API reference", doc,
                           (f"https://numpy.org/doc/stable/reference/generated/numpy.{name}.html"
                            if package == "numpy" else
                            f"https://pandas.pydata.org/docs/reference/api/pandas.{name}.html"))
        sentence, source_citation, sentence_start = cited_sentence(
            index, doc_id, needle)
        parameter_span = nearest_parameter_heading(doc, sentence_start)
        require(parameter_span is not None,
                f"nearest parameter heading missing for {package}.{name}")
        parameter, context_start, context_end = parameter_span
        require(parameter == expected_parameter,
                f"wrong heading for {package}.{name}: {parameter}")
        hit = next(item for item in index.search(needle, limit=20, context_chars=0)
                   if item.document_id == doc_id and item.match_start is not None)
        context = _cited_source_span(index, hit, context_start, context_end)
        require(context is not None, f"heading citation failed for {package}.{name}")
        require(index.resolve_citation(source_citation) == sentence,
                f"claim citation did not resolve for {package}.{name}")
        require(index.resolve_citation(context["citation"]) == context["text"],
                f"context citation did not resolve for {package}.{name}")
        direct = propose_procedure_phrase_candidates(
            sentence, source_citation=source_citation)
        require(not direct,
                f"sentence-only parser unexpectedly supplied a subject for {package}.{name}")
        proposals = propose_contextual_procedure_phrase_candidates(
            sentence, source_citation=source_citation,
            context_text=context["text"], context_citation=context["citation"])
        require(len(proposals) == 1,
                f"context-aware parser did not produce one proposal: {proposals!r}")
        proposal = proposals[0]
        require(proposal.subject == expected_subject
                and proposal.predicate_phrase == expected_predicate
                and proposal.context_citation == context["citation"]
                and proposal.context_basis == "nearest_parameter_heading"
                and proposal.status == "needs_review",
                f"incorrect contextual claim for {package}.{name}: {proposal!r}")
        subjects[doc_id] = (proposal.subject, proposal.context_text or "")

    # A heading in a prior API section must not leak across a section boundary.
    ambiguous = ("Parameters\n----------\nary : array_like\n"
                 "Input array.\n\nReturns\n-------\n"
                 "If necessary, will be flattened.")
    section_start = ambiguous.index("If necessary")
    require(nearest_parameter_heading(ambiguous, section_start) is None,
            "parameter context leaked across Returns boundary")
    require(not propose_contextual_procedure_phrase_candidates(
        "If necessary, will be flattened.",
        source_citation="x#sha256=abc&chars=0:30",
        context_text="", context_citation=""),
        "context-free omitted subject should abstain")
    return index, subjects


def check_shared_subjects(index: CRMSResearchIndex) -> None:
    cases = (
        ("pandas:to_datetime", "pandas", "to_datetime",
         "``dayfirst=True`` is not strict, but will prefer to parse with day first.",
         "``dayfirst=True``", "prefer to parse with day first", True),
        ("pandas:crosstab", "pandas", "crosstab",
         "Here 'c' and 'f' are not represented in the data and will not be shown in the output because dropna is True by default.",
         "Here 'c' and 'f'", "be shown in the output", False),
    )
    for doc_id, package, name, needle, subject, predicate, positive in cases:
        doc = inspect.getdoc(getattr(importlib.import_module(package), name))
        require(bool(doc), f"missing {package}.{name} source")
        index.add_document(
            doc_id, f"{package}.{name} API reference", doc,
            f"https://pandas.pydata.org/docs/reference/api/pandas.{name}.html")
        sentence, citation, _ = cited_sentence(index, doc_id, needle)
        proposals = propose_procedure_phrase_candidates(
            sentence, source_citation=citation)
        require(len(proposals) == 1,
                f"shared-subject clause was not isolated: {proposals!r}")
        candidate = proposals[0]
        require(candidate.subject == subject
                and candidate.predicate_phrase == predicate
                and candidate.polarity is positive
                and candidate.context_basis == "shared_subject"
                and candidate.source_citation == citation
                and index.resolve_citation(citation) == sentence,
                f"wrong shared-subject result: {candidate!r}")
        if name == "crosstab":
            require(candidate.scope_notes[-1]
                    == "after: because dropna is True by default",
                    f"reason clause was not retained as scope: {candidate!r}")

    negative = "If the option is enabled, but will be handled later."
    require(not propose_procedure_phrase_candidates(
        negative, source_citation="x#sha256=abc&chars=0:50"),
        "shared subject should not be borrowed from a conditional prefix")


def check_fresh_chat(index: CRMSResearchIndex) -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-479-") as tmp:
        root = Path(tmp)
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
            input="/suggest-procedure-phrases flattened differences\n"
                  "/rules\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        require("the ary parameter" in process.stdout
                and "Subject context: ary : array_like" in process.stdout
                and "Context citation:" in process.stdout,
                f"fresh chat omitted contextual evidence:\n{process.stdout}")
        require("No transformation rules are committed yet." in process.stdout,
                "context-derived proposal changed the rule store")


def main() -> None:
    index, subjects = check_contextual_claims()
    check_shared_subjects(index)
    check_fresh_chat(index)
    print("PASS: omitted subjects recovered only from adjacent API parameter headings")
    print("PASS: claim and parameter-heading citations resolve independently")
    print("PASS: stale section context and context-free missing subjects abstain")
    print("PASS: simple coordinated predicates reuse only their explicit subject")
    print("PASS: fresh chat shows the inferred subject and context citation")
    print("PASS: contextual proposals remain review-only and do not change rules")
    print(f"CASES: {len(subjects)} parameter headings and 2 shared subjects; no held-out transfer claim")


if __name__ == "__main__":
    main()
