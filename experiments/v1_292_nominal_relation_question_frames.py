"""Learn who/what question forms from reviewed nominal source relations."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_chat import _natural_who_evidence
from crms_research import CRMSSQLiteResearchIndex


def review_source_fact(knowledge, index, document_id, title, sentence):
    if not index.contains_document(document_id):
        index.add_document(document_id, title, sentence,
                           f"fixture://{document_id}")
    hit = next(hit for hit in index.search(sentence, limit=8)
               if hit.document_id == document_id)
    candidates = knowledge._discover_surface_relation_candidates(
        sentence, source=index.citation(hit), research_index=index)
    assert len(candidates) == 1, candidates
    candidate = candidates[0]
    assert candidate.language_evidence[0]["review_required"] is True
    return knowledge.accept_fact_candidate(candidate, index)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-292-") as folder:
        root = Path(folder)
        index = CRMSSQLiteResearchIndex(root / "research.sqlite")
        knowledge = CRMSKnowledgeBase()
        misleading_list = (
            "Scientists who have conducted a search for real séances and believed "
            "that contact with the dead is a reality include the evolutionary "
            "biologist Alfred Russel Wallace, the inventor of telephone "
            "Alexander Graham Bell, and the inventor of television technology "
            "John Logie Baird.")
        assert not knowledge._discover_surface_relation_candidates(
            misleading_list, source="fixture://ambiguous-list"), (
                "list appositives must not attribute inventor relations to the "
                "preceding person")
        designer_candidate = knowledge._discover_surface_relation_candidates(
            "Max Miedinger, Font Designer of Helvetica.",
            source="fixture://font-designer")
        assert (len(designer_candidate) == 1
                and designer_candidate[0].subject == "Max Miedinger"
                and designer_candidate[0].relation == "font designer of"
                and designer_candidate[0].object == "Helvetica"), designer_candidate
        derived_frames = knowledge._question_frame_variants(
            ("font", "designer", "of"),
            ("who", "is", "the", "font", "designer", "of"), (),
            {("font", "designer", "of")})
        assert (("who", "designed"), ()) in derived_frames, derived_frames

        first = "His second wife was Mary Shelley, the author of Frankenstein."
        second = "The author of Pride was Jane Austen."
        index.add_document("frankenstein", "Frankenstein", first,
                           "fixture://frankenstein")
        index.add_document("pride", "Pride", second, "fixture://pride")
        assert _natural_who_evidence(
            index, "Who authored Frankenstein?") is not None
        assert _natural_who_evidence(
            index, "Who designed Frankenstein?") is None

        unreviewed_state = root / "unreviewed"
        unreviewed_state.mkdir()
        unreviewed_knowledge = CRMSKnowledgeBase()
        unreviewed_path = unreviewed_state / "knowledge.json"
        unreviewed_knowledge.save(unreviewed_path)
        unreviewed_command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(root / "research.sqlite"),
            "--knowledge", str(unreviewed_path),
            "--dialogue-state", str(unreviewed_state / "dialogue.json"),
            "--candidate-session", str(unreviewed_state / "candidates.json"),
            "--rule-session", str(unreviewed_state / "rules.json"),
            "--math", str(unreviewed_state / "math.json"),
            "--math-session", str(unreviewed_state / "math-session.json"),
            "--translations", str(unreviewed_state / "translations.json"),
            "--translation-session",
            str(unreviewed_state / "translation-session.json"),
        ]
        source_chat = subprocess.run(
            unreviewed_command,
            input=("Who is the author of Frankenstein?\n"
                   "Who authored Frankenstein?\n"
                   "/pending-candidates\n/quit\n"),
            text=True, capture_output=True, timeout=30, check=False)
        assert source_chat.returncode == 0, source_chat.stderr + source_chat.stdout
        assert "Mary Shelley is the author of Frankenstein." in source_chat.stdout
        assert source_chat.stdout.count(
            "Mary Shelley is the author of Frankenstein.") == 2
        assert "quoted evidence, not an accepted fact" in source_chat.stdout
        assert "source claim available for review" in source_chat.stdout
        assert "Mary Shelley — author of → Frankenstein" in source_chat.stdout
        persisted_unreviewed = CRMSKnowledgeBase.load(unreviewed_path)
        assert not persisted_unreviewed.facts()
        persisted_unreviewed.close()

        review_source_fact(knowledge, index, "frankenstein", "Frankenstein", first)
        assert knowledge.ask("Who is the author of Frankenstein?").status == "unknown"
        review_source_fact(knowledge, index, "pride", "Pride", second)

        author_answer = knowledge.ask("Who is the author of Frankenstein?")
        assert author_answer.status == "answered"
        assert author_answer.answer == "Mary Shelley"
        assert knowledge.ask("Who is the author of Pride?").answer == "Jane Austen"
        assert knowledge.ask("What is the author of Frankenstein?").status != "answered"

        review_source_fact(
            knowledge, index, "france", "France", "The capital of France is Paris.")
        assert knowledge.ask("What is the capital of France?").status == "unknown"
        assert knowledge.ask("What are the capitals of France?").status == "unknown"
        review_source_fact(
            knowledge, index, "japan", "Japan", "The capital of Japan is Tokyo.")
        capital_answer = knowledge.ask("What is the capital of France?")
        assert capital_answer.status == "answered"
        assert capital_answer.answer == "Paris"
        plural_capital = knowledge.ask("What are the capitals of France?")
        assert plural_capital.status == "answered", plural_capital
        assert plural_capital.answer == "Paris", plural_capital

        review_source_fact(
            knowledge, index, "juice", "The Juice",
            "Camp Lazlo, creator of The Juice.")
        assert knowledge.ask(
            "Who are the creators of The Juice?").status == "unknown"
        review_source_fact(
            knowledge, index, "precrime", "PreCrime",
            "Iris Hineman, creator of PreCrime.")
        creator_answer = knowledge.ask("Who created PreCrime?")
        assert creator_answer.status == "answered", creator_answer
        assert creator_answer.answer == "Iris Hineman", creator_answer
        plural_creator = knowledge.ask("Who are the creators of PreCrime?")
        assert plural_creator.status == "answered", plural_creator
        assert plural_creator.answer == "Iris Hineman", plural_creator
        assert knowledge.ask("Who created Frankenstein?").status != "answered"

        review_source_fact(
            knowledge, index, "battery", "Battery",
            "Alessandro Volta, inventor of the battery.")
        assert knowledge.ask("Who invented the battery?").status == "unknown"
        review_source_fact(
            knowledge, index, "steam-engine", "Steam engine",
            "Thomas Newcomen, inventor of the steam engine.")
        review_source_fact(
            knowledge, index, "minecraft", "Minecraft",
            "Jens Bergensten, designer of Minecraft.")
        review_source_fact(
            knowledge, index, "stage-sets", "Stage sets",
            "Octave Landuyt, designer of stage sets.")
        invented = knowledge.ask("Who invented the battery?")
        assert invented.status == "answered", invented
        assert invented.answer == "Alessandro Volta", invented
        designed = knowledge.ask("Who designed Minecraft?")
        assert designed.status == "answered", designed
        assert designed.answer == "Jens Bergensten", designed
        assert knowledge.ask("Who authed Pride?").status != "answered"

        page_subject = review_source_fact(
            knowledge, index, "jens-page", "Jens Bergensten",
            "He is the lead designer of Minecraft.")
        assert (page_subject.subject, page_subject.relation,
                page_subject.object) == (
                    "Jens Bergensten", "lead designer of", "Minecraft")
        assert not knowledge._discover_surface_relation_candidates(
            "He is the lead designer of Minecraft.",
            source="fixture://no-page-title"), (
                "a sentence-initial pronoun must not become an entity without "
                "an exact source page title")
        accepted_page_subject = next(
            fact for fact in knowledge.facts()
            if fact.relation == "lead designer of")
        assert accepted_page_subject.sources

        state = root / "state"
        state.mkdir()
        knowledge_path = state / "knowledge.json"
        knowledge.save(knowledge_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(root / "research.sqlite"),
            "--knowledge", str(knowledge_path),
            "--dialogue-state", str(state / "dialogue.json"),
            "--candidate-session", str(state / "candidates.json"),
            "--rule-session", str(state / "rules.json"),
            "--math", str(state / "math.json"),
            "--math-session", str(state / "math-session.json"),
            "--translations", str(state / "translations.json"),
            "--translation-session", str(state / "translation-session.json"),
        ]
        chat = subprocess.run(
            command,
            input=("Who is the author of Frankenstein?\n"
                   "What is the capital of France?\n/quit\n"),
            text=True, capture_output=True, timeout=30, check=False)
        assert chat.returncode == 0, chat.stderr + chat.stdout
        assert "Mary Shelley, the author of Frankenstein" in chat.stdout, chat.stdout
        assert "The capital of France is Paris." in chat.stdout, chat.stdout
        print("PASS: appositive and copular nominal relations remain review-gated")
        print("PASS: varied accepted agent nouns license Who; capital relations license What")
        print("PASS: reviewed creator-of relations license the guarded past-tense created frame")
        print("PASS: reviewed inventor/designer frames license regular invented/designed questions")
        print("PASS: licensed nominal frames support regular plural question agreement")
        print("PASS: chat answers from the cited nominal source facts")
        index.close()


if __name__ == "__main__":
    main()
