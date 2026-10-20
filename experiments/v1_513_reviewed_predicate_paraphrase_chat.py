"""Test reviewed corpus wording transfer through fresh-process natural chat."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    knowledge = CRMSKnowledgeBase()
    canonical = (
        ("Gustave Eiffel", "the Eiffel Tower", "eiffel"),
        ("Joseph Paxton", "the Crystal Palace", "palace"),
    )

    # Teach the canonical relation and question frame from two distinct facts.
    for subject, obj, key in canonical:
        document_id = f"built-{key}"
        sentence = f"{subject} built {obj}."
        index.add_document(document_id, key, sentence, f"{document_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document_id)
        knowledge.add_fact_from_hit(subject, "build", obj, index, hit)
        knowledge.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="build", obj=obj,
            predicate_phrase="built", research_index=index, hit=hit)
        knowledge.teach_question(
            f"Who built {obj}?", relation="build", answer_field="subject",
            bound_entity=obj, answer=subject)

    require(knowledge.ask("Who constructed the Eiffel Tower?").status
            == "unknown",
            "an unreviewed wording was already active")

    # The alternate form has two distinct fact pairs in separate documents.
    for subject, obj, key in canonical:
        document_id = f"constructed-{key}"
        index.add_document(document_id, key,
                           f"{subject} constructed {obj}.",
                           f"{document_id}.txt")

    proposals = knowledge.propose_predicate_form_alignments(index)
    proposal = next((item for item in proposals
                     if item["relation"] == "build"
                     and item["predicate_phrase"] == "constructed"), None)
    require(proposal is not None,
            f"varied source pairs did not propose the paraphrase: {proposals!r}")
    require(proposal["distinct_subjects"] >= 2
            and proposal["distinct_objects"] >= 2
            and proposal["independent_documents"] >= 2
            and proposal["review_required"],
            f"proposal did not meet its evidence and review gates: {proposal!r}")

    # Discovery is report-only. The proposal cannot answer until accepted.
    require(knowledge.ask("Who constructed the Eiffel Tower?").status
            == "unknown",
            "report-only proposal changed question answering")
    accepted = knowledge.accept_predicate_form_alignment(
        proposal["proposal_id"], index)
    require(accepted["predicate_phrase"] == "constructed",
            f"acceptance licensed the wrong phrase: {accepted!r}")

    # Transfer to a new entity pair for which no `constructed` wording exists.
    heldout_sentence = "Mina built the Archive."
    index.add_document("built-archive", "Held-out entity pair",
                       heldout_sentence, "built-archive.txt")
    heldout_hit = next(item for item in index.search(
        heldout_sentence, limit=10)
        if item.document_id == "built-archive")
    knowledge.add_fact_from_hit("Mina", "build", "the Archive",
                                index, heldout_hit)

    direct = knowledge.ask("Who constructed the Archive?")
    require(direct.status == "answered"
            and direct.answer == "Mina"
            and direct.evidence,
            f"reviewed wording did not answer from stored evidence: {direct!r}")
    source_ids = {source.split("#sha256=", 1)[0]
                  for evidence in direct.evidence or []
                  for source in evidence.get("sources", [])}
    require("built-archive" in source_ids
            and "constructed-archive" not in source_ids,
            f"held-out fact evidence was not kept distinct: {source_ids!r}")
    language_source_ids = {
        source.split("#sha256=", 1)[0]
        for evidence in direct.language_evidence or []
        for support in evidence.get("support", [])
        for source in support.get("sources", [])
    }
    require({"constructed-eiffel", "constructed-palace"}
            .issubset(language_source_ids),
            f"accepted language alignment lost its teaching sources: "
            f"{language_source_ids!r}")

    with tempfile.TemporaryDirectory(prefix="crms-v1-513-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        knowledge.save(knowledge_path)
        index.save(index_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        dialogue = CRMSDialogue(restored)
        reply = respond(dialogue, "Who constructed the Archive?",
                        research_index=index)
        require(reply.status == "answered"
                and reply.response is not None
                and reply.response.answer == "Mina"
                and "Mina built the Archive." in reply.text,
                f"fresh chat did not realize the supported answer: {reply!r}")

        # Corpus support for this form must not create a free synonym inventory.
        unlicensed = respond(CRMSDialogue(restored),
                             "Who erected the Archive?",
                             research_index=index)
        require(unlicensed.status == "unknown",
                f"an unobserved synonym bypassed the evidence gate: {unlicensed!r}")

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
        run = subprocess.run(
            command,
            input="Who constructed the Archive?\n"
                  "Who erected the Archive?\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=30, check=False)
        require(run.returncode == 0,
                f"fresh CLI process failed: {run.stderr}\n{run.stdout}")
        require("Mina built the Archive." in run.stdout
                and "I couldn't find one source sentence" in run.stdout
                and run.stdout.count("Mina") == 1,
                f"fresh CLI paraphrase or negative case failed: {run.stdout}")

    print("PASS: two distinct source pairs propose constructed → build")
    print("PASS: proposals remain inert until explicit acceptance")
    print("PASS: held-out entity pair transfers through fresh-process chat with separate provenance")
    print("PASS: unobserved 'erected' wording still abstains")
    print("LIMIT: controlled source pairs; broad paraphrase transfer remains unmeasured")


if __name__ == "__main__":
    main()
