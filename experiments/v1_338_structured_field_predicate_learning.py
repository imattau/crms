"""Learn a predicate variant from source-backed structured fields.

Objective: validate a corpus learning path using infobox field labels as
explicit supervision for prose predicates.

Setup: three invented country pages each contain a structured capital field
and one matching sentence using ``capital city of``. Learn from two pages,
hold one page out, then answer the held-out question after explicit proposal
acceptance.

Metrics: proposal count/support, no pre-acceptance store mutation, held-out
answer/template/source, persistence, and rejection of stale citations.

Failure modes: wrong endpoint roles, one-example generalization, using the
held-out page as training, ambiguous sentence parses, and source changes.

Definition of success: propose one report-only alignment, accept only after
revalidation, and answer the held-out question from the accepted pattern while
preserving its source citation. One or two pages must not license it.

Run with: python3 experiments/v1_338_structured_field_predicate_learning.py
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import os

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def populate(index: CRMSSQLiteResearchIndex, count: int = 3,
             predicate: str = "capital city of") -> None:
    names = (("Nacre Nation", "Nacre City"),
             ("Veyra Nation", "Veyra City"),
             ("Orrin Nation", "Orrin City"),
             ("Tavor Nation", "Tavor City"),
             ("Eshar Nation", "Eshar City"),
             ("Mireth Nation", "Mireth City"),
             ("Ilyan Nation", "Ilyan City"),
             ("Zelrin Nation", "Zelrin City"))
    for number, (country, city) in enumerate(names[:count]):
        index.add_document(
            f"country-{number}", country,
            "Infobox country\n"
            f"capital = {city}\n\n"
            f"The {predicate} {country} is {city}.",
            f"fixture/countries/{number}.txt")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-338-") as folder:
        root = Path(folder)
        index = CRMSSQLiteResearchIndex(root / "research.sqlite")
        populate(index, count=8)
        knowledge = CRMSKnowledgeBase()
        options = {"minimum_pairs": 2, "maximum_documents": 10,
                   "maximum_sentences": 100, "maximum_proposals": 100}

        proposals = knowledge.propose_corpus_predicate_alignments(index, **options)
        matches = [item for item in proposals
                   if (item.get("evidence_kind") == "structured_field_prose"
                       and item["relation"] == "capital of"
                       and item["predicate_phrase"] == "capital city of")]
        require(len(matches) == 1,
                f"expected one structured-field proposal, got {matches}")
        proposal = matches[0]
        require(proposal["distinct_pairs"] == 8
                and len(proposal["training_support"]) == 6
                and len(proposal["holdout_support"]) == 2,
                f"training/holdout split is wrong: {proposal}")
        require(not knowledge.facts(),
                "proposal discovery changed the knowledge store before review")
        require(knowledge.ask("What city is the capital city of Orrin Nation?").status
                == "unknown",
                "unreviewed source evidence licensed a language frame")

        accepted = knowledge.accept_corpus_predicate_alignment(
            proposal["proposal_id"], index, **options)
        heldout = accepted["heldout_validation"]
        require(len(heldout["checks"]) == 2
                and all(check["heldout_document"] not in heldout["training_documents"]
                        for check in heldout["checks"])
                and heldout["matched_template"]
                == "what city is the capital city of {object}",
                f"held-out language transfer failed: {heldout}")
        require(all(check["heldout_document"] + "#" in check["source"]
                    for check in heldout["checks"]),
                f"held-out answer lost its source: {heldout}")
        require(len(knowledge.facts()) == 8,
                "acceptance did not retain the source-backed facts")

        path = root / "knowledge.sqlite"
        knowledge.save(path)
        restored = CRMSKnowledgeBase.load(path)
        replay = restored.ask(heldout["question"])
        require(replay.status == "answered" and replay.answer == heldout["answer"],
                f"accepted language learning did not persist: {replay}")

        # Exercise the user-facing report/review/write-back path, including
        # the full-corpus window arguments, with a fresh knowledge store.
        index.close()
        chat_knowledge = root / "chat-knowledge.sqlite"
        CRMSKnowledgeBase().save(chat_knowledge)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(chat_knowledge),
            "--index", str(root / "research.sqlite"), "--index-read-only",
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        chat = subprocess.run(
            command,
            input=("/suggest-corpus-alignments 0|10\n"
                   f"/accept-corpus-alignment {proposal['proposal_id']}|0|10\n"
                   + heldout["question"] + "\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60,
            env=os.environ.copy(), check=False)
        require(chat.returncode == 0,
                f"chat alignment flow failed: {chat.stderr}\n{chat.stdout}")
        require("evidence=structured_field_prose" in chat.stdout
                and "Accepted 'capital city of' as wording for 'capital of'" in chat.stdout
                and heldout["answer"] in chat.stdout,
                f"chat did not expose and apply the reviewed rule:\n{chat.stdout}")

        changed_index = CRMSSQLiteResearchIndex(root / "changed.sqlite")
        populate(changed_index, count=2)
        try:
            knowledge.accept_corpus_predicate_alignment(
                proposal["proposal_id"], changed_index, **options)
        except ValueError as error:
            require("stale or unsupported" in str(error),
                    f"unexpected stale proposal error: {error}")
        else:
            raise SystemExit("stale structured proposal was accepted")
        finally:
            changed_index.close()

        coordinated_index = CRMSSQLiteResearchIndex(root / "coordinated.sqlite")
        populate(coordinated_index, count=3,
                 predicate="capital and largest city of")
        try:
            coordinated = CRMSKnowledgeBase().propose_corpus_predicate_alignments(
                coordinated_index, **options)
            require(not any(item.get("evidence_kind")
                            == "structured_field_prose"
                            for item in coordinated),
                    "coordinated capital wording was licensed as a simple alias")
        finally:
            coordinated_index.close()

    print("PASS: structured capital fields proposed a repeated prose variant")
    print("PASS: no facts or language rules changed before explicit acceptance")
    print("PASS: six training pages licensed two held-out question forms")
    print("PASS: held-out answer retained source evidence and survived SQLite reload")
    print("PASS: stale proposals were rejected")
    print("PASS: coordinated capital wording was not simplified")
    print("PASS: chat report and explicit acceptance use indexed corpus windows")


if __name__ == "__main__":
    main()
