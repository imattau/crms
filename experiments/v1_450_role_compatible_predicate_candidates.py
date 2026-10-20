"""Propose, but never accept, predicate candidates from cited role types.

This addresses the low yield of exact shared-entity-pair alignment. It only
uses accepted, cited entity types to find source frames with compatible
subject/object roles. The fixture intentionally includes a false semantic
match (praised); it must remain an explicit review-only candidate.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_cited(index: CRMSResearchIndex, document_id: str,
              sentence: str) -> str:
    index.add_document(document_id, document_id, sentence,
                       f"https://source-{document_id}.example/{document_id}")
    hit = next((row for row in index.search(sentence, limit=20, context_chars=0)
                if row.document_id == document_id), None)
    require(hit is not None, f"source sentence was not indexed: {sentence}")
    citation = index.citation(hit)
    require(index.resolve_citation(citation) == sentence,
            f"citation did not resolve exactly: {citation}")
    return citation


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    relation_rows = (
        ("created-a", "Ada created Alpha."),
        ("created-b", "Bea created Beta."),
        ("made-a", "Cara made Gamma."),
        ("made-b", "Dan made Delta."),
        ("praised-a", "Eve praised Epsilon."),
        ("praised-b", "Finn praised Zeta."),
        ("visited-a", "Gus visited Rome."),
        ("visited-b", "Hana visited Paris."),
    )
    for document_id, sentence in relation_rows:
        add_cited(index, document_id, sentence)

    typed_entities = (
        ("Ada", "person"), ("Bea", "person"),
        ("Cara", "person"), ("Dan", "person"),
        ("Eve", "person"), ("Finn", "person"),
        ("Gus", "person"), ("Hana", "person"),
        ("Alpha", "language"), ("Beta", "language"),
        ("Gamma", "language"), ("Delta", "language"),
        ("Epsilon", "language"), ("Zeta", "language"),
        ("Rome", "city"), ("Paris", "city"),
    )
    for number, (entity, entity_type) in enumerate(typed_entities):
        citation = add_cited(
            index, f"type-{number}", f"{entity} is a {entity_type}.")
        kb.add_fact(entity, "is-a", entity_type, citation)

    negative_type = add_cited(
        index, "type-negative-ada", "Ada is not a person.")
    conflicted_types = CRMSKnowledgeBase()
    for fact in kb.facts():
        for source in fact.sources:
            conflicted_types.add_fact(
                fact.subject, fact.relation, fact.object, source,
                qualifiers=dict(fact.qualifiers))
    conflicted_types.add_negative_fact(
        "Ada", "is-a", "person", negative_type)

    qualified_types = CRMSKnowledgeBase()
    for number, (entity, entity_type) in enumerate(typed_entities):
        citation = add_cited(
            index, f"qualified-type-{number}",
            f"{entity} is a {entity_type}.")
        qualified_types.add_fact(
            entity, "is-a", entity_type, citation,
            qualifiers={"scope": "during the experiment"})
    require(not qualified_types.propose_role_compatible_predicate_candidates(
        index, maximum_documents=100),
        "qualified type facts unexpectedly supplied general role compatibility")
    conflicted_proposals = (
        conflicted_types.propose_role_compatible_predicate_candidates(
            index, maximum_documents=100))
    require(all("Ada created Alpha" not in row["canonical_sentence"]
                and "Ada created Alpha" not in row["candidate_sentence"]
                for item in conflicted_proposals for row in item["support"]),
            "a type contradicted by explicit negative evidence guided a candidate")

    before = kb.facts()
    # Without source-resolved, accepted type records, role matching is disabled.
    no_types = CRMSKnowledgeBase()
    require(not no_types.propose_role_compatible_predicate_candidates(index),
            "type-free corpus unexpectedly produced role candidates")

    proposals = kb.propose_role_compatible_predicate_candidates(
        index, maximum_documents=100)
    relation_pairs = {
        (item["relation"], item["candidate_predicate"])
        for item in proposals
    }
    require(any(set(pair) == {"created", "made"}
                for pair in relation_pairs),
            f"role-compatible made wording was not surfaced: {relation_pairs}")
    require(any(set(pair) == {"created", "praised"}
                for pair in relation_pairs),
            "fixture did not expose the expected false semantic candidate")
    require(not any("visited" in pair for pair in relation_pairs),
            f"incompatible person-to-city role was proposed: {relation_pairs}")
    require(all(item["status"] == "investigate_only"
                and item["acceptance_allowed"] is False
                and item["review_required"] is True
                and item["evidence_kind"] == "role_type_compatibility_only"
                for item in proposals),
            "a role-compatible candidate was not clearly review-only")
    require(all(index.resolve_citation(row[key])
                for item in proposals for row in item["support"]
                for key in ("canonical_source", "candidate_source")),
            "candidate support lost a resolvable relation citation")
    require(all(row["canonical_document_id"]
                != row["candidate_document_id"]
                for item in proposals for row in item["support"]),
            "one document supplied both sides of a candidate pair")
    require(kb.facts() == before,
            "report-only type matching changed accepted knowledge")

    with tempfile.TemporaryDirectory(prefix="crms-role-alignment-") as folder:
        root = Path(folder)
        kb.save(root / "knowledge.json")
        index.save(root / "index.json")
        command = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "index.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--dialogue-model", str(root / "intent.json"),
             "--rules", str(root / "rules.json"),
             "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--feedback-db", str(root / "feedback.sqlite")],
            input="/suggest-role-compatible-alignments\n/quit\n",
            text=True, capture_output=True, cwd=root, check=False, timeout=30)
        require(command.returncode == 0,
                f"chat failed to start: {command.stderr}")
        require("shared argument types do not show that the predicates mean the same thing"
                in command.stdout
                and "No facts or language frames changed" in command.stdout
                and "praised" in command.stdout,
                f"chat did not communicate the candidate limits: {command.stdout}")

    print("cited type compatibility surfaced made and false-match praised: PASS")
    print("incompatible person-to-city relation was filtered: PASS")
    print("qualified and explicitly contradicted type evidence was excluded: PASS")
    print("support citations resolve; proposal stays report-only and non-acceptable: PASS")
    print("chat exposes the review-only candidates and semantic limitation: PASS")
    print("scope: candidate retrieval signal, not synonym learning or acceptance")


if __name__ == "__main__":
    main()
