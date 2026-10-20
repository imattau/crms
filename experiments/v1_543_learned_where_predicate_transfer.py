"""Transfer a reviewed, source-discovered phrase into a where answer.

Run with: python3 experiments/v1_543_learned_where_predicate_transfer.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (  # noqa: E402
    _explicit_subject_locative_evidence,
    _natural_where_action_lookup,
)
from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSResearchIndex  # noqa: E402


TRAINING = (
    ("a", "Indigo River", "Ochre City"),
    ("b", "Mica Stream", "Silver City"),
)
HELDOUT_SENTENCE = "The Serein River 0133 flows through Nacre City 0133."
QUESTION = "Where does the Serein River 0133 run?"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def chat_options(root: Path) -> list[str]:
    options: list[str] = []
    for name in ("math", "rules", "dialogue-state", "rule-session",
                 "candidate-session", "math-session", "translations",
                 "translation-session"):
        options.extend(("--" + name, str(root / f"{name}.json")))
    return options


def add_document(index: CRMSResearchIndex, document_id: str,
                 sentence: str) -> None:
    index.add_document(document_id, document_id, sentence,
                       f"{document_id}.txt")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-learned-where-",
                                     dir="/tmp") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        knowledge = CRMSKnowledgeBase()
        for position, (suffix, subject, obj) in enumerate(TRAINING):
            canonical = f"{subject} flows through {obj}."
            alternate = f"{subject} runs through {obj}."
            canonical_id = f"flow-canonical-{suffix}"
            alternate_id = f"run-alternate-{suffix}"
            add_document(index, canonical_id, canonical)
            canonical_hit = next(
                hit for hit in index.search(canonical, limit=10)
                if hit.document_id == canonical_id)
            knowledge.add_fact_from_hit(
                subject, "flow through", obj, index, canonical_hit)
            add_document(index, alternate_id, alternate)

            if position == 0:
                single_support = knowledge.propose_predicate_form_alignments(index)
                require(not any(
                    item["relation"] == "flow through"
                    and item["predicate_phrase"] == "runs through"
                    for item in single_support),
                    "one independent pair prematurely proposed an alignment")
            else:
                proposals = knowledge.propose_predicate_form_alignments(index)
                proposal = next((
                    item for item in proposals
                    if item["relation"] == "flow through"
                    and item["predicate_phrase"] == "runs through"), None)
                require(proposal is not None
                        and proposal["distinct_subjects"] == 2
                        and proposal["distinct_objects"] == 2
                        and proposal["independent_documents"] == 2
                        and proposal["review_required"],
                        f"varied source pairs did not propose the phrase: {proposals!r}")
                # Discovery is inert; the explicit review step promotes the
                # relation alignment and preserves the original citations.
                before_review = knowledge.research(QUESTION, index)
                require(not any(
                    item.get("kind") == "licensed_predicate"
                    and item.get("text") == "runs through"
                    for item in before_review.query_expansions),
                    "a report-only proposal expanded a question before review")
                accepted = knowledge.accept_predicate_form_alignment(
                    proposal["proposal_id"], index)
                require(accepted["relation"] == "flow through"
                        and accepted["predicate_phrase"] == "runs through"
                        and len(accepted["support"]) == 2,
                        f"review did not accept the source-backed alignment: {accepted!r}")

        parsed = _natural_where_action_lookup(QUESTION)
        require(parsed == ("Serein River 0133", "run"),
                f"where-action parse changed: {parsed!r}")
        probe = knowledge.research(QUESTION, index)
        licensed_families: dict[str, set[str]] = {}
        for item in probe.query_expansions:
            if item.get("kind") == "licensed_predicate":
                licensed_families.setdefault(
                    str(item["evidence"]), set()).add(str(item["text"]))
        require(licensed_families.get("flow through") == {
                    "flow through", "runs through"},
                f"query did not recover the reviewed phrase family: "
                f"{licensed_families!r}")

        index.add_document("heldout-serein", "Held-out river source",
                           HELDOUT_SENTENCE, "heldout-serein.txt")
        heldout = _explicit_subject_locative_evidence(
            index, parsed[0], parsed[1], licensed_families)
        require(heldout is not None and not heldout.get("ambiguous")
                and heldout["text"] == HELDOUT_SENTENCE
                and heldout["aligned_relation"] == "flow through"
                and index.resolve_citation(heldout["citation"])
                    == HELDOUT_SENTENCE,
                f"reviewed relation did not transfer to held-out source: {heldout!r}")

        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        knowledge.save(knowledge_path)
        index.save(index_path)
        command = [sys.executable, str(PROJECT / "crms_chat.py"),
                   "--knowledge", str(knowledge_path), "--index", str(index_path),
                   *chat_options(root)]
        run = subprocess.run(
            command,
            input=(QUESTION + "\nWhere does the Serein River 0133 float?\n"
                   "/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=120, check=False)
        output = run.stdout + run.stderr
        require(run.returncode == 0 and "Traceback" not in output,
                f"fresh CLI failed: {output}")
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in run.stdout.splitlines() if "CRMS>" in line]
        require(len(replies) == 2
                and HELDOUT_SENTENCE in replies[0]
                and "[Source: Held-out river source; quoted evidence, not an accepted fact]"
                    in replies[0]
                and "reviewed wording alignment: 'run' to 'flow through'"
                    in replies[0]
                and "Indigo River runs through Ochre City." in replies[0]
                and "Mica Stream runs through Silver City." in replies[0]
                and "[Source: run-alternate-a]" in replies[0]
                and "[Source: run-alternate-b]" in replies[0],
                f"fresh chat omitted answer or learning lineage: {replies!r}")
        require("flows through" not in replies[1]
                and "quoted evidence, not an accepted fact" not in replies[1]
                and "won't guess" in replies[1].casefold(),
                f"unrelated predicate produced an answer: {replies[1]!r}")

        unsupported = _explicit_subject_locative_evidence(
            index, parsed[0], "float", licensed_families)
        require(unsupported is None,
                f"an unrelated verb was licensed by the learned phrase: {unsupported!r}")

    print("one independent pair does not propose; two varied pairs propose the relation: PASS")
    print("reviewed phrase transfers to a new entity and cited source sentence: PASS")
    print("fresh chat exposes direct and exact alignment citations: PASS")
    print("unrelated predicate remains unsupported in helper and chat: PASS")


if __name__ == "__main__":
    main()
