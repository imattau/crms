"""Check review-gated synonym-form discovery from repeated fact co-occurrence."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from copy import deepcopy

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    examples = [
        ("Guido van Rossum", "Python", "source-created-python"),
        ("Linus Torvalds", "Linux", "source-created-linux"),
    ]
    for subject, obj, doc_id in examples:
        sentence = f"{subject} created {obj}."
        index.add_document(doc_id, doc_id, sentence, f"{doc_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == doc_id)
        kb.add_fact_from_hit(subject, "create", obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="create", obj=obj,
            predicate_phrase="created", research_index=index, hit=hit)
        kb.teach_question(
            f"Who created {obj}?", relation="create",
            answer_field="subject", bound_entity=obj, answer=subject)

    alternatives = [
        ("Guido van Rossum", "Python", "source-made-python"),
        ("Linus Torvalds", "Linux", "source-made-linux"),
    ]
    for subject, obj, doc_id in alternatives:
        index.add_document(
            doc_id, doc_id, f"{subject} made {obj}.", f"{doc_id}.txt")
        for noise_index in range(15):
            noise_id = f"noise-{doc_id}-{noise_index:02}"
            index.add_document(
                noise_id, f"{subject} {obj}",
                f"Unrelated metadata record {noise_index}.",
                f"{noise_id}.txt")
    index.add_document("heldout-made", "Held out",
                       "Dana made the Satellite.", "heldout-made.txt")

    before_sources = {
        (fact.subject, fact.relation, fact.object): set(fact.sources)
        for fact in kb.facts()
    }
    sparse_index = CRMSResearchIndex()
    sparse_index.add_document(
        "one-made", "Single wording example",
        "Guido van Rossum made Python.", "one-made.txt")
    if any(item["predicate_phrase"] == "made"
           for item in kb.propose_predicate_form_alignments(sparse_index)):
        raise SystemExit(
            "one co-occurrence was enough to propose a predicate alignment")
    short_scan = kb.propose_predicate_form_alignments(
        index, maximum_hits_per_fact=10)
    if any(item["predicate_phrase"] == "made" for item in short_scan):
        raise SystemExit("predicate discovery ignored its requested hit bound")
    proposals = kb.propose_predicate_form_alignments(index)
    proposal = next((item for item in proposals
                     if item["relation"] == "create"
                     and item["predicate_phrase"] == "made"), None)
    if proposal is None:
        raise SystemExit(f"repeated alternate wording was not proposed: {proposals}")

    paged_kb = deepcopy(kb)
    for fact_index in range(101):
        paged_kb.add_fact(f"Earlier {fact_index}", "aaa relation",
                          f"Item {fact_index}", f"noise:fact:{fact_index}")
    first_page = paged_kb.propose_predicate_form_alignments(
        index, maximum_facts=100, maximum_hits_per_fact=100, fact_offset=0)
    later_page = paged_kb.propose_predicate_form_alignments(
        index, maximum_facts=100, maximum_hits_per_fact=100, fact_offset=100)
    if any(item["predicate_phrase"] == "made" for item in first_page):
        raise SystemExit("first bounded page unexpectedly included later facts")
    if not any(item["predicate_phrase"] == "made" for item in later_page):
        raise SystemExit("later fact page failed to reach the create relation")
    later_proposal = next(item for item in later_page
                          if item["predicate_phrase"] == "made")
    paged_acceptance = paged_kb.accept_predicate_form_alignment(
        later_proposal["proposal_id"], index, fact_offset=100)
    if paged_acceptance["predicate_phrase"] != "made":
        raise SystemExit("a paged predicate proposal could not be revalidated")
    if (proposal["distinct_subjects"] < 2
            or proposal["distinct_objects"] < 2
            or proposal["independent_documents"] < 2
            or not proposal["review_required"]):
        raise SystemExit(f"proposal did not satisfy its evidence gates: {proposal}")
    after_proposal = {
        (fact.subject, fact.relation, fact.object): set(fact.sources)
        for fact in kb.facts()
    }
    if before_sources != after_proposal:
        raise SystemExit("report-only predicate discovery mutated fact provenance")
    if kb.ask("Who made Python?").status == "answered":
        raise SystemExit("unreviewed alternate predicate was used for QA")

    with tempfile.TemporaryDirectory(prefix="crms-predicate-cli-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        index.save(index_path)
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        cli = subprocess.run(
            command,
            input=("/suggest-predicate-forms 0|10\n"
                   "/suggest-predicate-forms 0|100\n"
                   "Review alternate predicate forms\n"
                   f"Accept predicate-form proposal {proposal['proposal_id']}\n"
                   "Who made Python?\n"
                   "Who made the Satellite?\n"
                   "Accept candidate 1\n"
                   "Who made the Satellite?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if ("No alternate predicate wording met the varied-fact" not in cli.stdout
                or "'made' → 'create'" not in cli.stdout
                or "These proposals are report-only" not in cli.stdout
                or "Accepted source-backed wording 'made' for relation 'create'"
                not in cli.stdout
                or "Guido van Rossum" not in cli.stdout
                or "1 source claim available for review" not in cli.stdout
                or "Accepted positive fact: Dana — create → the Satellite." not in cli.stdout
                or "Dana made the Satellite." not in cli.stdout):
            raise SystemExit(
                f"interactive review path failed to teach the form: {cli.stdout}")
        restored = CRMSKnowledgeBase.load(knowledge_path)
        heldout_answer = restored.ask("Who made the Satellite?")
        if (heldout_answer.status != "answered"
                or heldout_answer.answer != "Dana"):
            raise SystemExit(
                f"held-out corpus wording did not survive restart: {heldout_answer}")
        heldout_sources = {source.partition("#sha256=")[0]
                           for item in heldout_answer.evidence or []
                           for source in item.get("sources", [])}
        if "heldout-made" not in heldout_sources:
            raise SystemExit("held-out answer lost its accepted source citation")

    accepted = kb.accept_predicate_form_alignment(
        proposal["proposal_id"], index)
    if accepted["predicate_phrase"] != "made":
        raise SystemExit(f"acceptance returned a different alignment: {accepted}")
    answer = kb.ask("Who made Python?")
    if answer.status != "answered" or answer.answer != "Guido van Rossum":
        raise SystemExit(f"accepted corpus alignment did not transfer: {answer}")
    evidence_sources = {source for item in answer.evidence or []
                        for source in item.get("sources", [])}
    if not evidence_sources.intersection(
            row["source"] for row in proposal["support"]):
        raise SystemExit("paraphrase answer omitted its reviewed source support")
    if kb.ask("Who built Python?").status == "answered":
        raise SystemExit("unobserved synonym was inferred from an accepted alignment")

    # Nominal paraphrases need the learned question frame's copula and article
    # when transferred from a verb-shaped question such as "Who created Python?".
    for subject, obj, document_id in (
            ("Guido van Rossum", "Python", "source-nominal-python"),
            ("Linus Torvalds", "Linux", "source-nominal-linux")):
        sentence = f"The creator of {obj} is {subject}."
        index.add_document(document_id, "Nominal predicate wording", sentence,
                           f"{document_id}.txt")
    nominal_proposal = next((item for item in
                             kb.propose_predicate_form_alignments(index)
                             if item["relation"] == "create"
                             and item["predicate_phrase"] == "creator of"), None)
    if nominal_proposal is None:
        raise SystemExit("repeated nominal predicate wording was not proposed")
    kb.accept_predicate_form_alignment(nominal_proposal["proposal_id"], index)
    nominal_answer = kb.ask("Who is the creator of Python?")
    if (nominal_answer.status != "answered"
            or nominal_answer.answer != "Guido van Rossum"):
        raise SystemExit(
            f"accepted nominal wording did not transfer into natural QA: {nominal_answer}")

    print("corpus predicate alignment diagnostic: PASS")
    print("varied co-occurrence, source separation, review gate, paraphrase transfer, held-out fact acceptance, citation provenance, restart, unseen-synonym abstention: PASS")


if __name__ == "__main__":
    main()
