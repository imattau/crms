"""Compose reviewed relation wording with proof-backed type inheritance."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(root: Path, knowledge_path: Path, index_path: Path,
             questions: tuple[str, ...], label: str) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path), "--index", str(index_path),
        "--dialogue-state", str(root / f"{label}-dialogue.json"),
        "--rules", str(root / f"{label}-rules.json"),
        "--rule-session", str(root / f"{label}-rule-session.json"),
        "--math", str(root / f"{label}-math.json"),
        "--translations", str(root / f"{label}-translations.json"),
    ]
    result = subprocess.run(
        command, input="\n".join((*questions, "/quit")) + "\n",
        text=True, capture_output=True, cwd=root, timeout=60, check=False)
    require(result.returncode == 0,
            f"{label} CLI failed: {result.stderr}\n{result.stdout}")
    return result.stdout


def main() -> None:
    index = CRMSResearchIndex()
    knowledge = CRMSKnowledgeBase()
    training_pairs = (
        ("The Serein River 0000", "Nacre City 0000", "0000"),
        ("The Amber River 0001", "Nacre City 0001", "0001"),
    )

    # The canonical relation is taught from two distinct source documents.
    for subject, obj, key in training_pairs:
        document_id = f"flow-{key}"
        sentence = f"{subject} flows through {obj}."
        index.add_document(document_id, f"Route {key}", sentence,
                           f"{document_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document_id)
        knowledge.add_fact_from_hit(subject, "flows through", obj, index, hit)
        knowledge.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="flows through", obj=obj,
            predicate_phrase="flows through", research_index=index, hit=hit)

    # Distinct documents repeat both pairs using a separate surface form.
    for subject, obj, key in training_pairs:
        document_id = f"run-{key}"
        index.add_document(document_id, f"Alternate route {key}",
                           f"{subject} runs through {obj}.",
                           f"{document_id}.txt")

    proposal = next((item for item in
                     knowledge.propose_predicate_form_alignments(index)
                     if item["relation"] == "flows through"
                     and item["predicate_phrase"] == "runs through"), None)
    require(proposal is not None and proposal["review_required"]
            and proposal["independent_documents"] >= 2,
            f"relation wording did not produce a cited review proposal: {proposal!r}")

    # A third, unseen route supplies canonical wording only. The type hierarchy
    # is explicit and separately licensed by its transitive is-a schema.
    heldout_rows = (
        ("route-0133", "Route 0133",
         "The Serein River 0133 flows through Nacre City 0133.",
         "The Serein River 0133", "flows through", "Nacre City 0133"),
        ("kind-0133", "Classification 0133",
         "The Serein River 0133 is a river.",
         "The Serein River 0133", "is-a", "river"),
        ("river-waterway", "Waterway taxonomy",
         "A river is a waterway.", "river", "is-a", "waterway"),
    )
    for document_id, title, sentence, subject, relation, obj in heldout_rows:
        index.add_document(document_id, title, sentence,
                           f"{document_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document_id)
        knowledge.add_fact_from_hit(subject, relation, obj, index, hit)
    knowledge.add_relation_type(
        "is-a", "transitive", "reviewed:transitive-type-schema")

    with tempfile.TemporaryDirectory(prefix="crms-v1-514-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        knowledge.save(knowledge_path)
        index.save(index_path)

        before = run_chat(
            root, knowledge_path, index_path,
            ("Which waterway runs through Nacre City 0133?",), "before")
        require("is a waterway that runs through" not in before,
                f"unreviewed relation wording was already accepted: {before}")

        accepted = knowledge.accept_predicate_form_alignment(
            proposal["proposal_id"], index)
        require(accepted["predicate_phrase"] == "runs through",
                f"acceptance licensed unexpected wording: {accepted!r}")
        knowledge.save(knowledge_path)
        index.save(index_path)

        output = run_chat(
            root, knowledge_path, index_path,
            ("Which waterway runs through Nacre City 0133?",
             "Which stream runs through Nacre City 0133?"), "after")
        require("The Serein River 0133 is a waterway that runs through "
                "Nacre City 0133." in output,
                f"reviewed wording and type proof did not compose: {output}")
        for title in ("Route 0133", "Classification 0133",
                      "Waterway taxonomy", "accepted transitive is-a proof",
                      "source wording 'flows through' is linked to the question "
                      "wording 'runs through'"):
            require(title in output,
                    f"composed answer omitted provenance {title!r}: {output}")
        require("couldn't independently verify that the subject is a stream"
                in output
                and "The Serein River 0133 is a stream that runs through"
                    not in output,
                f"an unsupported narrower type was promoted: {output}")

    print("PASS: relation wording remains inactive until explicit review")
    print("PASS: reviewed relation paraphrase composes with a held-out route")
    print("PASS: transitive type proof and source citations survive fresh CLI chat")
    print("PASS: waterway is supported; stream remains unverified and unasserted")
    print("LIMIT: controlled synthetic corpus; broad relation/type transfer remains open")


if __name__ == "__main__":
    main()
