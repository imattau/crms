"""Review symmetric-schema candidates on source-separated evidence."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def indexed_source(index: CRMSResearchIndex, document_id: str,
                   text: str, domain: str) -> str:
    index.add_document(document_id, document_id, text,
                       f"https://{domain}.example/relations")
    hit = next(hit for hit in index.search(text, limit=5)
               if hit.document_id == document_id)
    return index.citation(hit)


def add_reciprocal(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                   left: str, right: str, doc_id: str, domain: str) -> None:
    source = indexed_source(
        index, doc_id,
        f"{left} is connected to {right}. {right} is connected to {left}.",
        domain)
    kb.add_fact(left, "connected to", right, source)
    kb.add_fact(right, "connected to", left, source)


def add_one_way(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                left: str, right: str, doc_id: str, domain: str) -> None:
    source = indexed_source(index, doc_id, f"{left} is connected to {right}.",
                            domain)
    kb.add_fact(left, "connected to", right, source)


def main() -> None:
    kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    add_reciprocal(kb, index, "Ada", "Bea", "train:one", "train-one")
    add_reciprocal(kb, index, "Cy", "Dee", "train:two", "train-two")
    add_reciprocal(kb, index, "Eli", "Fay", "holdout:one", "holdout-one")
    add_reciprocal(kb, index, "Gus", "Hal", "holdout:two", "holdout-two")

    reviewed = kb.review_relation_schemas(
        "holdout:", research_index=index)
    require(reviewed.complete and len(reviewed.reviews) == 1,
            f"source-separated review failed to discover the candidate: {reviewed}")
    review = reviewed.reviews[0]
    require(review.candidate.status == "uncontradicted"
            and review.validation.status == "validated"
            and len(review.validation.positive_examples) == 2
            and not review.validation.negative_examples
            and review.validation.label_coverage == 1.0
            and len(review.validation.independent_sources) == 2,
            f"clean held-out reciprocal examples did not validate: {review}")
    require(not any(fact.relation == "has relation type"
                    for fact in kb.facts()),
            "held-out validation installed a relation schema")

    contradicted_kb = CRMSKnowledgeBase()
    contradicted_index = CRMSResearchIndex()
    add_reciprocal(contradicted_kb, contradicted_index,
                   "Ada", "Bea", "train:one", "train-one")
    add_reciprocal(contradicted_kb, contradicted_index,
                   "Cy", "Dee", "train:two", "train-two")
    add_reciprocal(contradicted_kb, contradicted_index,
                   "Eli", "Fay", "holdout:one", "holdout-one")
    negative = indexed_source(
        contradicted_index, "holdout:negative",
        "Gus is connected to Hal. Hal is not connected to Gus.",
        "holdout-negative")
    contradicted_kb.add_fact("Gus", "connected to", "Hal", negative)
    contradicted_kb.add_negative_fact("Hal", "connected to", "Gus", negative)
    contradicted = contradicted_kb.review_relation_schemas(
        "holdout:", research_index=contradicted_index)
    require(len(contradicted.reviews) == 1
            and contradicted.reviews[0].validation.status == "contradicted"
            and len(contradicted.reviews[0].validation.negative_examples) == 1,
            f"held-out counterexample did not reject the candidate: {contradicted}")

    unknown_kb = CRMSKnowledgeBase()
    unknown_index = CRMSResearchIndex()
    add_reciprocal(unknown_kb, unknown_index,
                   "Ada", "Bea", "train:one", "train-one")
    add_reciprocal(unknown_kb, unknown_index,
                   "Cy", "Dee", "train:two", "train-two")
    add_one_way(unknown_kb, unknown_index,
                "Eli", "Fay", "holdout:one", "holdout-one")
    add_one_way(unknown_kb, unknown_index,
                "Gus", "Hal", "holdout:two", "holdout-two")
    unknown = unknown_kb.review_relation_schemas(
        "holdout:", research_index=unknown_index)
    require(len(unknown.reviews) == 1
            and unknown.reviews[0].validation.status == "insufficient"
            and unknown.reviews[0].validation.unknown_reverse_pairs == 2
            and unknown.reviews[0].validation.label_coverage == 0.0,
            f"unlabeled reverse absences were treated as validation: {unknown}")

    with tempfile.TemporaryDirectory(prefix="crms-heldout-schema-") as folder:
        root = Path(folder)
        kb.save(root / "knowledge.json")
        index.save(root / "index.json")
        chat = subprocess.run(
            [sys.executable,
             str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "index.json"),
             "--rules", str(root / "rules.json"),
             "--dialogue-state", str(root / "dialogue.json")],
            input=("/review-relation-schemas holdout:\n"
                   "/inference-rules\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        require("Candidate 1 [validated; training=uncontradicted]"
                in chat.stdout
                and "holdout-positive=2" in chat.stdout
                and "no schema was stored" in chat.stdout
                and "connected to — has relation type → symmetric"
                not in chat.stdout,
                f"interactive review failed or installed its candidate: {chat.stdout}")

    print("source-held-out reciprocal evidence validates a symmetry candidate: PASS")
    print("an explicit held-out negative rejects the candidate: PASS")
    print("unlabeled reverse absences remain unknown and lower coverage: PASS")
    print("interactive review reports evidence without installing a schema: PASS")


if __name__ == "__main__":
    main()
