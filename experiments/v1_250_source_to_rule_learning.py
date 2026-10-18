"""Exercise the reviewed source-to-fact-to-rule learning route end to end."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()

    # Two labeled examples per relation teach only the surface frames. Each
    # accepted fact retains a citation to the indexed source document.
    seeds = [
        ("train:1:a", "Ada mentored Bea.", "Ada", "parent", "Bea"),
        ("train:1:b", "Bea mentored Cal.", "Bea", "parent", "Cal"),
        ("train:1:c", "Ada guided Cal.", "Ada", "ancestor", "Cal"),
        ("train:2:a", "Dee mentored Eli.", "Dee", "parent", "Eli"),
        ("train:2:b", "Eli mentored Fay.", "Eli", "parent", "Fay"),
        ("train:2:c", "Dee guided Fay.", "Dee", "ancestor", "Fay"),
    ]
    indexed = {}
    for document_id, sentence, subject, relation, obj in seeds:
        index.add_document(document_id, "Seed examples", sentence,
                           f"{document_id}.txt")
        hit = next(hit for hit in index.search(sentence, limit=10)
                   if hit.document_id == document_id)
        indexed[document_id] = (sentence, hit)
        kb.add_fact_from_hit(subject, relation, obj, index, hit)

    for relation, rows in (
            ("parent", seeds[:2]),
            ("ancestor", [seeds[2], seeds[5]])):
        licensed = False
        for document_id, sentence, subject, _label, obj in rows:
            source_sentence, hit = indexed[document_id]
            licensed = kb.teach_fact_pattern_from_hit(
                source_sentence, subject=subject, relation=relation, obj=obj,
                predicate_phrase=("mentored" if relation == "parent" else "guided"),
                research_index=index, hit=hit) or licensed
        require(licensed,
                f"two sourced examples did not license {relation} wording")

    # A third training chain and two held-out chains enter only through
    # reviewable extraction candidates; none is committed by proposing it.
    chains = [
        ("holdout:1", "Mia", "Ned", "Ola"),
        ("holdout:2", "Pia", "Quin", "Raj"),
    ]
    for prefix, start, middle, end in chains:
        for suffix, sentence, subject, relation, obj in (
                ("a", f"{start} mentored {middle}.", start, "parent", middle),
                ("b", f"{middle} mentored {end}.", middle, "parent", end),
                ("c", f"{start} guided {end}.", start, "ancestor", end)):
            document_id = f"{prefix}:{suffix}"
            index.add_document(document_id, "Reviewed source", sentence,
                               f"{document_id}.txt")
            hit = next(hit for hit in index.search(sentence, limit=10)
                       if hit.document_id == document_id)
            candidates = kb.propose_facts_from_hit(
                sentence, research_index=index, hit=hit)
            require(len(candidates) == 1,
                    f"expected one reviewed extraction for {sentence!r}: {candidates}")
            candidate = candidates[0]
            require((candidate.subject, candidate.relation, candidate.object)
                    == (subject, relation, obj),
                    f"source frame extracted the wrong relation: {candidate}")
            before = len(kb.facts())
            kb.accept_fact_candidate(candidate, index)
            require(len(kb.facts()) == before + 1,
                    "accepted source candidate did not add exactly one fact")

    # Add a fresh two-edge chain without storing its ancestor conclusion. This
    # makes the later chat query require the learned rule rather than direct
    # retrieval of a labeled answer.
    for document_id, sentence, subject, obj in (
            ("train:3:a", "Gus mentored Hal.", "Gus", "Hal"),
            ("train:3:b", "Hal mentored Ivy.", "Hal", "Ivy")):
        index.add_document(document_id, "Unlabeled chain premises", sentence,
                           f"{document_id}.txt")
        hit = next(hit for hit in index.search(sentence, limit=10)
                   if hit.document_id == document_id)
        candidates = kb.propose_facts_from_hit(
            sentence, research_index=index, hit=hit)
        require(len(candidates) == 1
                and (candidates[0].subject, candidates[0].relation,
                     candidates[0].object) == (subject, "parent", obj),
                f"new chain premise was not extracted correctly: {candidates}")
        kb.accept_fact_candidate(candidates[0], index)

    review = kb.review_inference_rules(
        "holdout:", min_support=2, min_validation_support=2)
    candidate_number = next((number for number, item in enumerate(
        review.reviews, start=1)
        if (item.candidate.first_relation, item.candidate.second_relation,
            item.candidate.conclusion_relation) == ("parent", "parent", "ancestor")
        and item.validation is not None
        and item.validation.status == "validated"), None)
    require(review.complete and candidate_number is not None,
            f"sourced examples did not validate the expected rule: {review}")
    require(not kb._inference_rules,
            "rule review silently installed a candidate")

    # Exercise the same source-derived candidate through the user's terminal
    # chat path, including ordinary-language review, explicit acceptance, and
    # a question that can only be answered by applying the accepted rule.
    frame_licensed = False
    for question, subject, obj in (
            ("Is Ada an ancestor of Cal?", "Ada", "Cal"),
            ("Is Dee an ancestor of Fay?", "Dee", "Fay")):
        frame_licensed = kb.teach_polar_question(
            question, subject=subject, relation="ancestor", obj=obj,
            answer=True) or frame_licensed
    require(frame_licensed,
            "two grounded examples did not license the inference question frame")
    with tempfile.TemporaryDirectory(prefix="crms-source-rule-chat-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "research.json"
        kb.save(knowledge_path)
        index.save(index_path)
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        chat = subprocess.run(
            command,
            input=(
                "Review inference rule candidates against held-out sources "
                "with prefix 'holdout:'.\n"
                f"Accept rule candidate {candidate_number} as 'parent-chain' "
                "using held-out source prefix 'holdout:'.\n"
                "Is Gus an ancestor of Ivy?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        require("parent then parent entails ancestor" in chat.stdout,
                f"terminal review did not show source-derived candidate: {chat.stdout}")
        require("Accepted validated rule parent-chain" in chat.stdout,
                f"natural-language acceptance did not activate rule: {chat.stdout}")
        require("CRMS> Yes." in chat.stdout,
                f"chat question did not use the accepted proof: {chat.stdout}")

    accepted = kb.accept_inference_rule_candidate(
        candidate_number, "parent-chain", "holdout:", min_support=2,
        min_validation_support=2)
    require(accepted.accepted and accepted.rule is not None,
            f"explicitly accepted rule was not installed: {accepted}")
    answer = kb.infer_relation("Gus", "ancestor", "Ivy")
    require(answer.status == "answered" and answer.proofs,
            f"accepted source-validated rule did not prove a new query: {answer}")
    source_ids = {source for fact in kb.facts() for source in fact.sources}
    fact_rows = [asdict(fact) for fact in kb.facts()]
    rule_rows = [asdict(rule) for rule in kb._inference_rules.values()]
    cited = set()
    for proof in answer.proofs:
        checked = verify_inference_proof(
            proof, fact_rows, rule_rows, expected_conclusion=answer.conclusion)
        require(checked.valid,
                f"independent checker rejected the source-derived proof: {checked}")
        cited.update(source for leaf in kb._inference_fact_leaves(proof)
                     for source in leaf.get("sources", []))
    require(cited and cited <= source_ids,
            "rule proof omitted or invented reviewed source citations")

    print("source-to-rule learning diagnostic: PASS")
    print("reviewed sentence frames -> cited facts -> source-heldout rule "
          "validation -> explicit activation -> proof-backed inference: PASS")


if __name__ == "__main__":
    main()
