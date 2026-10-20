"""Connect reviewed source frames to learned reasoning and procedure composition.

The source sentences are authored fixtures. CRMS extracts and cites relation
frames; the experiment explicitly reviews those frames, validates an induced
rule on document-disjoint examples, verifies proofs, and passes only proved
IDs to a learned list procedure. This is an integration probe, not a claim of
autonomous source understanding.
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
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof
from crms_translation import CRMSTranslation


TRAIN = (
    ("train:one", "Ada is parent of Bea. Bea is parent of Cal. "
     "Ada is ancestor of Cal."),
    ("train:two", "Dee is parent of Eli. Eli is parent of Fay. "
     "Dee is ancestor of Fay."),
)
HOLDOUT = (
    ("holdout:one", "Gus is parent of Hal. Hal is parent of Ivy. "
     "Gus is ancestor of Ivy."),
    ("holdout:two", "Jo is parent of Kim. Kim is parent of Lou. "
     "Jo is ancestor of Lou."),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_index(rows: tuple[tuple[str, str], ...],
               destination: CRMSResearchIndex) -> CRMSResearchIndex:
    for document_id, text in rows:
        destination.add_document(document_id, document_id, text,
                                 f"https://{document_id.replace(':', '-')}.example/source")
    return destination


def review_relation_frames(kb: CRMSKnowledgeBase,
                           index: CRMSResearchIndex) -> None:
    proposals = kb.propose_corpus_relation_frames(index)
    for relation in ("parent of", "ancestor of"):
        proposal = next((row for row in proposals
                         if row["relation"] == relation
                         and row["polarity"] is True), None)
        require(proposal is not None and proposal["review_required"]
                and proposal["independent_documents"] == 2,
                f"source frame {relation!r} was not separately supported: "
                f"{proposals!r}")
        accepted = kb.accept_corpus_relation_frame(
            proposal["proposal_id"], index)
        expected_support = 4 if relation == "parent of" else 2
        require(len(accepted["support"]) == expected_support,
                f"review did not retain all {relation!r} examples: "
                f"{len(accepted['support'])} != {expected_support}")


def learn_procedure() -> CRMSModel:
    model = CRMSModel(max_workers=1)
    inputs = ([4, 1, 4, 2], [3, 3, 1], [-1, 2, -1, 0],
              [0, 0], [1, 2, 3], [], [2, 2, 1, 1])
    transforms = {
        "remove duplicate values": lambda xs: list(dict.fromkeys(xs)),
        "reverse the list": lambda xs: list(reversed(xs)),
        "remove duplicate values then reverse the list":
            lambda xs: list(reversed(list(dict.fromkeys(xs)))),
    }
    for phrase, transform in transforms.items():
        result = model.teach(
            phrase, [(values, transform(values)) for values in inputs],
            source_ids=["codex:procedure-demonstration"] * len(inputs),
            labeler_ids=["codex:procedure-labeler"] * len(inputs),
            instruction_source_ids=["codex:instruction-alignment"] * len(inputs),
            _use_language_prior=False)
        require(result.status == "learned",
                f"procedure component {phrase!r} did not learn: {result}")
    return model


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-source-reasoned-procedure-") as folder:
        root = Path(folder)
        full_index = CRMSResearchIndex()
        train_index = make_index(TRAIN, CRMSResearchIndex())
        holdout_index = make_index(HOLDOUT, CRMSResearchIndex())
        make_index((*TRAIN, *HOLDOUT), full_index)

        kb = CRMSKnowledgeBase()
        review_relation_frames(kb, train_index)
        holdout_kb = CRMSKnowledgeBase()
        review_relation_frames(holdout_kb, holdout_index)
        # Holdout facts are extracted and reviewed in their own corpus slice;
        # add them only after the training frames have been accepted.
        for fact in holdout_kb.facts():
            for source in fact.sources:
                kb.add_fact(fact.subject, fact.relation, fact.object, source,
                            qualifiers=dict(fact.qualifiers))

        review = kb.review_inference_rules(
            "holdout:", research_index=full_index)
        target = next((number for number, item in enumerate(review.reviews, 1)
                       if (item.candidate.first_relation,
                           item.candidate.second_relation,
                           item.candidate.conclusion_relation)
                       == ("parent of", "parent of", "ancestor of")), None)
        require(target is not None and review.complete
                and review.reviews[target - 1].validation is not None
                and review.reviews[target - 1].validation.status == "validated",
                f"source-held-out inference rule did not validate: {review}")
        accepted = kb.accept_inference_rule_candidate(
            target, "source-parent-chain", "holdout:",
            research_index=full_index)
        require(accepted.accepted and accepted.rule is not None,
                f"reviewed inference candidate was not accepted: {accepted}")

        # Runtime premises are new cited evidence. The rule must compose them;
        # the queried ancestor result is deliberately absent as a direct fact.
        for first, middle, target_id, source in (
                ("Nia", "A", "12", "runtime:12"),
                ("Nia", "B", "4", "runtime:4a"),
                ("Nia", "C", "4", "runtime:4b"),
                ("Nia", "D", "9", "runtime:9")):
            kb.add_fact(first, "parent of", middle, source)
            kb.add_fact(middle, "parent of", target_id, source)

        facts = [asdict(row) for row in kb.facts()]
        rules = [asdict(row) for row in kb._inference_rules.values()]
        proved_ids: list[int] = []
        for target_id in ("12", "4", "9"):
            result = kb.infer_relation("Nia", "ancestor of", target_id)
            require(result.status == "answered" and result.proofs,
                    f"source-learned rule failed on {target_id}: {result}")
            for proof in result.proofs:
                check = verify_inference_proof(
                    proof, facts, rules,
                    expected_conclusion={"subject": "Nia",
                                         "relation": "ancestor of",
                                         "object": target_id})
                require(check.valid,
                        f"independent proof verifier rejected {target_id}: {check}")
                proved_ids.append(int(target_id))
        unknown = kb.infer_relation("Nia", "ancestor of", "8")
        require(unknown.status == "unknown",
                f"unsupported conclusion did not abstain: {unknown}")
        require(proved_ids == [12, 4, 4, 9],
                f"proof-backed procedure inputs changed: {proved_ids}")

        conflicted = copy.deepcopy(kb)
        conflicted.add_fact("Nia", "parent of", "E", "runtime:7")
        conflicted.add_fact("E", "parent of", "7", "runtime:7")
        conflicted.add_negative_fact(
            "Nia", "ancestor of", "7", "runtime:7-negative")
        denial = conflicted.infer_relation("Nia", "ancestor of", "7")
        require(denial.reason_code == "contradiction"
                and denial.status == "ambiguous"
                and denial.proofs,
                f"proof/negative conflict was not kept ambiguous: {denial}")

        model = learn_procedure()
        request = "remove duplicate values then reverse the list"
        artifact = generate_python(model, request)
        require(artifact is not None,
                "learned procedure did not compose the two operations")
        scope: dict[str, object] = {}
        exec(compile(artifact.source, "<source-reasoned-procedure>", "exec"), scope)
        actual = scope["transform"](proved_ids)
        require(actual == [9, 4, 12] and scope["validate_examples"](),
                f"proof-backed values failed the independent oracle: {actual}")

        chat_kb = copy.deepcopy(kb)
        practiced = kb.practice_question("Is Nia an ancestor of 12?")
        require(practiced[0].status == "answered" and practiced[1],
                f"verified conclusion was not retained separately: {practiced}")
        require(kb.remove_fact("Nia", "parent of", "A", "runtime:12"),
                "source correction did not remove its runtime premise")
        require(kb.retrieve_derived_case(
            "Nia", "ancestor of", "12", record_use=False) is None,
            "derived conclusion remained available after premise correction")

        # Citations from all accepted source frames must resolve to exact text.
        for fact in (*kb.facts(), *kb.negative_facts()):
            for source in fact.sources:
                if source.startswith(("train:", "holdout:")):
                    require(full_index.resolve_citation(source),
                            f"learned source citation is stale: {source}")

        # Exercise the same learned records through a clean chat process.
        chat_kb.save(root / "knowledge.json")
        model.save(root / "rules.json")
        full_index.save(root / "index.json")
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--index", str(root / "index.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command,
            input=("Is Nia an ancestor of 12?\nwhy?\n"
                   "Is Nia an ancestor of 8?\n"
                   "Write Python code to remove duplicate values then reverse the list\n"
                   "/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = chat.stdout + chat.stderr
        require(chat.returncode == 0 and "Traceback" not in output
                and "CRMS> Yes." in output
                and "Because Nia is parent of A." in output
                and "I don't have a direct source statement" in output
                and "Generated Python" in output,
                f"fresh chat did not route reasoned procedure end to end: {output}")

    print("reviewed text frames -> held-out rule -> verified proofs: PASS")
    print("source-learned proof outputs -> composed procedure oracle: PASS")
    print("proof/negative conflict, unknown, verification, correction: PASS")
    print("fresh-process chat answer, explanation, abstention, code generation: PASS")
    print("supervision: source frames reviewed by experiment; procedure labels: Codex")


if __name__ == "__main__":
    main()
