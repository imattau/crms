"""Measure held-out typed-relation recombination through fresh chat processes."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "experiments" / "reports" / "v1_516_recombination_transfer_packet.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_cited_fact(index: CRMSResearchIndex, knowledge: CRMSKnowledgeBase,
                   document_id: str, title: str, sentence: str,
                   subject: str, relation: str, obj: str) -> None:
    index.add_document(document_id, title, sentence, f"{document_id}.txt")
    hit = next(item for item in index.search(sentence, limit=10)
               if item.document_id == document_id)
    knowledge.add_fact_from_hit(subject, relation, obj, index, hit)


def run_chat(root: Path, knowledge_path: Path, index_path: Path,
             question: str, label: str) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path), "--index", str(index_path),
        "--feedback-db", str(root / f"{label}-feedback.sqlite3"),
        "--dialogue-state", str(root / f"{label}-dialogue.json"),
        "--rules", str(root / f"{label}-rules.json"),
        "--rule-session", str(root / f"{label}-rule-session.json"),
        "--math", str(root / f"{label}-math.json"),
        "--translations", str(root / f"{label}-translations.json"),
    ]
    result = subprocess.run(
        command, input=question + "\n/quit\n", text=True,
        capture_output=True, cwd=root, timeout=60, check=False)
    require(result.returncode == 0,
            f"{label} chat failed: {result.stderr}\n{result.stdout}")
    chunks = result.stdout.split("you> ")
    require(len(chunks) >= 2, f"{label} chat emitted no response: {result.stdout}")
    return chunks[1].strip()


def main() -> None:
    index = CRMSResearchIndex()
    knowledge = CRMSKnowledgeBase()

    training_pairs = (
        ("The Serein River 0000", "Nacre City 0000", "0000"),
        ("The Amber River 0001", "Nacre City 0001", "0001"),
    )
    training_document_ids: set[str] = set()
    for subject, obj, key in training_pairs:
        document_id = f"learn-flow-{key}"
        sentence = f"{subject} flows through {obj}."
        training_document_ids.add(document_id)
        index.add_document(document_id, f"Training route {key}", sentence,
                           f"{document_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document_id)
        knowledge.add_fact_from_hit(subject, "flows through", obj, index, hit)
        knowledge.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="flows through", obj=obj,
            predicate_phrase="flows through", research_index=index, hit=hit)

    for subject, obj, key in training_pairs:
        document_id = f"learn-alias-{key}"
        training_document_ids.add(document_id)
        sentence = f"{subject} runs through {obj}."
        index.add_document(document_id, f"Alternate training route {key}",
                           sentence, f"{document_id}.txt")

    proposal = next((candidate for candidate in
                     knowledge.propose_predicate_form_alignments(index)
                     if candidate["relation"] == "flows through"
                     and candidate["predicate_phrase"] == "runs through"), None)
    require(proposal is not None and proposal["review_required"]
            and proposal["independent_documents"] >= 2,
            f"expected a review-gated wording proposal: {proposal!r}")

    heldout_routes = (
        ("0133", "The Serein River 0133", "Nacre City 0133"),
        ("0217", "The Lark River 0217", "Birch City 0217"),
        ("0881", "The Copper River 0881", "Cinder City 0881"),
    )
    heldout_document_ids: set[str] = set()
    for key, subject, obj in heldout_routes:
        route_id = f"heldout-route-{key}"
        class_id = f"heldout-class-{key}"
        heldout_document_ids.update((route_id, class_id))
        add_cited_fact(
            index, knowledge, route_id, f"Route dossier {key}",
            f"{subject} flows through {obj}.", subject, "flows through", obj)
        add_cited_fact(
            index, knowledge, class_id, f"Classification note {key}",
            f"{subject} is a river.", subject, "is-a", "river")

    untyped_route_id = "heldout-untyped-route-0882"
    heldout_document_ids.add(untyped_route_id)
    add_cited_fact(
        index, knowledge, untyped_route_id, "Unclassified route 0882",
        "Copper 0882 flows through Cinder City 0882.", "Copper 0882",
        "flows through", "Cinder City 0882")

    taxonomy_id = "heldout-taxonomy-river-waterway"
    heldout_document_ids.add(taxonomy_id)
    add_cited_fact(
        index, knowledge, taxonomy_id, "Waterway taxonomy",
        "A river is a waterway.", "river", "is-a", "waterway")
    knowledge.add_relation_type(
        "is-a", "transitive", "reviewed:transitive-type-schema")
    require(not (training_document_ids & heldout_document_ids),
            "training and held-out source documents overlap")

    with tempfile.TemporaryDirectory(prefix="crms-v1-516-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        knowledge.save(knowledge_path)
        index.save(index_path)

        # A clean process cannot use the unreviewed language relation.
        before = run_chat(
            root, knowledge_path, index_path,
            "Which waterway runs through Nacre City 0133?", "before-review")
        require("is a waterway that runs through" not in before,
                f"unreviewed wording was already active: {before}")

        accepted = knowledge.accept_predicate_form_alignment(
            proposal["proposal_id"], index)
        require(accepted["predicate_phrase"] == "runs through",
                f"review accepted unexpected predicate: {accepted!r}")
        knowledge.save(knowledge_path)
        index.save(index_path)

        positive_cases = [
            (f"Which waterway runs through {obj}?",
             f"{subject} is a waterway that runs through {obj}.", key)
            for key, subject, obj in heldout_routes
        ]
        results = []
        for question, expected, key in positive_cases:
            output = run_chat(root, knowledge_path, index_path,
                              question, f"positive-{key}")
            require(expected in output,
                    f"held-out recombination failed for {question}: {output}")
            for required in (f"Route dossier {key}",
                             f"Classification note {key}",
                             "Waterway taxonomy",
                             "accepted transitive is-a proof",
                             "source wording 'flows through' is linked to the question wording 'runs through'"):
                require(required in output,
                        f"{question} omitted required provenance {required!r}: {output}")
            results.append({"question": question, "expected": expected,
                            "response": output, "status": "passed"})

        unsupported_cases = (
            ("Which stream runs through Nacre City 0133?",
             "The Serein River 0133 is a stream that runs through Nacre City 0133.",
             "couldn't independently verify"),
            ("Which river runs through Cinder City 0882?",
             "Copper 0882 is a river that runs through Cinder City 0882.",
             "couldn't independently verify"),
        )
        for number, (question, unsupported_answer, expected_limit) in enumerate(unsupported_cases):
            output = run_chat(root, knowledge_path, index_path,
                              question, f"unsupported-{number}")
            require(unsupported_answer not in output,
                    f"unsupported subtype was asserted: {question}: {output}")
            require(expected_limit in output.casefold()
                    or "couldn't find" in output.casefold()
                    or "don't have a grounded answer" in output.casefold(),
                    f"unsupported subtype did not produce a clear limit: {output}")
            results.append({"question": question,
                            "expected": "abstain; no unsupported subtype",
                            "response": output, "status": "passed"})

        # These forms vary both the interrogative and clause structure. They
        # must reach the same proof-backed realization rather than the generic
        # source-text fallback.
        probe_cases = (
            ("What waterway runs through Nacre City 0133?",
             "The Serein River 0133 is a waterway that runs through Nacre City 0133."),
            ("Name the waterway that runs through Nacre City 0133.",
             "The Serein River 0133 is a waterway that runs through Nacre City 0133."),
        )
        for number, (question, expected) in enumerate(probe_cases):
            output = run_chat(root, knowledge_path, index_path,
                              question, f"probe-{number}")
            require(expected in output,
                    f"alternate question form lost the composed answer: {question}: {output}")
            require("accepted transitive is-a proof" in output
                    and "Waterway taxonomy" in output,
                    f"alternate question form bypassed the proof/evidence route: {output}")
            results.append({"question": question, "expected": expected,
                            "response": output, "status": "passed"})

        report = {
            "experiment": "v1_516_recombination_transfer_packet",
            "training_documents": sorted(training_document_ids),
            "heldout_documents": sorted(heldout_document_ids),
            "source_disjoint": True,
            "learned_alignment": "runs through → flows through; explicitly reviewed",
            "reasoning_schema": "reviewed transitive is-a",
            "distinct_route_transfers": 3,
            "successful_positive_question_forms": sum(
                item["status"] == "passed" for item in results
                if item["expected"].startswith("The ")),
            "unsupported_type_controls": 2,
            "alternate_question_forms": 2,
            "results": results,
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n",
                          encoding="utf-8")

    print("PASS: relation wording stayed inactive before explicit review")
    print("PASS: 3/3 source-disjoint routes recombined through fresh chat")
    print("PASS: each positive retained route, classification, taxonomy, and proof provenance")
    print("PASS: 2/2 unsupported narrower types were not asserted")
    print("PASS: both 'What' and imperative 'Name the … that' forms retain the same proof")
    print(f"REPORT: {REPORT}")
    print("LIMIT: synthetic controlled domain; no representative user-task or 70B comparison")


if __name__ == "__main__":
    main()
