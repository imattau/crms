"""Learn a reviewed predicate alignment from a large mixed corpus in chat."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402
from experiments.v1_251_large_corpus_chat_stress import corpus_rows  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-296-") as folder:
        root = Path(folder)
        index = CRMSSQLiteResearchIndex(root / "research.sqlite")
        for document_id, title, text in corpus_rows():
            index.add_document(document_id, title, text,
                               f"{document_id}.txt")
        # Each alias sentence is in a different record from the canonical
        # sentence. Two distinct pairs support each variant independently.
        for verb, numbers in (("passes through", (0, 1)),
                              ("runs through", (2, 3))):
            for number in numbers:
                sentence = (
                    f"The Serein River {number:04d} {verb} "
                    f"Nacre City {number:04d}.")
                index.add_document(
                    f"{verb.split()[0]}-{number:04d}",
                    "Alternate waterway record", sentence,
                    f"{verb.split()[0]}-{number:04d}.txt")
        # Typed questions need explicit class statements for the same
        # subjects. Keep them in separate records so the integration test
        # checks composition of predicate transfer and type grounding.
        for number, requested_type in ((0, "stream"), (4, "waterway")):
            index.add_document(
                f"type-{number:04d}", "Waterway classification record",
                f"The Serein River {number:04d} is a {requested_type}.",
                f"type-{number:04d}.txt")

        knowledge = CRMSKnowledgeBase()
        proposals = knowledge.propose_corpus_predicate_alignments(
            index, maximum_documents=1_300, maximum_sentences=30_000,
            maximum_proposals=1_000)
        proposal = next((item for item in proposals
                         if {item["relation"], item["predicate_phrase"]}
                         == {"flows through", "passes through"}), None)
        if proposal is None or proposal["distinct_pairs"] != 2:
            raise SystemExit(
                "large-corpus shared-pair evidence did not propose the river "
                f"predicate alignment: {proposals[:8]}")
        if (proposal["canonical_documents"] != 2
                or proposal["alias_documents"] != 2
                or knowledge.facts()):
            raise SystemExit(
                "alignment proposal lacks independent sources or changed facts "
                "before review")
        run_proposal = next((item for item in proposals
                             if {item["relation"], item["predicate_phrase"]}
                             == {"flows through", "runs through"}), None)
        if (run_proposal is None or run_proposal["distinct_pairs"] != 2
                or run_proposal["canonical_documents"] != 2
                or run_proposal["alias_documents"] != 2):
            raise SystemExit(
                "independent shared-pair evidence did not propose the second "
                f"predicate variant: {proposals[:12]}")
        accepted = []
        for candidate in (proposal, run_proposal):
            accepted.append(knowledge.accept_corpus_predicate_alignment(
                candidate["proposal_id"], index, maximum_documents=1_300,
                maximum_sentences=30_000, maximum_proposals=1_000))
        if {item["predicate_phrase"] for item in accepted} != {
                "passes through", "runs through"}:
            raise SystemExit(f"unexpected accepted wordings: {accepted}")

        knowledge_path = root / "knowledge.json"
        knowledge.save(knowledge_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(root / "research.sqlite"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math", str(root / "math.json"),
            "--math-session", str(root / "math-session.json"),
            "--translations", str(root / "translations.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        queries = (
            "Which stream passes through Nacre City 0000?",
            "Which waterway runs through Nacre City 0004?",
        )
        run = subprocess.run(
            command, input="\n".join((*queries, "/quit")) + "\n", text=True,
            capture_output=True, cwd=root, timeout=90, check=False)
        if run.returncode:
            raise SystemExit(
                "chat failed after a reviewed corpus alignment:\n"
                + run.stderr + run.stdout)
        if ("The Serein River 0000 flows through Nacre City 0000." not in run.stdout
                or "The Serein River 0004 flows through Nacre City 0004." not in run.stdout
                or "reviewed relation alignment links 'flows through'" not in run.stdout):
            raise SystemExit(
                "accepted corpus wording did not transfer to the held-out "
                "natural-language question:\n" + run.stdout)
        if ("candidate facts still need review" not in run.stdout
                or "passes through → Nacre City 0000" not in run.stdout
                or "question wording 'runs through'" not in run.stdout
                or "direct source class evidence for a stream" not in run.stdout
                or "direct source class evidence for a waterway" not in run.stdout):
            raise SystemExit(
                "typed relation transfer lost its review boundary:\n"
                + run.stdout)
        print("PASS: 1,200 mixed documents plus two independent alias records")
        print("PASS: two independent pairs each proposed and licensed a predicate variant")
        print("PASS: no facts changed before explicit acceptance")
        print("PASS: two typed chat questions composed both reviewed variants with separately sourced class evidence")
        index.close()


if __name__ == "__main__":
    main()
