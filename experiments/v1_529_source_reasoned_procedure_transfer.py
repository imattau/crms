"""Transfer source-backed reasoning into a separately learned procedure.

The rule is discovered from two SimpleWiki training articles, reviewed against
two document-disjoint articles, then evaluated on Marie Curie's article after
the validation conclusions are removed. Only proof-verified years reach the
learned count procedure. This is one audited task slice, not a broad reasoning
or learning benchmark.
"""

from __future__ import annotations

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
from v1_507_reasoned_count_aggregation import teach_count
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSSQLiteResearchIndex, SearchHit
from crms_rule_proof import verify_inference_proof
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = PROJECT / "data" / "crms_simplewiki_research.sqlite"
REPORT = PROJECT / "experiments" / "reports" / "v1_529_source_reasoned_procedure_transfer.json"
REQUEST = (
    "Count the matching entries among 1903 and 1911 that Marie Curie won in."
)
UNKNOWN_REQUEST = (
    "Count the matching entries among 1903, 1911, and 1912 "
    "that Marie Curie won in."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_span_facts(source: CRMSSQLiteResearchIndex,
                   model_sources: CRMSSQLiteResearchIndex,
                   knowledge: CRMSKnowledgeBase,
                   copied: set[str], *, split: str, document_id: str,
                   span: str,
                   triples: tuple[tuple[str, str, str], ...]) -> list[str]:
    document = source.document(document_id)
    require(span in document.text,
            f"frozen SimpleWiki source span changed: {document.title}: {span!r}")
    local_id = f"{split}:{document_id}"
    if local_id not in copied:
        model_sources.add_document(local_id, document.title, document.text,
                                   document.location)
        copied.add(local_id)
    start = document.text.index(span)
    hit = SearchHit(local_id, document.title, document.location, 1.0,
                    span, start, start + len(span), ())
    citations = []
    for subject, relation, obj in triples:
        fact = knowledge.add_fact_from_hit(
            subject, relation, obj, model_sources, hit)
        citations.extend(fact.sources)
    if not triples:
        citations.append(model_sources.citation(hit))
    return sorted(set(citations))


def run_chat(root: Path, knowledge_path: Path, procedures_path: Path,
             source_path: Path, turns: tuple[str, ...], name: str) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path), "--rules", str(procedures_path),
        "--index", str(source_path),
        "--feedback-db", str(root / f"{name}-feedback.sqlite3"),
        "--dialogue-state", str(root / f"{name}-dialogue.json"),
        "--rule-session", str(root / f"{name}-rule-session.json"),
        "--math", str(root / f"{name}-math.json"),
        "--translations", str(root / f"{name}-translations.json"),
    ]
    result = subprocess.run(
        command, input="\n".join((*turns, "/quit", "")), text=True,
        capture_output=True, cwd=root, timeout=90, check=False)
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"{name}: fresh chat failed:\n{output[-3000:]}")
    return output


