"""Feed verified natural-language reasoning results into a learned procedure.

The exercise learns a typed three-premise relation rule from training examples,
validates it against source-held-out facts, and asks ordinary-language chat
queries about runtime candidates. Only independently verified positive proofs
become input values to a separately learned list procedure. A fresh chat process
also answers the reasoning queries and generates the procedure artifact.

This is a controlled integration diagnostic. Reasoning facts and procedure
demonstrations are explicit fixtures; it is not autonomous source-only learning
or a general task planner.
"""
from __future__ import annotations

from dataclasses import asdict
import copy
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import generate_python
from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_chain(kb: CRMSKnowledgeBase, subject: str, first: str,
              second: str, target: str, source: str, *,
              conclusion: str = "positive") -> None:
    kb.add_fact(subject, "employs", first, source)
    kb.add_fact(first, "owns", second, source)
    kb.add_fact(second, "located in", target, source)
    kb.add_fact(first, "is-a", "person", source)
    kb.add_fact(second, "is-a", "asset", source)
    if conclusion == "positive":
        kb.add_fact(subject, "reaches", target, source)
    elif conclusion == "negative":
        kb.add_negative_fact(subject, "reaches", target, source)
    elif conclusion != "none":
        raise ValueError(conclusion)


def discover_and_accept(kb: CRMSKnowledgeBase) -> None:
    add_chain(kb, "Ada", "Bea", "Crux", "London", "train:one")
    add_chain(kb, "Dee", "Eli", "Fork", "Rome", "train:two")
    add_chain(kb, "Gray", "Hel", "Ink", "Oslo", "holdout:one")
    add_chain(kb, "Jo", "Kai", "Lamp", "Perth", "holdout:two")
    discovery = kb.discover_inference_rules(max_arity=3)
    matches = [(number, candidate) for number, candidate
               in enumerate(discovery.candidates, start=1)
               if (candidate.first_relation == "employs"
                   and candidate.second_relation == "owns"
                   and candidate.third_relation == "located in"
                   and candidate.conclusion_relation == "reaches"
                   and candidate.middle_kind == "person"
                   and candidate.second_middle_kind == "asset")]
    require(discovery.complete and len(matches) == 1,
            f"typed reasoning rule was not uniquely discovered: {discovery}")
    review = kb.review_inference_rules("holdout:", max_arity=3)
    reviewed = [item for item in review.reviews
                if item.candidate.conclusion_relation == "reaches"
                and item.candidate.third_relation == "located in"]
    require(review.complete and len(reviewed) == 1
            and reviewed[0].validation is not None
            and reviewed[0].validation.status == "validated",
            f"rule failed source-held-out validation: {review}")
    number, _candidate = matches[0]
    accepted = kb.accept_inference_rule_candidate(
        number, "employment-route", "holdout:", max_arity=3)
    require(accepted.accepted and accepted.rule is not None,
            f"validated rule could not be accepted: {accepted}")


def learn_procedure() -> CRMSModel:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    inputs = (
        [4, 1, 4, 2], [3, 3, 1], [-1, 2, -1, 0], [0, 0],
        [1, 2, 3], [], [2, 2, 1, 1],
    )
    procedures = {
        "remove duplicate values": lambda values: list(dict.fromkeys(values)),
        "reverse the list": lambda values: list(reversed(values)),
        "remove duplicate values then reverse the list": lambda values: list(
            reversed(list(dict.fromkeys(values)))),
    }
    for phrase, operation in procedures.items():
        examples = [(values, operation(values)) for values in inputs]
        learned = model.teach(
            phrase, examples,
            source_ids=["codex:procedure-example"] * len(examples),
            labeler_ids=["codex:task-labeler"] * len(examples),
            instruction_source_ids=["codex:phrase-association"] * len(examples),
            _use_language_prior=False)
        require(learned.status == "learned",
                f"procedure did not learn for {phrase!r}: {learned}")
    return model


