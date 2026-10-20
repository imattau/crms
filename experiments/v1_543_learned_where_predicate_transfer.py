"""Transfer a reviewed relation phrase into a source-grounded where answer.

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
    ("run-phrase-a", "The Indigo River runs through Ochre City.",
     "Indigo River", "Ochre City"),
    ("run-phrase-b", "The Mica Stream runs through Silver City.",
     "Mica Stream", "Silver City"),
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


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-learned-where-",
                                     dir="/tmp") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        knowledge = CRMSKnowledgeBase()
        for document_id, sentence, subject, obj in TRAINING:
            index.add_document(document_id, document_id, sentence,
                               f"{document_id}.txt")
            hit = next(hit for hit in index.search(sentence, limit=10)
                       if hit.document_id == document_id)
            knowledge.add_fact_from_hit(
                subject, "flow through", obj, index, hit)
            licensed = knowledge.teach_fact_pattern_from_hit(
                sentence, subject=subject, relation="flow through", obj=obj,
                predicate_phrase="runs", research_index=index, hit=hit)
            if document_id == TRAINING[0][0]:
                require(not licensed,
                        "one example prematurely licensed a relation phrase")
                one_example = knowledge.research(QUESTION, index)
                require(not any(
                    item.get("kind") == "licensed_predicate"
                    and item.get("text") == "runs"
                    for item in one_example.query_expansions),
                    "one source example prematurely expanded the query")
            else:
                require(licensed,
                        "diverse source-backed examples did not license the phrase")

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
                    "flow through", "runs"},
                f"query did not recover the reviewed relation family: "
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
            text=True,
            capture_output=True, cwd=root, timeout=120, check=False)
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
                and TRAINING[0][1] in replies[0]
                and TRAINING[1][1] in replies[0]
                and "[Source: run-phrase-a]" in replies[0]
                and "[Source: run-phrase-b]" in replies[0],
                f"fresh chat omitted answer or learning lineage: {replies!r}")
        require("flows through" not in replies[1]
                and "quoted evidence, not an accepted fact" not in replies[1]
                and "won't guess" in replies[1].casefold(),
                f"unrelated predicate produced an answer: {replies[1]!r}")

        unsupported = _explicit_subject_locative_evidence(
            index, parsed[0], "float", licensed_families)
        require(unsupported is None,
                f"an unrelated verb was licensed by the learned phrase: {unsupported!r}")

    print("two source-backed examples license run → flow through; one does not: PASS")
    print("reviewed relation transfers to a new entity and cited source sentence: PASS")
    print("fresh chat exposes both answer source and alignment sources: PASS")
    print("unrelated predicate remains unsupported in helper and chat: PASS")


if __name__ == "__main__":
    main()
