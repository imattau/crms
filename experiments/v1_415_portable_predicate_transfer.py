"""A reviewed predicate alignment survives portable-model packaging."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_package import export_model_database, install_model_database
from crms_research import CRMSSQLiteResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-portable-predicate-") as folder:
        root = Path(folder)
        index_path = root / "source.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        rows = (
            ("canonical-0", "Record 0000",
             "The Serein River 0000 flows through Nacre City 0000."),
            ("canonical-1", "Record 0001",
             "The Serein River 0001 flows through Nacre City 0001."),
            ("alias-0", "Alternate record 0000",
             "The Serein River 0000 passes through Nacre City 0000."),
            ("alias-1", "Alternate record 0001",
             "The Serein River 0001 passes through Nacre City 0001."),
            # This entity is held out from alignment induction. Its text uses
            # only the canonical predicate, so the accepted relation family
            # must make the new question wording retrieve this sentence.
            ("heldout-2", "Record 0002",
             "The Serein River 0002 flows through Nacre City 0002."),
        )
        for document_id, title, sentence in rows:
            index.add_document(document_id, title, sentence,
                               f"{document_id}.txt")

        knowledge = CRMSKnowledgeBase()
        empty_knowledge_path = root / "empty-knowledge.json"
        CRMSKnowledgeBase().save(empty_knowledge_path)
        proposals = knowledge.propose_corpus_predicate_alignments(
            index, maximum_documents=20, maximum_sentences=100,
            maximum_proposals=100)
        proposal = next((item for item in proposals
                         if {item["relation"], item["predicate_phrase"]}
                         == {"flows through", "passes through"}), None)
        require(proposal is not None
                and proposal["distinct_pairs"] == 2
                and proposal["canonical_documents"] == 2
                and proposal["alias_documents"] == 2,
                f"independent corpus evidence did not propose alignment: {proposals!r}")
        require(not knowledge.facts(),
                "alignment discovery silently added facts")
        accepted = knowledge.accept_corpus_predicate_alignment(
            proposal["proposal_id"], index, maximum_documents=20,
            maximum_sentences=100, maximum_proposals=100)
        require(accepted["predicate_phrase"] == "passes through",
                f"unexpected accepted predicate: {accepted!r}")

        knowledge_path = root / "knowledge.json"
        rules_path = root / "rules.json"
        knowledge.save(knowledge_path)
        CRMSModel().save(rules_path)
        model_path = root / "portable.sqlite"
        export_model_database(
            model_path, knowledge=knowledge_path, rules=rules_path,
            research_index=index_path)
        index.close()
        index_path.unlink()
        installed = install_model_database(model_path, root / "installed")
        require("knowledge" in installed and "research_index" in installed,
                f"portable package omitted required memories: {installed!r}")

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(installed["knowledge"]),
            "--index", str(installed["research_index"]),
            "--rules", str(installed.get("rules", rules_path)),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
        ]
        queries = (
            "Which river passes through Nacre City 0002?",
            "Which river invents Nacre City 0002?",
        )
        run = subprocess.run(
            command, input="\n".join((*queries, "/quit")) + "\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(run.returncode == 0,
                f"portable chat failed: {run.stderr}\n{run.stdout}")
        replies = [chunk.strip() for chunk in run.stdout.split("you> ")[1:]]
        require(len(replies) == 3,
                f"chat returned {len(replies)} prompt responses for two queries and quit:\n"
                + run.stdout)
        require("The Serein River 0002 flows through Nacre City 0002." in run.stdout
                and "Source: Record 0002" in run.stdout
                and "quoted evidence, not an accepted fact" in run.stdout,
                "packaged learned relation did not retrieve held-out source text:\n"
                + run.stdout)
        negative_reply = replies[1]
        require("I found this source sentence:" not in negative_reply
                and any(marker in negative_reply.casefold() for marker in (
                    "couldn't find", "won't guess", "does not support",
                    "no grounded answer")),
                "unlicensed relation produced a source-backed answer:\n" + run.stdout)

        control = subprocess.run(
            [*command[:3], str(empty_knowledge_path), *command[4:]],
            input="Which river passes through Nacre City 0002?\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(control.returncode == 0,
                f"unlicensed control chat failed: {control.stderr}")
        require("I found this source sentence:" not in control.stdout
                and any(marker in control.stdout.casefold() for marker in (
                    "does not support a grounded answer", "couldn't find",
                    "i won't guess")),
                "held-out transfer also worked without the packaged alignment; "
                "the test did not isolate learned-language contribution:\n"
                + control.stdout)

    print("reviewed relation alignment is stored in the portable model: PASS")
    print("embedded source supports held-out predicate transfer after source removal: PASS")
    print("unlicensed relation remains unsupported: PASS")


if __name__ == "__main__":
    main()
