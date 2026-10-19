"""Discover, hold out, accept, and execute explicit typed ternary rules."""

from __future__ import annotations

from dataclasses import asdict
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_chain(kb: CRMSKnowledgeBase, subject: str, first_middle: str,
              second_middle: str, target: str, source: str, *,
              label: str = "positive", with_kinds: bool = True) -> None:
    for first, relation, second in (
            (subject, "employs", first_middle),
            (first_middle, "owns", second_middle),
            (second_middle, "located in", target)):
        kb.add_fact(first, relation, second, source)
    if with_kinds:
        kb.add_fact(first_middle, "is-a", "person", source)
        kb.add_fact(second_middle, "is-a", "asset", source)
    if label == "positive":
        kb.add_fact(subject, "reaches", target, source)
    elif label == "negative":
        kb.add_negative_fact(subject, "reaches", target, source)


def seeded(*, negative_holdout: bool = False,
           missing_second_holdout_kinds: bool = False) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    add_chain(kb, "Ada", "Bea", "Crux", "London", "train:one")
    add_chain(kb, "Dee", "Eli", "Fork", "Rome", "train:two")
    add_chain(kb, "Gray", "Hel", "Ink", "Oslo", "holdout:one")
    add_chain(kb, "Jo", "Kai", "Lamp", "Perth", "holdout:two",
              label="negative" if negative_holdout else "positive",
              with_kinds=not missing_second_holdout_kinds)
    add_chain(kb, "Nia", "Oren", "Pike", "Sydney", "runtime:one",
              label="none")
    return kb


