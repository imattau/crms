"""Propose explicit relation schemas from cited sentences for human review."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def proposal_for(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                 document_id: str, sentence: str):
    index.add_document(document_id, document_id, sentence,
                       f"{document_id}.txt")
    hit = index.search(sentence, limit=1)[0]
    return kb.propose_facts_from_hit(
        sentence, research_index=index, hit=hit)


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()

    # The relation name is explicit and quoted; a multiword schema assertion
    # becomes one ordinary, cited fact candidate and is not stored yet.
    sentence = 'The relation "parent of" is irreflexive.'
    candidates = proposal_for(kb, index, "schema-positive", sentence)
    require(len(candidates) == 1,
            f"expected one schema proposal, got: {candidates}")
    candidate = candidates[0]
    require((candidate.subject, candidate.relation, candidate.object,
             candidate.polarity)
            == ("parent of", "has relation type", "irreflexive", True),
            f"schema proposal has wrong content: {candidate}")
    require(candidate.source and candidate.source.startswith("schema-positive#")
            and candidate.sentence == sentence
            and any(item.get("kind") == "relation_type_schema_discovery"
                    and item.get("review_required") is True
                    for item in candidate.language_evidence),
            f"schema proposal lost its citation or review marker: {candidate}")
    require(not kb.facts(),
            "schema proposal changed the knowledge store before review")
    research_result = kb.research("parent relation irreflexive", index)
    require(any((item.subject, item.relation, item.object)
                == ("parent of", "has relation type", "irreflexive")
                and item.source == candidate.source
                for item in research_result.candidates or []),
            f"normal source research did not surface the review candidate: "
            f"{research_result}")

    # Only an exact affirmative declaration is recognized. The source parser
    # must not convert negation, conditionals, or an ambiguous bare multiword
    # span into a schema.
    rejected_sentences = (
        "The relation parent is not symmetric.",
        "If the relation parent is asymmetric, check for cycles.",
        "The relation parent of Ann is asymmetric.",
        "The relation works for is functional.",
    )
    for index_number, rejected in enumerate(rejected_sentences):
        proposals = proposal_for(kb, index, f"schema-rejected-{index_number}",
                                 rejected)
        require(not any(item.relation == "has relation type"
                        for item in proposals),
                f"ambiguous or non-affirmative schema was proposed: {rejected!r} "
                f"-> {proposals}")

    # The usual cited-candidate acceptance path installs the declaration;
    # the reasoning engine then uses it to flag a violating fact.
    schema_fact = kb.accept_fact_candidate(candidate, index)
    require((schema_fact.subject, schema_fact.relation, schema_fact.object)
            == ("parent of", "has relation type", "irreflexive")
            and candidate.source in schema_fact.sources,
            f"review acceptance lost schema content or provenance: {schema_fact}")
    kb.add_fact("Ann", "parent of", "Ann", "fact:self-parent")
    checked = kb.infer_relation("Ann", "parent of", "Ann")
    require(checked.status == "ambiguous"
            and checked.reason_code == "integrity_conflict"
            and candidate.source in (checked.request or ""),
            f"accepted source schema did not affect reasoning with provenance: "
            f"{checked}")

    # An unquoted single-token relation remains usable for an explicit source
    # statement, while schema-like labels alone do not become declarations.
    one_word = proposal_for(
        kb, index, "schema-bare", "The relation parent is asymmetric.")
    require(len(one_word) == 1
            and one_word[0].object == "asymmetric",
            f"explicit bare relation declaration was missed: {one_word}")
    label_only = proposal_for(
        kb, index, "schema-label-only", "Parent relations are usually asymmetric.")
    require(not any(item.relation == "has relation type" for item in label_only),
            f"relation label/type association was inferred without declaration: "
            f"{label_only}")

    for index_number, relation_type in enumerate((
            "transitive", "symmetric", "irreflexive", "asymmetric",
            "functional", "closed-world")):
        schema_sentence = (
            f'The relation "review relation {index_number}" is '
            f'{relation_type.replace("-", " ")}.')
        type_candidates = proposal_for(
            kb, index, f"schema-type-{index_number}", schema_sentence)
        require(len(type_candidates) == 1
                and type_candidates[0].object == relation_type,
                f"supported schema type was not extracted: {schema_sentence!r} "
                f"-> {type_candidates}")

    print("reviewed relation-schema proposal diagnostic: PASS")
    print("explicit cited assertion, review-only storage, rejection of negated/conditional/"
          "ambiguous phrasing, provenance-preserving acceptance and integrity use: PASS")


if __name__ == "__main__":
    main()
