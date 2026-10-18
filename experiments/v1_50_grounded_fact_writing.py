"""Check source-backed multi-fact writing and contradiction handling."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def add_grounded_frame(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                       document_id: str, sentence: str, subject: str,
                       relation: str, obj: str, year: str) -> None:
    index.add_document(document_id, document_id, sentence,
                       f"sources/{document_id}.txt")
    hit = index.search(sentence, limit=1)[0]
    kb.add_fact_from_hit(subject, relation, obj, index, hit)
    kb.teach_fact_pattern_from_hit(
        hit.snippet, subject=subject, relation=relation, obj=obj,
        research_index=index, hit=hit)


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        index = CRMSResearchIndex()
        kb = CRMSKnowledgeBase()
        rows = [
            ("a-design", "Ada Lovelace designed the Analytical Engine.",
             "Ada Lovelace", "designed", "the Analytical Engine", "1843"),
            ("g-design", "Grace Hopper designed the Compiler.",
             "Grace Hopper", "designed", "the Compiler", "1945"),
            ("a-publish", "Ada Lovelace published Notes on the Engine.",
             "Ada Lovelace", "published", "Notes on the Engine", "1843"),
            ("g-publish", "Grace Hopper published the Compiler Manual.",
             "Grace Hopper", "published", "the Compiler Manual", "1945"),
        ]
        for row in rows:
            add_grounded_frame(kb, index, *row)
        for request in (
                "Write about Ada Lovelace",
                "Could you please write a short sourced summary about Ada Lovelace?",
                "Please compose a digest about Ada Lovelace."):
            if kb.resolve_about_request(request) != ("Ada Lovelace", False):
                raise SystemExit(f"natural writing request was not resolved: {request}")
        if kb.resolve_about_request("Summarize Ada Lovelace") != (None, False):
            raise SystemExit("research summarization was misrouted to fact writing")

        full = kb.write_about("Ada Lovelace")
        if full.status != "written" or len(full.statements) != 2:
            raise SystemExit(f"licensed fact digest was incomplete: {full}")
        combined = (
            "Ada Lovelace designed the Analytical Engine and published "
            "Notes on the Engine.")
        if combined not in full.text:
            raise SystemExit(f"shared-subject writing failed: {full.text}")
        for statement in full.statements:
            fact_sources = statement["fact"]["sources"]
            if not fact_sources or not any(source in full.text for source in fact_sources):
                raise SystemExit("a written sentence lost its source labels")

        for fact in list(kb.facts()):
            if fact.subject == "Ada Lovelace":
                kb.add_fact(fact.subject, fact.relation, fact.object,
                            fact.sources[0], qualifiers={"year": "1843"})
        contextual = kb.write_about("Ada Lovelace", qualifiers={"year": "1843"})
        if contextual.status != "written" or any(
                item["fact"]["qualifiers"] != (("year", "1843"),)
                for item in contextual.statements):
            raise SystemExit(f"qualifier filter did not constrain writing: {contextual}")
        if "context: year=1843" not in contextual.text:
            raise SystemExit("written fact omitted its qualifier context")

        kb.add_fact("Ada Lovelace", "won", "a prize", "unframed-source")
        partial_digest = kb.write_about("Ada Lovelace")
        if partial_digest.status != "partial" or len(partial_digest.omitted) != 1:
            raise SystemExit(f"unwritable stored fact was hidden: {partial_digest}")
        if "unframed-source" not in partial_digest.text:
            raise SystemExit("omitted fact lost its provenance")

        kb.add_negative_fact(
            "Ada Lovelace", "designed", "the Analytical Engine",
            "contradictory-source", qualifiers={"year": "1843"})
        conflict = kb.write_about(
            "Ada Lovelace", qualifiers={"year": "1843"})
        if conflict.status != "partial" or len(conflict.conflicts) != 1:
            raise SystemExit(f"conflicting fact was not reported: {conflict}")
        if any("designed the Analytical Engine" in line
               for line in conflict.text.splitlines()):
            raise SystemExit("writer asserted a proposition with conflicting polarity")
        if "contradictory-source" not in conflict.text:
            raise SystemExit("conflict output dropped one side's provenance")

        unknown = kb.write_about("Unstored Person")
        if unknown.status != "unknown":
            raise SystemExit(f"writer invented an unknown entity summary: {unknown}")
        no_frame = CRMSKnowledgeBase()
        no_frame.add_fact("Ada", "owns", "a telescope", "owned-source")
        if no_frame.write_about("Ada").status != "no_licensed_frame":
            raise SystemExit("writer fabricated a sentence without a learned frame")

        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        kb.save(knowledge_path)
        index.save(index_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        if restored.write_about("Ada Lovelace", qualifiers={"year": "1843"}).status != "partial":
            raise SystemExit("writing frames or conflict evidence failed persistence")

        chat_command = [
             sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--rules", str(temp / "rules.json"),
             "--dialogue-state", str(temp / "dialogue.json"),
             "--rule-session", str(temp / "rule-session.json")]
        output = subprocess.run(
            chat_command,
            input="Write a short sourced summary about Ada Lovelace.\nWhy?\n"
                 "What about Grace Hopper?\n"
                 "/write-about Ada Lovelace|year=1843\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20).stdout
        if ("About Ada Lovelace:" not in output
                or output.count("About Ada Lovelace:") < 2
                or "About Grace Hopper:" not in output
                or "published the Compiler Manual" not in output
                or "designed the Analytical Engine" not in output
                or "published Notes on the Engine" not in output
                or "a-publish#sha256=" not in output
                or "contradictory-source" not in output):
            raise SystemExit(f"terminal grounded writing failed: {output}")
        resumed = subprocess.run(
            chat_command, input="Why?\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20).stdout
        if ("About Grace Hopper:" not in resumed
                or "published the Compiler Manual" not in resumed
                or "g-publish#sha256=" not in resumed):
            raise SystemExit(f"writing follow-up context did not resume: {resumed}")

    print("grounded fact-writing diagnostic: PASS")
    print("multi-fact composition, natural requests, citations, qualifiers, "
          "conflict abstention, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