def main() -> None:
    kb = seeded()
    binary = kb.discover_inference_rules()
    require(binary.complete and not any(candidate.third_relation
                                        for candidate in binary.candidates),
            "typed three-premise candidates leaked into the default binary search")
    try:
        kb.discover_inference_rules(max_arity=4)
    except ValueError:
        pass
    else:
        raise SystemExit("rule discovery accepted arity above the fixed cap of three")

    discovery = kb.discover_inference_rules(max_arity=3)
    candidates = [candidate for candidate in discovery.candidates
                  if candidate.first_relation == "employs"
                  and candidate.second_relation == "owns"
                  and candidate.third_relation == "located in"
                  and candidate.conclusion_relation == "reaches"]
    require(discovery.complete and len(candidates) == 1,
            f"typed ternary rule was not uniquely discovered: {discovery}")
    candidate = candidates[0]
    require((candidate.middle_kind, candidate.second_middle_kind)
            == ("person", "asset")
            and len(candidate.positive_examples) == 4
            and all("first_kind" in example and "second_kind" in example
                    for example in candidate.positive_examples),
            "candidate omitted its two exact kind guards or evidence")

    reviews = kb.review_inference_rules("holdout:", max_arity=3)
    matching = [review for review in reviews.reviews
                if review.candidate.third_relation == "located in"
                and review.candidate.conclusion_relation == "reaches"]
    require(reviews.complete and len(matching) == 1
            and matching[0].validation is not None
            and matching[0].validation.status == "validated"
            and len(matching[0].validation.positive_examples) == 2,
            f"held-out typed examples did not validate the candidate: {reviews}")

    accepted = kb.accept_inference_rule_candidate(
        1, "employment-route", "holdout:", max_arity=3)
    require(accepted.accepted and accepted.rule is not None
            and accepted.rule.third_relation == "located in"
            and accepted.rule.middle_kind == "person"
            and accepted.rule.second_middle_kind == "asset",
            f"validated typed candidate was not installed correctly: {accepted}")
    inferred = kb.infer_relation("Nia", "reaches", "Sydney")
    require(inferred.status == "answered" and inferred.proofs
            and all(proof.get("kind") == "rule" for proof in inferred.proofs),
            f"accepted typed rule did not derive the runtime target: {inferred}")
    fact_rows = [asdict(fact) for fact in kb.facts()]
    rule_rows = [asdict(rule) for rule in kb._inference_rules.values()]
    for proof in inferred.proofs:
        checked = verify_inference_proof(
            proof, fact_rows, rule_rows,
            expected_conclusion=inferred.conclusion)
        require(checked.valid, f"independent checker rejected typed discovery proof: {checked}")

    # The learned three-premise schema must also be reachable through an
    # ordinary-language yes/no turn, with its typed middle witnesses in proof.
    natural_language = respond(
        CRMSDialogue(kb), "Does Nia reach Sydney?")
    require(natural_language.status == "answered"
            and natural_language.response is not None
            and natural_language.response.truth is True
            and natural_language.response.inference_proofs
            and "employment-route" in json.dumps(
                natural_language.response.inference_proofs),
            f"natural-language chat did not use the learned typed rule: "
            f"{natural_language}")
    natural_proof = natural_language.response.inference_proofs[0]
    natural_check = verify_inference_proof(
        natural_proof, fact_rows, rule_rows,
        expected_conclusion={
            "subject": "Nia", "relation": "reaches", "object": "Sydney"})
    require(natural_check.valid,
            f"natural-language typed proof did not independently verify: "
            f"{natural_check}")
    missing_kind = seeded()
    missing_kind.accept_inference_rule_candidate(
        1, "employment-route", "holdout:", max_arity=3)
    require(missing_kind.remove_fact(
        "Oren", "is-a", "person", "runtime:one"),
        "runtime kind witness could not be removed for the negative control")
    untyped_chat = respond(
        CRMSDialogue(missing_kind), "Does Nia reach Sydney?")
    require(untyped_chat.status != "answered"
            or untyped_chat.response is None
            or untyped_chat.response.truth is not True,
            "natural-language chat ignored a required typed middle witness")

    contradicted = seeded(negative_holdout=True).review_inference_rules(
        "holdout:", max_arity=3)
    rejected = [review for review in contradicted.reviews
                if review.candidate.third_relation == "located in"
                and review.candidate.conclusion_relation == "reaches"]
    require(len(rejected) == 1 and rejected[0].validation is not None
            and rejected[0].validation.status == "low-confidence",
            "balanced held-out positive and negative labels were over-trusted")

    missing_kinds = seeded(missing_second_holdout_kinds=True).review_inference_rules(
        "holdout:", max_arity=3)
    under_supported = [review for review in missing_kinds.reviews
                       if review.candidate.third_relation == "located in"
                       and review.candidate.conclusion_relation == "reaches"]
    require(len(under_supported) == 1 and under_supported[0].validation is not None
            and under_supported[0].validation.status == "insufficient"
            and len(under_supported[0].validation.positive_examples) == 1,
            "holdout validation accepted a chain without both held-out type guards")

    bounded = kb.discover_inference_rules(max_arity=3, max_expansions=1)
    require(not bounded.complete,
            "candidate discovery hid an exhausted expansion budget")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "list-rules.json"
        rule_session = root / "rule-session.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(state_path), "--rules", str(rules_path),
             "--rule-session", str(rule_session)],
            input=("/suggest-inference-rules 2|holdout:|arity=3\n"
                   "/accept-inference-rule 1|employment-route|holdout:|arity=3\n"
                   "/infer-relation Nia|reaches|Sydney\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(process.returncode == 0
                and "middle kinds: person, asset" in process.stdout
                and "holdout=validated" in process.stdout
                and "Accepted validated rule employment-route" in process.stdout
                and "Because Nia — employs → Oren and Oren — owns → Pike and "
                    "Pike — located in → Sydney and Oren — is-a → person and "
                    "Pike — is-a → asset, Nia — reaches → Sydney "
                    "(rule employment-route)." in process.stdout,
                f"typed discovery/review/use CLI flow failed:\n"
                f"{process.stdout}\n{process.stderr}")
        persisted = CRMSKnowledgeBase.load(knowledge_path)
        saved_rule = next(iter(persisted._inference_rules.values()))
        require(saved_rule.third_relation == "located in"
                and saved_rule.middle_kind == "person"
                and saved_rule.second_middle_kind == "asset",
                "typed discovered rule lost its schema on reload")

    print("typed three-premise rule discovery diagnostic: PASS")
    print("learned three-premise rule reaches natural-language chat with an independently verified proof: PASS")
    print("natural-language reasoning abstains when a required kind witness is absent: PASS")
    print("bounded discovery, explicit kinds, source-heldout validation, negative rejection, proof verification, CLI and persistence: PASS")


if __name__ == "__main__":
    main()