def main() -> None:
    require(SOURCE_DB.is_file(), f"missing SimpleWiki source index: {SOURCE_DB}")
    source = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)
    knowledge = CRMSKnowledgeBase()
    with tempfile.TemporaryDirectory(prefix="crms-v1-529-") as temp:
        root = Path(temp)
        source_path = root / "source.sqlite"
        model_sources = CRMSSQLiteResearchIndex(source_path)
        copied: set[str] = set()
        evidence: dict[str, list[str]] = {}

        # Training examples: two people, each with a cited prize and award
        # year, plus a directly labeled conclusion for rule discovery.
        training = (
            ("wiki:simplewiki:8106", "Max Planck", "1918",
             "He won the Nobel Prize in physics.",
             "Nobel Prize in Physics (1918)"),
            ("wiki:simplewiki:2138", "Albert Einstein", "1921",
             "He won the Nobel Prize in Physics in 1921 for theoretical physics.",
             "Nobel Prize in Physics (1921)"),
        )
        for document_id, person, year, person_span, year_span in training:
            evidence[f"training:{person}"] = add_span_facts(
                source, model_sources, knowledge, copied, split="train",
                document_id=document_id, span=person_span,
                triples=((person, "received", "Nobel Prize in Physics"),))
            year_citations = add_span_facts(
                source, model_sources, knowledge, copied, split="train",
                document_id=document_id, span=year_span,
                triples=(("Nobel Prize in Physics", "awarded in", year),
                         (person, "won in", year)))
            evidence[f"training:{person}"].extend(year_citations)

        # Independent source documents are held out for candidate validation.
        validation = (
            ("wiki:simplewiki:70876", "Pierre Curie",
             "He shared the 1903 Nobel Prize in Physics with his wife, Marie Curie and Henri Becquerel"),
            ("wiki:simplewiki:230071", "Henri Becquerel",
             "won part of the Nobel Prize in Physics in 1903"),
        )
        validation_conclusions: list[tuple[str, str, str, str]] = []
        for document_id, person, span in validation:
            citations = add_span_facts(
                source, model_sources, knowledge, copied, split="holdout",
                document_id=document_id, span=span,
                triples=((person, "received", "Nobel Prize in Physics"),
                         ("Nobel Prize in Physics", "awarded in", "1903"),
                         (person, "won in", "1903")))
            evidence[f"holdout:{person}"] = citations
            conclusion = next(
                fact for fact in knowledge.facts()
                if fact.subject == person and fact.relation == "won in"
                and fact.object == "1903")
            validation_conclusions.append(
                (person, "won in", "1903", conclusion.sources[0]))

        review = knowledge.review_inference_rules("holdout:", max_arity=2)
        require(review.complete and len(review.reviews) == 1,
                f"source-disjoint rule candidate set was not unique/complete: {review}")
        candidate = review.reviews[0].candidate
        validation_result = review.reviews[0].validation
        require((candidate.first_relation, candidate.second_relation,
                 candidate.conclusion_relation)
                == ("received", "awarded in", "won in")
                and validation_result is not None
                and validation_result.status == "validated"
                and len(validation_result.positive_examples) == 2
                and validation_result.label_coverage == 1.0,
                f"cited source rule did not pass holdout validation: {review}")
        accepted = knowledge.accept_inference_rule_candidate(
            1, "nobel-prize-award-year", "holdout:", max_arity=2)
        require(accepted.accepted and accepted.rule is not None,
                f"reviewed rule was not accepted: {accepted}")

        # Validation conclusions license the rule but must not serve as future
        # premises. Retain only their cited first/second premises and the
        # audit record attached to the accepted rule.
        for subject, relation, obj, citation in validation_conclusions:
            require(knowledge.remove_fact(subject, relation, obj, citation),
                    f"could not remove validation conclusion {subject} {obj}")
        require(all(knowledge.infer_relation(subject, relation, obj).status
                    == "answered"
                    for subject, relation, obj, _citation
                    in validation_conclusions),
                "accepted rule did not rederive held-out conclusions after removal")

        # Marie Curie's records were not available during rule discovery or
        # validation. Their two award/year pairs are the evaluation premises.
        for span, award, year in (
                ("Nobel Prize in Physics (1903)",
                 "Nobel Prize in Physics", "1903"),
                ("Nobel Prize in Chemistry (1911)",
                 "Nobel Prize in Chemistry", "1911")):
            evidence.setdefault("evaluation:Marie Curie", []).extend(
                add_span_facts(
                    source, model_sources, knowledge, copied,
                    split="evaluation", document_id="wiki:simplewiki:47196",
                    span=span,
                    triples=(("Marie Curie", "received", award),
                             (award, "awarded in", year))))

        count_procedure = learn_components()
        teach_count(count_procedure)
        result = compose_verified_filter(REQUEST, knowledge, count_procedure)
        require(result is not None and result.status == "answered"
                and result.included_values == (1903, 1911)
                and result.output_values == (2,)
                and len(result.inference_proofs) == 2
                and result.procedure_records,
                f"source-backed inference/count composition failed: {result}")
        require(all(
            verify_inference_proof(
                proof, [asdict(fact) for fact in
                        (*knowledge.facts(), *knowledge.negative_facts())],
                [asdict(rule) for rule in knowledge._inference_rules.values()],
                expected_conclusion={"subject": "Marie Curie",
                                     "relation": "won in", "object": year}).valid
            for proof, year in zip(result.inference_proofs, ("1903", "1911"))),
            "independent verifier rejected one of the two inference proofs")

        # Every evidence citation must resolve from the small copied source
        # database; the original 1.3 GB source index is not needed at runtime.
        fact_citations = sorted({citation for rows in evidence.values()
                                 for citation in rows})
        require(fact_citations and all(
            model_sources.resolve_citation(citation) is not None
            for citation in fact_citations),
            "copied source database failed to resolve an accepted fact citation")

        # A second SimpleWiki page supplies an independent answer check:
        # it explicitly lists Physics 1903 and Chemistry 1911.
        oracle_span = (
            "They are:\nMarie Curie – in Physics 1903, for the discovery of "
            "radioactivity; and in Chemistry 1911, for the isolation of pure radium"
        )
        oracle_citations = add_span_facts(
            source, model_sources, knowledge, copied, split="oracle",
            document_id="wiki:simplewiki:6494", span=oracle_span,
            triples=())
        require(len({"1903", "1911"}) == result.output_values[0]
                and oracle_citations
                and all(model_sources.resolve_citation(citation) is not None
                        for citation in oracle_citations),
                "independent cited award-list check disagreed with the count")

        unknown = compose_verified_filter(UNKNOWN_REQUEST, knowledge,
                                          count_procedure)
        require(unknown is not None and unknown.status == "unknown"
                and unknown.unresolved_values == (1912,)
                and not unknown.output_values,
                f"unsupported year entered the learned procedure: {unknown}")

        knowledge_path = root / "knowledge.sqlite3"
        procedure_path = root / "procedures.json"
        knowledge.save(knowledge_path)
        count_procedure.save(procedure_path)
        model_sources.close()
        source.close()
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        # Copy only the learned knowledge, procedure, and the cited source
        # text needed to verify it. No original source paths are available.
        session = root / "clean-model-copy"
        session.mkdir()
        for path in (knowledge_path, procedure_path, source_path,
                     root / "math.json", root / "translations.json"):
            shutil.copy2(path, session / path.name)
        copied_index = CRMSSQLiteResearchIndex(
            session / source_path.name, read_only=True)
        copy_citations_resolve = bool(fact_citations) and all(
            copied_index.resolve_citation(citation) is not None
            for citation in fact_citations)
        copied_index.close()
        require(copy_citations_resolve,
                "clean copied source database cannot resolve every fact citation")
        positive_chat = run_chat(
            session, session / knowledge_path.name,
            session / procedure_path.name, session / source_path.name,
            (REQUEST, "why?"), "positive")
        require("There are 2 listed entries satisfying" in positive_chat
                and "Marie Curie" in positive_chat
                and "1903" in positive_chat and "1911" in positive_chat
                and "nobel-prize-award-year" in positive_chat
                and "Traceback" not in positive_chat,
                f"clean copied-model chat failed to show checked result/lineage:\n{positive_chat}")
        unknown_chat = run_chat(
            session, session / knowledge_path.name,
            session / procedure_path.name, session / source_path.name,
            (UNKNOWN_REQUEST,), "unknown")
        require("1912" in unknown_chat
                and "did not run the procedure" in unknown_chat
                and "There are 3 listed entries satisfying" not in unknown_chat,
                f"clean copied model applied a procedure to an unknown value:\n{unknown_chat}")

        report = {
            "experiment": "v1_529_source_reasoned_procedure_transfer",
            "source_index": "data/crms_simplewiki_research.sqlite (read-only input)",
            "copied_source_documents": sorted(copied),
            "training_people": ["Max Planck", "Albert Einstein"],
            "validation_people": ["Pierre Curie", "Henri Becquerel"],
            "evaluation_entity": "Marie Curie",
            "rule": {"premises": ["received", "awarded in"],
                     "conclusion": "won in", "holdout": "validated",
                     "validation_examples": 2,
                     "validation_label_coverage": 1.0},
            "learned_procedure": "count the matching entries",
            "result": {"verified_years": [1903, 1911], "count": 2},
            "independent_check": {
                "kind": "separate cited Nobel Prize article listing the two awards",
                "source_citations_resolve": True,
                "count_agrees": True,
            },
            "unknown_control": {"candidate_year": 1912,
                                "status": unknown.status,
                                "procedure_not_run": not unknown.output_values},
            "proofs_independently_verified": len(result.inference_proofs),
            "all_fact_citations_resolve_from_copy": copy_citations_resolve,
            "clean_model_copy_chat": True,
            "limitations": [
                "The fact and relation labels were manually reviewed by Codex; extraction was not autonomous.",
                "All source documents come from SimpleWiki, and the rule holdout has only two examples.",
                "The procedure is separately supervised with Codex-labeled examples.",
                "This proves one source-backed reasoning-to-count composition, not general task-planning or broad corpus learning.",
                "No external 70B-class model was run; the comparator remains a qualitative task rubric.",
            ],
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")

    print("source-disjoint rule discovery and two-document holdout validation: PASS")
    print("Marie Curie years derived with two independently verified proofs: PASS")
    print("separately learned count agrees with a cited second-article check: PASS")
    print("unknown year prevents partial procedure output: PASS")
    print("clean copied model answers, explains, and preserves citations: PASS")
    print("scope: one SimpleWiki task slice; labels and procedure teaching are reviewed")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
