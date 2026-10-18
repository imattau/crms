"""Check natural-language accept/reject for cited research candidates."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def prepare(root: Path, holdouts: tuple[tuple[str, str], ...]):
    index = CRMSResearchIndex()
    training = (
        ("ada", "Ada Lovelace designed the Analytical Engine."),
        ("grace", "Grace Hopper designed the Compiler."),
    )
    for document_id, sentence in (*training, *holdouts):
        index.add_document(document_id, document_id, sentence,
                           f"research/{document_id}.txt")
    index_path = root / "index.json"
    knowledge_path = root / "knowledge.json"
    index.save(index_path)

    knowledge = CRMSKnowledgeBase()
    for document_id, sentence in training:
        hit = index.search(sentence, limit=1)[0]
        subject, obj = (("Ada Lovelace", "the Analytical Engine")
                        if document_id == "ada" else
                        ("Grace Hopper", "the Compiler"))
        knowledge.add_fact_from_hit(subject, "designed", obj, index, hit)
        knowledge.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="designed", obj=obj,
            research_index=index, hit=hit)
        knowledge.teach_question(
            f"Who designed {obj}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject)
    knowledge.save(knowledge_path)
    return index, index_path, knowledge_path


def run_chat(root: Path, index_path: Path, knowledge_path: Path,
             lines: tuple[str, ...], name: str) -> str:
    return subprocess.run(
        [sys.executable, str(PROJECT / "crms_chat.py"),
         "--knowledge", str(knowledge_path), "--index", str(index_path),
         "--dialogue-state", str(root / f"{name}-dialogue.json"),
         "--rules", str(root / f"{name}-rules.json"),
         "--rule-session", str(root / f"{name}-rule-session.json")],
        input="\n".join((*lines, "/quit")) + "\n", text=True,
        capture_output=True, check=True, timeout=20).stdout


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        holdout = ("katherine", "Katherine Johnson designed the trajectory table.")
        index, index_path, knowledge_path = prepare(root, (holdout,))
        accepted = run_chat(
            root, index_path, knowledge_path,
            ("Who designed the trajectory table?", "Accept that candidate.",
             "Who designed the trajectory table?", "/facts"), "accept")
        if ("Review candidate 1 (positive)" not in accepted
                or "Accepted positive fact: Katherine Johnson — designed → the trajectory table." not in accepted
                or "Answer: Katherine Johnson." not in accepted):
            raise SystemExit(f"natural-language candidate acceptance failed:\n{accepted}")
        accepted_kb = CRMSKnowledgeBase.load(knowledge_path)
        if len(accepted_kb.facts()) != 3:
            raise SystemExit("accepted candidate was not stored exactly once")
        holdout_hit = index.search(holdout[1], limit=1)[0]
        citation = index.citation(holdout_hit)
        if citation not in accepted_kb.facts()[-1].sources:
            raise SystemExit("accepted candidate lost its cited source")

        resumed_root = root / "resumed"
        resumed_root.mkdir()
        _index, resumed_index_path, resumed_knowledge_path = prepare(
            resumed_root, (holdout,))
        first_session = run_chat(
            resumed_root, resumed_index_path, resumed_knowledge_path,
            ("Who designed the trajectory table?",), "first-session")
        second_session = run_chat(
            resumed_root, resumed_index_path, resumed_knowledge_path,
            ("Accept candidate 1", "Who designed the trajectory table?"),
            "second-session")
        if ("Review candidate 1 (positive)" not in first_session
                or "Restored 1 pending cited fact candidate" not in second_session
                or "Accepted positive fact: Katherine Johnson — designed → the trajectory table." not in second_session
                or "Answer: Katherine Johnson." not in second_session):
            raise SystemExit("natural candidate decision did not survive restart:\n"
                             + first_session + second_session)
        if len(CRMSKnowledgeBase.load(resumed_knowledge_path).facts()) != 3:
            raise SystemExit("restored candidate acceptance did not persist")

        rejected_root = root / "reject"
        rejected_root.mkdir()
        _index, rejected_index_path, rejected_knowledge_path = prepare(
            rejected_root, (holdout,))
        rejected = run_chat(
            rejected_root, rejected_index_path, rejected_knowledge_path,
            ("Who designed the trajectory table?", "Reject that candidate.",
             "/facts", "/pending-candidates"), "reject")
        if ("Rejected candidate 1; it remains uncommitted: Katherine Johnson" not in rejected
                or "There are no fact candidates waiting for review." not in rejected):
            raise SystemExit(f"natural-language candidate rejection failed:\n{rejected}")
        rejected_kb = CRMSKnowledgeBase.load(rejected_knowledge_path)
        if len(rejected_kb.facts()) != 2:
            raise SystemExit("rejected candidate entered the fact store")

        ambiguous_root = root / "ambiguous"
        ambiguous_root.mkdir()
        holdouts = (
            ("katherine", "Katherine Johnson designed the Device."),
            ("mary", "Mary Jackson designed the Device."),
        )
        _index, ambiguous_index_path, ambiguous_knowledge_path = prepare(
            ambiguous_root, holdouts)
        ambiguous = run_chat(
            ambiguous_root, ambiguous_index_path, ambiguous_knowledge_path,
            ("Who designed the Device?", "Accept the candidate.",
             "Reject candidate 2", "/facts"),
            "ambiguous")
        if ("Several fact candidates are waiting; name a candidate number." not in ambiguous
                or "Rejected candidate 2; it remains uncommitted" not in ambiguous
                or "1 candidate(s) remain in the review queue" not in ambiguous
                or "Say 'accept candidate 1'" not in ambiguous):
            raise SystemExit(f"ambiguous natural decision was guessed:\n{ambiguous}")
        ambiguous_kb = CRMSKnowledgeBase.load(ambiguous_knowledge_path)
        if len(ambiguous_kb.facts()) != 2:
            raise SystemExit("ambiguous natural decision mutated knowledge")
        remaining = run_chat(
            ambiguous_root, ambiguous_index_path, ambiguous_knowledge_path,
            ("Accept candidate 1",), "ambiguous-resumed")
        if ("Restored 1 pending cited fact candidate" not in remaining
                or "Accepted positive fact:" not in remaining):
            raise SystemExit(f"remaining candidate was not reviewable after restart:\n{remaining}")
        if len(CRMSKnowledgeBase.load(ambiguous_knowledge_path).facts()) != 3:
            raise SystemExit("selected remaining candidate did not persist")

        stale_root = root / "stale-source"
        stale_root.mkdir()
        _index, stale_index_path, stale_knowledge_path = prepare(
            stale_root, (holdout,))
        first = run_chat(
            stale_root, stale_index_path, stale_knowledge_path,
            ("Who designed the trajectory table?",), "stale-first")
        if "Review candidate 1 (positive)" not in first:
            raise SystemExit("could not stage a candidate for invalidation test")
        changed_index = CRMSResearchIndex.load(stale_index_path)
        changed_index.add_document(
            "katherine", "katherine", "Katherine Johnson studied astronomy.",
            "research/katherine.txt", replace=True)
        changed_index.save(stale_index_path)
        invalidated = run_chat(
            stale_root, stale_index_path, stale_knowledge_path,
            ("/invalidated-candidates", "/accept 1"), "stale-second")
        if ("Restored 1 invalidated candidate record" not in invalidated
                or "citation refers to a different source revision" not in invalidated
                or "These records are inspect-only" not in invalidated
                or "There are no fact candidates waiting for review." not in invalidated):
            raise SystemExit("invalidated candidate was lost or remained acceptable:\n"
                             + invalidated)
        restored_invalidation = run_chat(
            stale_root, stale_index_path, stale_knowledge_path,
            ("/invalidated-candidates", "/clear-invalidated-candidates",
             "/invalidated-candidates"), "stale-third")
        if "citation refers to a different source revision" not in restored_invalidation:
            raise SystemExit("invalidation reason did not survive another restart:\n"
                             + restored_invalidation)
        if "Invalidated candidate history cleared." not in restored_invalidation:
            raise SystemExit("invalidated history could not be cleared explicitly")
        if "There are no invalidated fact candidates to inspect." not in restored_invalidation:
            raise SystemExit("cleared invalidation history remained visible")
        if len(CRMSKnowledgeBase.load(stale_knowledge_path).facts()) != 2:
            raise SystemExit("invalidated candidate entered the fact store")

    print("natural-language candidate review diagnostic: PASS")
    print("cited acceptance, explicit rejection, ambiguous-choice clarification, "
          "pending-review restoration, inspectable invalidation, and no "
          "unreviewed writes: PASS")


if __name__ == "__main__":
    main()
