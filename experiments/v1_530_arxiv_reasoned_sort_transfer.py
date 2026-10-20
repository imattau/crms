"""Transfer a reviewed relation rule and learned sort to arXiv metadata.

The task joins source-backed primary-category and publication-year fields,
then sorts only years supported by verified proofs. The input index contains
arXiv bibliographic metadata with a stated CC0 metadata license; it does not
contain or license the papers themselves.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v1_500_learned_and_reasoned_composition import learn_components
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_research import CRMSSQLiteResearchIndex, SearchHit
from crms_rule_proof import verify_inference_proof
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = PROJECT / "data" / "crms_arxiv_cc0_ccby.sqlite"
REPORT = PROJECT / "experiments" / "reports" / "v1_530_arxiv_reasoned_sort_transfer.json"
RULE_ID = "primary-category-publication-year"
RELATION = "has primary category papers from"
REQUESTS = (
    "From values 2020 and 2019, keep only the values that cs.CL has primary "
    "category papers from, then sort the list.",
    "Filter 2020 and 2019 to values cs.CL has primary category papers from, "
    "then sort the list.",
)
UNKNOWN_REQUEST = (
    "From values 2020, 2019, and 2018, keep only the values that cs.CL has "
    "primary category papers from, then sort the list."
)
RECORDS = (
    # split, arXiv id, primary category, publication year
    ("train", "arxiv:1901.06261v1", "cs.LG", "2019"),
    ("train", "arxiv:1805.11996v3", "cs.SE", "2018"),
    ("holdout", "arxiv:1905.03362v1", "cs.AI", "2019"),
    ("holdout", "arxiv:2005.09885v1", "math.CO", "2020"),
    ("evaluation", "arxiv:1904.07904v1", "cs.CL", "2019"),
    ("evaluation", "arxiv:2005.11313v1", "cs.CL", "2020"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_claim(source: CRMSSQLiteResearchIndex,
              copied_source: CRMSSQLiteResearchIndex,
              knowledge: CRMSKnowledgeBase, copied_documents: set[str], *,
              split: str, document_id: str, text_span: str,
              triples: tuple[tuple[str, str, str], ...]) -> list[str]:
    source_document = source.document(document_id)
    require(text_span in source_document.text,
            f"arXiv metadata span changed: {document_id}: {text_span!r}")
    local_id = f"{split}:{document_id}"
    if local_id not in copied_documents:
        copied_source.add_document(local_id, source_document.title,
                                   source_document.text,
                                   source_document.location)
        copied_documents.add(local_id)
    start = source_document.text.index(text_span)
    hit = SearchHit(local_id, source_document.title, source_document.location,
                    1.0, text_span, start, start + len(text_span), ())
    citations: list[str] = []
    for subject, relation, obj in triples:
        fact = knowledge.add_fact_from_hit(
            subject, relation, obj, copied_source, hit)
        citations.extend(fact.sources)
    return sorted(set(citations))


def run_chat(root: Path, knowledge_path: Path, procedure_path: Path,
             source_path: Path, lines: tuple[str, ...], label: str) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path), "--rules", str(procedure_path),
        "--index", str(source_path),
        "--dialogue-state", str(root / f"{label}-dialogue.json"),
        "--feedback-db", str(root / f"{label}-feedback.sqlite3"),
        "--rule-session", str(root / f"{label}-rule-session.json"),
        "--math", str(root / f"{label}-math.json"),
        "--translations", str(root / f"{label}-translations.json"),
    ]
    result = subprocess.run(
        command, input="\n".join((*lines, "/quit", "")), text=True,
        capture_output=True, cwd=root, timeout=90, check=False)
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"{label}: clean CLI failed:\n{output[-3000:]}")
    return output


def main() -> None:
    require(SOURCE_DB.is_file(), f"missing arXiv metadata index: {SOURCE_DB}")
    source = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)
    knowledge = CRMSKnowledgeBase()
    with tempfile.TemporaryDirectory(prefix="crms-v1-530-") as temp:
        root = Path(temp)
        source_path = root / "arxiv-metadata.sqlite"
        copied_source = CRMSSQLiteResearchIndex(source_path)
        copied_documents: set[str] = set()
        source_citations: list[str] = []
        validation_conclusions: list[tuple[str, str, str, str]] = []
        evaluation_rows: list[tuple[str, str, str]] = []

        for split, paper_id, category, year in RECORDS:
            category_span = f"Primary category: {category}"
            published_span = f"Published: {year}-"
            source_citations.extend(add_claim(
                source, copied_source, knowledge, copied_documents,
                split=split, document_id=paper_id, text_span=category_span,
                triples=((category, "has primary category paper", paper_id),)))
            source_citations.extend(add_claim(
                source, copied_source, knowledge, copied_documents,
                split=split, document_id=paper_id, text_span=published_span,
                triples=((paper_id, "published in", year),)))
            if split in {"train", "holdout"}:
                citation = add_claim(
                    source, copied_source, knowledge, copied_documents,
                    split=split, document_id=paper_id,
                    text_span=f"Primary category: {category}\n",
                    triples=((category, RELATION, year),))
                source_citations.extend(citation)
                if split == "holdout":
                    fact = next(
                        fact for fact in knowledge.facts()
                        if fact.subject == category and fact.relation == RELATION
                        and fact.object == year)
                    validation_conclusions.append(
                        (category, RELATION, year, fact.sources[0]))
            else:
                evaluation_rows.append((paper_id, category, year))

        train_ids = {paper_id for split, paper_id, *_ in RECORDS
                     if split == "train"}
        holdout_ids = {paper_id for split, paper_id, *_ in RECORDS
                       if split == "holdout"}
        evaluation_ids = {paper_id for split, paper_id, *_ in RECORDS
                          if split == "evaluation"}
        require(not (train_ids & holdout_ids or train_ids & evaluation_ids
                     or holdout_ids & evaluation_ids),
                "training, validation, and evaluation documents overlap")

        review = knowledge.review_inference_rules("holdout:", max_arity=2)
        require(review.complete and len(review.reviews) == 1,
                f"arXiv rule search was not complete and unique: {review}")
        candidate_review = review.reviews[0]
        validation = candidate_review.validation
        require((candidate_review.candidate.first_relation,
                 candidate_review.candidate.second_relation,
                 candidate_review.candidate.conclusion_relation)
                == ("has primary category paper", "published in", RELATION)
                and validation is not None
                and validation.status == "validated"
                and len(validation.positive_examples) == 2
                and validation.label_coverage == 1.0,
                f"primary-category/year rule did not pass document holdout: {review}")
        accepted = knowledge.accept_inference_rule_candidate(
            1, RULE_ID, "holdout:", max_arity=2)
        require(accepted.accepted and accepted.rule is not None,
                f"validated arXiv rule was not accepted: {accepted}")

        # Remove held-out conclusions, leaving only cited source premises and
        # the rule-validation ledger. Future evaluation cannot use these rows.
        for subject, relation, obj, citation in validation_conclusions:
            require(knowledge.remove_fact(subject, relation, obj, citation),
                    f"could not remove holdout label: {subject} {obj}")
        evaluation_years = sorted({year for _paper, _category, year
                                   in evaluation_rows})
        for paper_id, category, year in evaluation_rows:
            # Category and publication date are the only evaluation premises.
            category_citation = next(
                citation for citation in source_citations
                if f"evaluation:{paper_id}" in citation
                and "Primary category" in copied_source.resolve_citation(citation))
            date_citation = next(
                citation for citation in source_citations
                if f"evaluation:{paper_id}" in citation
                and f"Published: {year}-" in copied_source.resolve_citation(citation))
            knowledge.add_fact(category, "has primary category paper", paper_id,
                               category_citation)
            knowledge.add_fact(paper_id, "published in", year, date_citation)

        procedures = learn_components()
        result = compose_verified_filter(REQUESTS[0], knowledge, procedures)
        require(result is not None and result.status == "answered"
                and result.included_values == (2020, 2019)
                and result.output_values == (2019, 2020)
                and len(result.inference_proofs) == 2,
                f"arXiv reasoning-to-sort composition failed: {result}")
        facts = [asdict(fact) for fact in
                 (*knowledge.facts(), *knowledge.negative_facts())]
        rules = [asdict(rule) for rule in knowledge._inference_rules.values()]
        for proof, year in zip(result.inference_proofs, ("2020", "2019")):
            checked = verify_inference_proof(
                proof, facts, rules,
                expected_conclusion={"subject": "cs.CL", "relation": RELATION,
                                     "object": year})
            require(checked.valid,
                    f"independent proof verifier rejected cs.CL in {year}: {checked}")

        # Independently reconstruct the task oracle from the frozen raw
        # metadata fields and a standard list-sorting implementation.
        oracle = sorted({int(year) for _paper, category, year in evaluation_rows
                         if category == "cs.CL"})
        require(oracle == [2019, 2020]
                and tuple(oracle) == result.output_values,
                f"raw metadata oracle disagrees with composition: {oracle} / {result}")

        unknown = compose_verified_filter(UNKNOWN_REQUEST, knowledge, procedures)
        require(unknown is not None and unknown.status == "unknown"
                and unknown.unresolved_values == (2018,)
                and not unknown.output_values,
                f"unknown year entered the sort operation: {unknown}")
        conflict_kb = copy.deepcopy(knowledge)
        conflict_kb.add_negative_fact(
            "cs.CL", RELATION, "2019", "audit:injected-negative-control")
        conflict = compose_verified_filter(REQUESTS[0], conflict_kb, procedures)
        require(conflict is not None and conflict.status == "conflict"
                and not conflict.output_values,
                f"conflicting membership ran the operation: {conflict}")

        knowledge_path = root / "knowledge.sqlite3"
        procedure_path = root / "procedures.json"
        knowledge.save(knowledge_path)
        procedures.save(procedure_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        copied_source.close()
        source.close()

        session = root / "clean-copy"
        session.mkdir()
        for path in (knowledge_path, procedure_path, source_path,
                     root / "math.json", root / "translations.json"):
            shutil.copy2(path, session / path.name)
        copied_index = CRMSSQLiteResearchIndex(
            session / source_path.name, read_only=True)
        citations_resolve = bool(source_citations) and all(
            copied_index.resolve_citation(citation) is not None
            for citation in source_citations)
        copied_index.close()
        require(citations_resolve,
                "clean copied source database lost a training/validation citation")

        positive_chat = run_chat(
            session, session / knowledge_path.name,
            session / procedure_path.name, session / source_path.name,
            (REQUESTS[0], "why?"), "positive")
        require("[2019, 2020]" in positive_chat
                and RULE_ID in positive_chat
                and "has primary category paper →" in positive_chat
                and "published in → 2020" in positive_chat,
                f"clean copied model failed to answer/explain with provenance:\n{positive_chat}")
        alternate_chat = run_chat(
            session, session / knowledge_path.name,
            session / procedure_path.name, session / source_path.name,
            (REQUESTS[1],), "alternate")
        require("[2019, 2020]" in alternate_chat,
                f"alternate request form did not transfer: {alternate_chat}")
        unknown_chat = run_chat(
            session, session / knowledge_path.name,
            session / procedure_path.name, session / source_path.name,
            (UNKNOWN_REQUEST,), "unknown")
        require("2018" in unknown_chat
                and "did not run the procedure" in unknown_chat
                and "[2019, 2018, 2020]" not in unknown_chat,
                f"clean copied model presented a partial result: {unknown_chat}")

        report = {
            "experiment": "v1_530_arxiv_reasoned_sort_transfer",
            "source_index": "data/crms_arxiv_cc0_ccby.sqlite (read-only input)",
            "source_license_scope": "CC0 bibliographic metadata; article text/license not included",
            "training_documents": sorted(train_ids),
            "validation_documents": sorted(holdout_ids),
            "evaluation_documents": sorted(evaluation_ids),
            "source_disjoint": True,
            "rule": {"premises": ["has primary category paper", "published in"],
                     "conclusion": RELATION, "validation": "passed",
                     "validation_examples": len(validation.positive_examples),
                     "validation_label_coverage": validation.label_coverage},
            "procedure": "sort the list (separately learned with Codex-labeled examples)",
            "evaluation": {"category": "cs.CL",
                           "verified_years_before_sort": [2020, 2019],
                           "sorted_years": list(result.output_values),
                           "raw_metadata_oracle": oracle,
                           "proofs_independently_verified": len(result.inference_proofs)},
            "unknown_control": {"year": 2018, "status": unknown.status,
                                "partial_output_blocked": not unknown.output_values},
            "conflict_control": {"status": conflict.status,
                                 "operation_blocked": not conflict.output_values,
                                 "negative_was_injected": True},
            "citations_resolve_from_clean_copy": citations_resolve,
            "fresh_chat_answer_explain_and_alternate_form": True,
            "limitations": [
                "Source records are arXiv metadata, not full papers; article licenses were not checked.",
                "The task's relation facts were manually mapped from metadata fields by Codex.",
                "Rule validation uses only two held-out documents from the same platform.",
                "Sort is separately taught with Codex-labeled examples; no automatic procedure induction from papers is claimed.",
                "This is one category/year task and not an estimate of broad reasoning, dialogue, or 70B-class performance.",
            ],
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")

    print("arXiv metadata rule discovery and two-document holdout: PASS")
    print("held-out cs.CL year membership independently proof-checked: PASS")
    print("learned sort returns [2019, 2020], matching raw metadata oracle: PASS")
    print("unknown year and injected conflict both block output: PASS")
    print("clean copied-model chat answers, explains, and resolves citations: PASS")
    print("scope: CC0 metadata only; manually mapped facts; one task slice")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
