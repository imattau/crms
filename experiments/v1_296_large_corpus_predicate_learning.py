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
        # sentence. The same two entity pairs must recur under both verbs.
        for number in (0, 1):
            sentence = (
                f"The Serein River {number:04d} passes through "
                f"Nacre City {number:04d}.")
            index.add_document(
                f"alternate-{number:04d}", "Alternate waterway record",
                sentence, f"alternate-{number:04d}.txt")

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
        accepted = knowledge.accept_corpus_predicate_alignment(
            proposal["proposal_id"], index, maximum_documents=1_300,
            maximum_sentences=30_000, maximum_proposals=1_000)
        if accepted["predicate_phrase"] != "passes through":
            raise SystemExit(f"unexpected accepted wording: {accepted}")

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
        query = "Which river passes through Nacre City 0000?"
        run = subprocess.run(
            command, input=query + "\n/quit\n", text=True,
            capture_output=True, cwd=root, timeout=90, check=False)
        if run.returncode:
            raise SystemExit(
                "chat failed after a reviewed corpus alignment:\n"
                + run.stderr + run.stdout)
        if "The Serein River 0000 flows through Nacre City 0000." not in run.stdout:
            raise SystemExit(
                "accepted corpus wording did not transfer to the held-out "
                "natural-language question:\n" + run.stdout)
        print("PASS: 1,200 mixed documents plus two independent alias records")
        print("PASS: two cross-source entity pairs proposed flows-through alignment")
        print("PASS: no facts changed before explicit acceptance")
        print("PASS: accepted wording answered a cited held-out chat question")
        index.close()


if __name__ == "__main__":
    main()