def main() -> None:
    kb = CRMSKnowledgeBase()
    discover_and_accept(kb)
    # Multiple independent chains prove record 4; records 7 and 8 are explicit
    # negative and open-world controls; record 6 has conflicting evidence.
    add_chain(kb, "Nia", "Orin", "Axle", "12", "runtime:record-12",
              conclusion="none")
    add_chain(kb, "Nia", "Pia", "Bolt", "4", "runtime:record-4a",
              conclusion="none")
    add_chain(kb, "Nia", "Quin", "Cove", "4", "runtime:record-4b",
              conclusion="none")
    add_chain(kb, "Nia", "Rae", "Dune", "9", "runtime:record-9",
              conclusion="none")
    kb.add_negative_fact("Nia", "reaches", "7", "runtime:record-7-negative")

    dialogue = CRMSDialogue(kb)
    direct_results = {}
    proof_record_ids: list[int] = []
    facts = [asdict(fact) for fact in kb.facts()]
    rules = [asdict(rule) for rule in kb._inference_rules.values()]
    for record_id in ("12", "4", "9", "7", "8"):
        turn = respond(dialogue, f"Does Nia reach {record_id}?")
        direct_results[record_id] = turn
        inferred = kb.infer_relation("Nia", "reaches", record_id)
        if record_id in {"12", "4", "9"}:
            require(turn.status == "answered" and turn.response is not None
                    and turn.response.truth is True,
                    f"chat did not answer the supported record {record_id}: {turn}")
            require(inferred.status == "answered" and inferred.proofs,
                    f"engine did not prove record {record_id}: {inferred}")
            for proof in inferred.proofs:
                checked = verify_inference_proof(
                    proof, facts, rules,
                    expected_conclusion={
                        "subject": "Nia", "relation": "reaches",
                        "object": record_id,
                    })
                require(checked.valid,
                        f"independent verifier rejected record {record_id}: {checked}")
                proof_record_ids.append(int(record_id))
        elif record_id == "7":
            require(turn.response is not None and turn.response.truth is False,
                    f"explicit negative was not preserved: {turn}")
        else:
            require(turn.status == "unknown"
                    and (turn.response is None or turn.response.truth is not True),
                    f"open-world miss was not an abstention: {turn}")

    conflicted = copy.deepcopy(kb)
    add_chain(conflicted, "Nia", "Sol", "Tern", "6", "runtime:record-6",
              conclusion="positive")
    conflicted.add_negative_fact(
        "Nia", "reaches", "6", "runtime:record-6-negative")
    conflict_result = conflicted.infer_relation("Nia", "reaches", "6")
    conflict_turn = respond(
        CRMSDialogue(conflicted), "Does Nia reach 6?")
    require(conflict_result.status == "ambiguous"
            and conflict_turn.response is not None
            and conflict_turn.response.truth is not True,
            f"conflicted record was accepted: {conflict_turn} / {conflict_result}")

    require(proof_record_ids == [12, 4, 4, 9],
            f"proof multiplicity was not retained as procedure input: {proof_record_ids}")
    procedure = learn_procedure()
    request = "remove duplicate values then reverse the list"
    artifact = generate_python(procedure, request)
    require(artifact is not None,
            "learned procedure could not produce a code artifact")
    namespace: dict[str, object] = {}
    exec(compile(artifact.source, "<verified-reasoning-procedure>", "exec"), namespace)
    actual = namespace["transform"](proof_record_ids)
    expected = [9, 4, 12]
    require(actual == expected and namespace["validate_examples"](),
            f"procedure failed on verified proof outputs: {actual} != {expected}")
    require(artifact.provenance_id and artifact.evidence_phrases,
            "generated procedure omitted its learnable evidence lineage")

    # Save a pre-correction model for the fresh-process chat check. The
    # following source-retraction check deliberately mutates only `kb`.
    chat_kb = copy.deepcopy(kb)
    practiced = kb.practice_relation("Nia", "reaches", "12")
    retained = kb.retrieve_derived_case(
        "Nia", "reaches", "12", record_use=False)
    require(practiced.status == "answered" and retained is not None
            and retained["status"] == "verified",
            "verified reasoning result was not retained as a separate derived case")
    require(kb.remove_fact(
        "Nia", "employs", "Orin", "runtime:record-12"),
        "source premise correction failed")
    require(kb.retrieve_derived_case(
        "Nia", "reaches", "12", record_use=False) is None
            and any(case["status"] == "stale_or_conflicted"
                    for case in kb.derived_cases()),
            "source correction did not invalidate the practiced conclusion")

    with tempfile.TemporaryDirectory(prefix="crms-reasoned-procedure-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        rule_path = root / "list-rules.json"
        chat_kb.save(knowledge_path)
        procedure.save(rule_path)
        CRMSResearchIndex().save(root / "index.json")
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(rule_path),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command,
            input=("Does Nia reach 12?\nwhy?\n"
                   "Does Nia reach 7?\nDoes Nia reach 8?\n"
                   "Write Python code to remove duplicate values then reverse the list\n"
                   "/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = chat.stdout + chat.stderr
        require(chat.returncode == 0 and "Traceback" not in output
                and "CRMS> Yes." in output
                and "Because Nia — employs → Orin" in output
                and "CRMS> No." in output
                and "I don't have a direct source statement for this exact proposition"
                    in output
                and "Generated Python" in output,
                f"fresh natural-language chat did not preserve the composed paths:\n{output}")

    print("typed three-premise rule discovered and source-held-out validated: PASS")
    print("natural-language answers produced independently verified runtime proofs: PASS")
    print("negative, conflicting, and unknown records were excluded: PASS")
    print("proof-derived IDs fed a learned, executable list procedure: PASS")
    print("practiced conclusion remained separate and invalidated after correction: PASS")
    print("fresh chat answered reasoning probes and generated the procedure artifact: PASS")
    print("scope: integrated controlled task; not autonomous raw-source learning or general planning")


if __name__ == "__main__":
    main()
