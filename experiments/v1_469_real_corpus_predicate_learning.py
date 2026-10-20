"""Exercise reviewed phrase learning using cited pages from real SimpleWiki.

This is an integration experiment, not a general learner benchmark. It copies
only examples from the already reviewed `capital city of` alignment into a
temporary index, accepts the exact proposal through CRMS's review API, then
checks a held-out question through a fresh chat process and SQLite reload.
The structured `capital` field mapping is currently hand-coded in
`crms_knowledge.py`; acceptance is explicitly Codex-reviewed and the source
pages all come from one encyclopedia.

Run:
    python3 experiments/v1_469_real_corpus_predicate_learning.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402

SOURCE_INDEX = PROJECT / "data" / "crms_simplewiki_research.sqlite"
DISCOVERY_REPORT = PROJECT / "experiments" / "reports" / (
    "v1_468_pair_overlap_discovery.json")
REVIEW_REPORT = PROJECT / "experiments" / "reports" / (
    "v1_464_unmapped_structured_predicate_review.json")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    discovery = json.loads(DISCOVERY_REPORT.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_REPORT.read_text(encoding="utf-8"))
    candidate = next((row for row in discovery["candidates"]
                      if row["field"] == "capital"
                      and row["title_role"] == "title-object"
                      and row["dominant_training_phrase"] == "capital of"
                      and row["candidate_phrase"] == "capital city of"), None)
    require(candidate is not None,
            "the reviewed capital phrase candidate was not in the frozen report")
    judgment = next((row.get("judgment") for row in review["candidates"]
                     if row["field"] == candidate["field"]
                     and row["title_role"] == candidate["title_role"]
                     and row["dominant_training_phrase"]
                         == candidate["dominant_training_phrase"]
                     and row["candidate_phrase"] == candidate["candidate_phrase"]),
                    None)
    require(judgment == "same_relation_candidate",
            f"candidate review did not license the expected alignment: {judgment}")

    rows = candidate["support"][:4] + candidate["heldout_support"][:2]
    require(len({row["document_id"] for row in rows}) == len(rows),
            "the selected candidate evidence is not from distinct pages")
    require(all(row["field"] == "capital"
                and row["title_role"] == "title-object" for row in rows),
            "candidate rows do not match the reviewed field/role");

    with tempfile.TemporaryDirectory(prefix="crms-v1-469-") as folder:
        root = Path(folder)
        source = CRMSSQLiteResearchIndex(SOURCE_INDEX, read_only=True)
        subset_path = root / "sources.sqlite"
        subset = CRMSSQLiteResearchIndex(subset_path)
        try:
            for row in rows:
                document = source.document(row["document_id"])
                require(document.title == row["title"],
                        "candidate title no longer matches the source page")
                require(source.resolve_citation(row["field_citation"])
                        == row["field_line"],
                        "structured field citation is stale")
                require(source.resolve_citation(row["sentence_citation"])
                        == row["sentence"],
                        "prose citation is stale")
                subset.add_document(document.document_id, document.title,
                                    document.text, document.location)
        finally:
            source.close()
            subset.close()

        index = CRMSSQLiteResearchIndex(subset_path, read_only=True)
        knowledge = CRMSKnowledgeBase()
        options = {"minimum_pairs": 2, "maximum_documents": 20,
                   "maximum_sentences": 1000, "maximum_proposals": 100}
        proposals = knowledge.propose_corpus_predicate_alignments(index, **options)
        matches = [row for row in proposals
                   if row.get("evidence_kind") == "structured_field_prose"
                   and row["relation"] == "capital of"
                   and row["predicate_phrase"] == "capital city of"]
        require(len(matches) == 1,
                f"expected one real-source proposal, found {len(matches)}")
        proposal = matches[0]
        heldout = proposal["holdout_support"]
        require(heldout and not knowledge.facts(),
                "proposal must be review-only before explicit acceptance")
        held_question = (
            f"What city is the capital city of {heldout[0]['object']}?")
        require(knowledge.ask(held_question).status == "unknown",
                "an unreviewed proposal licensed a question frame")

        # Codex's reviewed label authorizes this explicit experimental accept;
        # the review and candidate generator are not independent.
        accepted = knowledge.accept_corpus_predicate_alignment(
            proposal["proposal_id"], index, **options)
        validation = accepted["heldout_validation"]
        require(validation["checks"]
                and all(item["heldout_document"]
                        not in validation["training_documents"]
                        for item in validation["checks"]),
                f"held-out pages overlapped with phrase teaching: {validation}")
        require(all("capital city of" in check["matched_template"]
                    for check in validation["checks"]),
                f"held-out question did not use the candidate phrase: {validation}")
        for check in validation["checks"]:
            require(index.resolve_citation(check["source"]),
                    "held-out answer citation did not resolve")

        knowledge_path = root / "knowledge.sqlite"
        knowledge.save(knowledge_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        replay = restored.ask(held_question)
        require(replay.status == "answered"
                and replay.answer == validation["answer"],
                f"learned frame did not survive SQLite reload: {replay}")
        unsupported = restored.ask(
            f"What city is the largest city of {heldout[0]['object']}?")
        require(unsupported.status == "unknown",
                f"unsupported relation form was promoted: {unsupported}")

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(subset_path),
            "--index-read-only", "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        process = subprocess.run(
            command, input=held_question + "\n/quit\n", text=True,
            capture_output=True, cwd=root, timeout=60,
            env=os.environ.copy(), check=False)
        require(process.returncode == 0,
                f"fresh chat process failed: {process.stderr}\n{process.stdout}")
        require(validation["answer"] in process.stdout
                and "Source:" in process.stdout,
                f"fresh chat did not answer with cited knowledge:\n{process.stdout}")
        index.close()

    print("PASS: real source candidates remain inert before explicit review")
    print(f"PASS: reviewed capital wording learned from {len(proposal['training_support'])} pages")
    print(f"PASS: held-out question passed on {len(validation['checks'])} page(s)")
    print("PASS: SQLite reload and fresh chat preserve answer and citation")
    print("PASS: unsupported relation wording remains unknown")
    print("LIMIT: one SimpleWiki relation, hand-coded field map, Codex review")


if __name__ == "__main__":
    main()
