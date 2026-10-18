"""Discover and review alternate predicates from corpus-only shared pairs."""
from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    examples = (
        ("canon-python", "Guido van Rossum created Python.", "created"),
        ("canon-linux", "Linus Torvalds created Linux.", "created"),
        ("alt-python", "Guido van Rossum developed Python.", "developed"),
        ("alt-linux", "Linus Torvalds developed Linux.", "developed"),
        # One shared pair alone must never license the alignment.
        ("single-ada", "Ada Lovelace invented the Analytical Engine.", "invented"),
    )
    for document_id, sentence, _phrase in examples:
        index.add_document(document_id, "Computing history", sentence,
                           f"{document_id}.txt")
    # Independent source evidence licenses both past-tense normalization classes.
    for document_id, sentence in (
            ("base-create-a", "Engineers can create reliable tools."),
            ("base-create-b", "Researchers need to create useful systems."),
            ("base-develop-a", "Teams can develop reliable tools."),
            ("base-develop-b", "Researchers need to develop useful systems.")):
        index.add_document(document_id, "Computing language", sentence,
                           f"{document_id}.txt")

    kb = CRMSKnowledgeBase()
    sparse = CRMSResearchIndex()
    for document_id, sentence in (
            ("sparse-create-a", "Ada created Engine."),
            ("sparse-create-b", "Bea created Compiler."),
            ("sparse-develop-a", "Ada developed Engine."),
            ("sparse-develop-c", "Cara developed Tool."),
            ("sparse-base-create", "Teams can create reliable systems."),
            ("sparse-base-develop", "Teams can develop useful systems.")):
        sparse.add_document(document_id, "Sparse overlap", sentence,
                            f"{document_id}.txt")
    if kb.propose_corpus_predicate_alignments(sparse):
        raise SystemExit("one shared pair was enough to propose an alignment")
    proposals = kb.propose_corpus_relation_frames(index)
    if (kb.facts()
            or kb.ask("Who created Python?").status == "answered"
            or kb.ask("Who developed Python?").status == "answered"):
        raise SystemExit("report-only frame discovery mutated answerable knowledge")
    alignments = kb.propose_corpus_predicate_alignments(index)
    proposal = next((row for row in alignments
                     if row["predicate_phrase"] == "developed"
                     and row["relation"] == "created"), None)
    if proposal is None:
        raise SystemExit(
            "corpus-only shared subject/object pairs did not yield an alignment: "
            f"{alignments}")
    if (proposal["distinct_pairs"] != 2
            or proposal["canonical_documents"] < 2
            or proposal["alias_documents"] < 2
            or kb.facts()):
        raise SystemExit(f"proposal did not preserve review gates: {proposal}")

    accepted = kb.accept_corpus_predicate_alignment(
        proposal["proposal_id"], index)
    if accepted["predicate_phrase"] != "developed" or kb.facts() == []:
        raise SystemExit("review acceptance did not store cited canonical facts")
    for question, expected in (("Who developed Python?", "Guido van Rossum"),
                               ("Who developed Linux?", "Linus Torvalds")):
        result = kb.ask(question)
        if result.status != "answered" or result.answer != expected:
            raise SystemExit(
                f"accepted corpus-only language rule did not transfer: {question}: {result}")
        if not result.evidence:
            raise SystemExit(f"learned answer lost provenance: {result}")

    # The accepted corpus alignment should also make a new source sentence
    # teachable through its alternate wording. This checks language transfer
    # on a fact pair that did not contribute to the alignment proposal.
    index.add_document(
        "heldout-lua", "Lua language record",
        "Nia Patel developed Lua.", "heldout-lua.txt")
    heldout = kb.research("Who developed Lua?", index)
    if (heldout.status != "needs_review" or len(heldout.candidates or []) != 1
            or (heldout.candidates[0].subject,
                heldout.candidates[0].relation,
                heldout.candidates[0].object) !=
               ("Nia Patel", "created", "Lua")):
        raise SystemExit(
            "accepted corpus wording did not propose the held-out fact for review: "
            f"{heldout}")
    if not heldout.candidates[0].source.startswith("heldout-lua#"):
        raise SystemExit("held-out proposal lost its source provenance")
    kb.accept_fact_candidate(heldout.candidates[0], index)
    heldout_answer = kb.ask("Who developed Lua?")
    if (heldout_answer.status != "answered"
            or heldout_answer.answer != "Nia Patel"
            or not heldout_answer.evidence):
        raise SystemExit(
            "reviewed held-out alternate wording did not become answerable: "
            f"{heldout_answer}")
    for row in accepted["support"]:
        if not kb.remove_fact(row["subject"], accepted["relation"],
                              row["object"], row["alias_source"]):
            raise SystemExit("accepted alternate source could not be retracted")
    if (kb.ask("Who developed Python?").status == "answered"
            or kb.ask("Who created Python?").answer != "Guido van Rossum"):
        raise SystemExit(
            "retracted alternate wording remained licensed or damaged canonical evidence")

    with tempfile.TemporaryDirectory(prefix="crms-corpus-alignment-chat-") as folder:
        root = Path(folder)
        chat_knowledge = CRMSKnowledgeBase()
        chat_knowledge.save(root / "knowledge.json")
        index.save(root / "index.json")
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math", str(root / "math.json"),
            "--math-session", str(root / "math-session.json"),
            "--translations", str(root / "translations.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        run = subprocess.run(
            command,
            input=("/suggest-corpus-alignments\n"
                   "/accept-corpus-alignment 1\n"
                   "Who developed Python?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        if (run.returncode
                or "'created' → 'developed'" not in run.stdout
                or "Accepted 'created' as wording for 'developed'" not in run.stdout
                or "CRMS> Guido van Rossum" not in run.stdout):
            raise SystemExit(
                "corpus predicate alignment chat flow failed:\n"
                + run.stdout + run.stderr)

    # A reviewed relation alignment must also survive the stricter inverse-
    # question evidence filter. This is the natural-language bridge between
    # "What did X investigate?" and a held-out source sentence saying "X
    # studied Y"; the newly extracted fact still waits for review.
    study_index = CRMSResearchIndex()
    for number in range(2):
        subject = f"Researcher {number:04d}"
        obj = f"Quartz Field {number:04d}"
        for prefix, predicate in (("canonical", "investigated"),
                                  ("alternate", "studied")):
            sentence = f"{subject} {predicate} {obj}."
            study_index.add_document(
                f"{prefix}-{number:04d}", "Research record", sentence,
                f"{prefix}-{number:04d}.txt")
    study_learner = CRMSKnowledgeBase()
    study_proposal = next((item for item in
                           study_learner.propose_corpus_predicate_alignments(
                               study_index)
                           if item["relation"] == "investigated"
                           and item["predicate_phrase"] == "studied"), None)
    if study_proposal is None or study_proposal["distinct_pairs"] != 2:
        raise SystemExit(
            "repeated studied/investigated pairs did not produce a reviewable alignment")
    if study_learner.facts():
        raise SystemExit("report-only study alignment wrote facts before review")
    study_learner.accept_corpus_predicate_alignment(
        study_proposal["proposal_id"], study_index)
    heldout_sentence = "Researcher 0002 studied Quartz Field 0002."
    study_index.add_document(
        "heldout-study", "Research record", heldout_sentence,
        "heldout-study.txt")
    heldout_question = "What did Researcher 0002 investigate?"
    heldout_result = study_learner.research(heldout_question, study_index)
    if (heldout_result.status != "needs_review"
            or len(heldout_result.candidates or []) != 1
            or (heldout_result.candidates[0].subject,
                heldout_result.candidates[0].relation,
                heldout_result.candidates[0].object) !=
               ("Researcher 0002", "investigated", "Quartz Field 0002")
            or heldout_result.candidates[0].sentence != heldout_sentence):
        raise SystemExit(
            "licensed question wording did not retrieve the held-out alternate "
            f"predicate for review: {heldout_result}")
    if study_learner.ask(heldout_question).status == "answered":
        raise SystemExit("held-out source fact bypassed explicit review")
    study_learner.accept_fact_candidate(
        heldout_result.candidates[0], study_index)
    study_answer = study_learner.ask(heldout_question)
    if (study_answer.status != "answered"
            or study_answer.answer != "Quartz Field 0002"
            or not study_answer.evidence):
        raise SystemExit(
            f"reviewed alternate-predicate fact did not answer: {study_answer}")

    # Drive the same learning sequence through the interactive chat: report
    # the alignment, accept its cited pairs, add a new source, review its
    # candidate, and then ask the question again.
    chat_study_index = CRMSResearchIndex()
    for number in range(2):
        subject = f"Researcher {number:04d}"
        obj = f"Quartz Field {number:04d}"
        for prefix, predicate in (("canonical", "investigated"),
                                  ("alternate", "studied")):
            sentence = f"{subject} {predicate} {obj}."
            chat_study_index.add_document(
                f"{prefix}-{number:04d}", "Research record", sentence,
                f"{prefix}-{number:04d}.txt")
    with tempfile.TemporaryDirectory(
            prefix="crms-investigated-studied-chat-") as folder:
        root = Path(folder)
        study_knowledge_path = root / "knowledge.json"
        study_index_path = root / "index.json"
        CRMSKnowledgeBase().save(study_knowledge_path)
        chat_study_index.save(study_index_path)
        heldout_path = root / "heldout.txt"
        heldout_path.write_text(
            "Researcher 0002 studied Quartz Field 0002.\n",
            encoding="utf-8")
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(study_knowledge_path),
            "--index", str(study_index_path),
            "--rules", str(root / "chat-rules.json"),
            "--rule-session", str(root / "chat-rule-session.json"),
            "--candidate-session", str(root / "chat-candidates.json"),
            "--math", str(root / "chat-math.json"),
            "--math-session", str(root / "chat-math-session.json"),
            "--translations", str(root / "chat-translations.json"),
            "--translation-session", str(root / "chat-translation-session.json"),
            "--dialogue-state", str(root / "chat-dialogue.json"),
        ]
        chat = subprocess.run(
            command,
            input=("/suggest-corpus-alignments\n"
                   "/accept-corpus-alignment 1\n"
                   f"/source {heldout_path}\n"
                   f"{heldout_question}\n"
                   "accept candidate 1\n"
                   f"{heldout_question}\n/quit\n"),
            text=True, capture_output=True, check=False, cwd=root, timeout=60)
        # The accepted alignment licenses the source predicate for retrieval
        # and canonical fact storage; answer realization must preserve the
        # exact reviewed source wording instead of rewriting it into the
        # canonical relation label.
        expected_sentence = (
            "Researcher 0002 studied Quartz Field 0002. "
            "[Source: heldout.txt; accepted fact]")
        if (chat.returncode
                or "Accepted 'studied' as wording for 'investigated'" not in chat.stdout
                or "supporting claim awaiting review; not yet an accepted fact" not in chat.stdout
                or "Researcher 0002 studied Quartz Field 0002. [Source: heldout.txt; supporting claim awaiting review" not in chat.stdout
                or expected_sentence not in chat.stdout):
            raise SystemExit(
                "natural-language predicate learning chat flow failed:\n"
                + chat.stdout + chat.stderr)

    print("corpus-only predicate alignment diagnostic: PASS")
    print("shared-pair threshold, independent citations, report-only discovery, explicit acceptance, held-out source fact extraction and QA, provenance: PASS")


if __name__ == "__main__":
    main()
