"""Check learned conversational requests for source-backed entity digests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def add_fact(index: CRMSResearchIndex, kb: CRMSKnowledgeBase,
             document_id: str, sentence: str, subject: str,
             obj: str) -> None:
    index.add_document(document_id, document_id, sentence,
                       f"sources/{document_id}.txt")
    hit = index.search(sentence, limit=1)[0]
    kb.add_fact_from_hit(subject, "designed", obj, index, hit)


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        index = CRMSResearchIndex()
        kb = CRMSKnowledgeBase()
        rows = [
            ("ada", "Ada Lovelace designed the Analytical Engine.",
             "Ada Lovelace", "the Analytical Engine"),
            ("grace", "Grace Hopper designed the Compiler.",
             "Grace Hopper", "the Compiler"),
            ("katherine", "Katherine Johnson designed the trajectory table.",
             "Katherine Johnson", "the trajectory table"),
        ]
        hits = {}
        for document_id, sentence, subject, obj in rows:
            add_fact(index, kb, document_id, sentence, subject, obj)
            hits[document_id] = index.search(sentence, limit=1)[0]

        for document_id, sentence, subject, obj in rows[:2]:
            licensed = kb.teach_fact_pattern_from_hit(
                hits[document_id].snippet, subject=subject,
                relation="designed", obj=obj,
                research_index=index, hit=hits[document_id])
        if not licensed:
            raise SystemExit("source-grounded sentence frame was not licensed")

        if kb.teach_about_frame("Tell me about Ada Lovelace", entity="Ada Lovelace"):
            raise SystemExit("one about-request example licensed a frame")
        if kb.resolve_about_request("Tell me about Ada Lovelace") != (None, False):
            raise SystemExit("an unsupported about-request frame resolved early")
        if not kb.teach_about_frame("Tell me about Grace Hopper", entity="Grace Hopper"):
            raise SystemExit("two distinct entities did not license the about frame")

        subject, conflict = kb.resolve_about_request("Tell me about Katherine Johnson")
        if subject != "Katherine Johnson" or conflict:
            raise SystemExit(f"about frame did not bind a held-out entity: {subject}, {conflict}")
        dialogue = CRMSDialogue(kb)
        turn = dialogue.turn("Tell me about Katherine Johnson", research_index=index)
        if (turn.status != "written" or turn.writing is None
                or "Katherine Johnson designed the trajectory table." not in turn.text
                or "katherine#sha256=" not in turn.text):
            raise SystemExit(f"about request did not write a sourced digest: {turn}")
        pronoun = dialogue.turn("Tell me about her", research_index=index)
        if pronoun.status != "written" or pronoun.resolved_question != "Tell me about Katherine Johnson":
            raise SystemExit(f"about-request result did not support a pronoun follow-up: {pronoun}")
        unknown = dialogue.turn("Tell me about Unstored Person")
        if unknown.status != "unknown":
            raise SystemExit(f"about frame invented facts for an unknown entity: {unknown}")
        stale = dialogue.turn("Tell me about her")
        if stale.status != "unknown" or "pronoun refers to" not in stale.text:
            raise SystemExit("unknown about-request left a stale pronoun referent")

        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        kb.save(knowledge_path)
        index.save(index_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        if restored.resolve_about_request("Tell me about Ada Lovelace") != (
                "Ada Lovelace", False):
            raise SystemExit("about-request frame did not survive persistence")

        chat = [sys.executable,
                str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
                "--knowledge", str(knowledge_path), "--index", str(index_path),
                "--rules", str(temp / "rules.json"),
                "--dialogue-state", str(temp / "dialogue.json"),
                "--rule-session", str(temp / "rule-session.json")]
        output = subprocess.run(
            chat,
            input=("/teach-about Tell me about Ada Lovelace|Ada Lovelace\n"
                   "/teach-about Tell me about Grace Hopper|Grace Hopper\n"
                   "Tell me about Katherine Johnson\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20).stdout
        if ("About-request frame licensed." not in output
                or "Katherine Johnson designed the trajectory table." not in output
                or "katherine#sha256=" not in output):
            raise SystemExit(f"terminal about-request flow failed: {output}")

        natural_knowledge_path = temp / "natural-knowledge.json"
        natural_knowledge = CRMSKnowledgeBase.load(knowledge_path)
        natural_knowledge._about_question_examples.clear()
        natural_knowledge.save(natural_knowledge_path)
        natural_chat = list(chat)
        natural_chat[natural_chat.index("--knowledge") + 1] = str(natural_knowledge_path)
        natural_chat[natural_chat.index("--dialogue-state") + 1] = str(
            temp / "natural-dialogue.json")
        invalid_about_batch = (
            'Teach an about-request frame from examples: '
            '"Tell me about Ada Lovelace" => "Ada Lovelace"; '
            '"Describe Grace Hopper" => "Grace Hopper"')
        valid_about_batch = (
            'Teach an about-request frame from examples: '
            '"Tell me about Ada Lovelace" => "Ada Lovelace"; '
            '"Tell me about Grace Hopper" => "Grace Hopper"; '
            '"Tell me about Katherine Johnson" => "Katherine Johnson"')
        natural_output = subprocess.run(
            natural_chat,
            input=(invalid_about_batch + "\n" + valid_about_batch + "\n"
                   'Tell me about Katherine Johnson\n/quit\n'),
            text=True, capture_output=True, check=True, timeout=20).stdout
        if ("examples must use distinct entities in one shared request frame"
                not in natural_output
                or "About-request frame licensed from 3 stored entities." not in natural_output
                or "Katherine Johnson designed the trajectory table." not in natural_output
                or "katherine#sha256=" not in natural_output):
            raise SystemExit(f"conversational about-frame teaching failed: {natural_output}")
        resumed = subprocess.run(
            chat, input="Tell me about her\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20).stdout
        if "Katherine Johnson designed the trajectory table." not in resumed:
            raise SystemExit(f"about frame or referent did not persist: {resumed}")

    print("learned about-request diagnostic: PASS")
    print("two-example API gate, 3-example natural frame, held-out entity, cited writing, "
          "pronouns, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
