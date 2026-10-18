"""Portable learned-memory bundle smoke and integrity diagnostic."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_chat import _memory_file_state
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_package import (export_model_database, inspect_model_database,
                          install_model_database, model_database_has_research,
                          model_database_research_stats)
from crms_research import CRMSSQLiteResearchIndex
from crms_text import word_matches
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-portable-") as temporary:
        root = Path(temporary)
        tracked_memory = root / "memory.json"
        tracked_memory.write_text('{"fact":"A"}', encoding="utf-8")
        fixed_time = 1_700_000_000_000_000_000
        os.utime(tracked_memory, ns=(fixed_time, fixed_time))
        first_memory_state = _memory_file_state(tracked_memory)
        tracked_memory.write_text('{"fact":"B"}', encoding="utf-8")
        os.utime(tracked_memory, ns=(fixed_time, fixed_time))
        if _memory_file_state(tracked_memory) == first_memory_state:
            raise SystemExit(
                "portable model update tracking missed a same-size, same-mtime change")
        knowledge = CRMSKnowledgeBase()
        knowledge.add_fact("Ada", "founded", "Example Lab",
                           "chat:design-review#turn=18")
        require(not knowledge.teach_question(
            "Who founded Example Lab?", relation="founded",
            answer_field="subject", bound_entity="Example Lab", answer="Ada"),
            "single fact should not license a generalized question frame")
        knowledge.add_fact("Grace", "founded", "Example Hub", "paper:founder-list")
        # Seed a small proof chain so runtime practice can test whether a newly
        # derived, provenance-bearing case returns to the portable DB.
        knowledge.add_fact("A", "part", "M", "source:part")
        knowledge.add_fact("M", "follows", "B", "source:follows")
        knowledge.add_fact("B", "precedes", "C", "source:edge")
        knowledge.add_relation_type("precedes", "transitive", "source:schema")
        knowledge.add_inference_rule("part-follow", "part", "follows", "precedes")
        require(knowledge.teach_question(
            "Who founded Example Hub?", relation="founded",
            answer_field="subject", bound_entity="Example Hub", answer="Grace"),
            "second fact-backed example did not license the question frame")
        require(knowledge.ask("Who founded Example Lab?").answer == "Ada",
                "exact grounded question example did not answer")
        knowledge.save(root / "knowledge.json")
        research = CRMSSQLiteResearchIndex(root / "research.sqlite")
        source_pages = (
            "Rotor systems require balanced blades.",
            "Starlingpoint rotor cooling uses a dual-channel ceramic exchanger.")
        research.add_document(
            "manual:rotor", "Rotor test manual",
            "\n\f\n".join(source_pages), pages=source_pages)
        for number in range(130):
            research.add_document(
                f"fixture:{number:03d}", f"Corpus fixture {number:03d}",
                ("Record " + str(number) + " covers local corpus scaling. "
                 + ("Goldensparrow appears in this retrieval fixture."
                    if number == 129 else "Routine indexed corpus content.")))
        research.add_document(
            "fixture:unicode", "Unicode token fixture",
            "Cafe\u0301 uses Unicode combining marks; O’Neil's index.")
        expected_word_units = sum(
            len(word_matches(document.text)) for document in research.documents())
        research.close()
        rules = CRMSModel(max_search_expansions=20_000, vsa_alpha=0.7,
                          vsa_min_similarity=0.4, vsa_min_margin=0.15)
        rule_examples = [
            (values, list(reversed([value + 1 for value in values])))
            for values in ([1, 4, -2], [5, -3, 8], [0, 6, -7], [9, 2, 1])]
        result = rules.teach(
            "add 1 to each value then reverse the list", rule_examples)
        require(result.status == "learned", f"rule teaching failed: {result}")
        rules.save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        database = export_model_database(
            root / "model.sqlite", knowledge=root / "knowledge.json",
            rules=root / "rules.json", math=root / "math.json",
            translations=root / "translations.json",
            research_index=root / "research.sqlite")
        model_types = {row[0] for row in sqlite3.connect(database).execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        require(model_types == {"model_metadata", "learned_memories",
                                "research_documents"},
                f"model database contains unexpected tables: {model_types}")
        metadata = dict(sqlite3.connect(database).execute(
            "SELECT key, value FROM model_metadata"))
        require(metadata["contains_source_documents"] == "true"
                and metadata["contains_research_index"] == "true"
                and model_database_has_research(database),
                "model database does not declare its embedded source corpus")
        knowledge_payload = sqlite3.connect(database).execute(
            "SELECT payload_json FROM learned_memories WHERE kind='knowledge'").fetchone()[0]
        require("chat:design-review#turn=18" in knowledge_payload,
                "source provenance reference was lost")
        require(set(inspect_model_database(database)) ==
                {"knowledge", "rules", "math", "translations"},
                "model database failed format inspection")
        cli_database = root / "cli-model.sqlite"
        cli_export = subprocess.run(
            [sys.executable, str(PROJECT / "crms_package.py"), "export",
             "--output", str(cli_database), "--knowledge", str(root / "knowledge.json"),
             "--rules", str(root / "rules.json"), "--research-index",
             str(root / "research.sqlite")],
            text=True, capture_output=True, cwd=root, timeout=30)
        cli_inspect = subprocess.run(
            [sys.executable, str(PROJECT / "crms_package.py"), "inspect",
             str(cli_database)],
            text=True, capture_output=True, cwd=root, timeout=30)
        require(cli_export.returncode == 0 and cli_inspect.returncode == 0
                and "research text: 132 documents" in cli_inspect.stdout
                and "CRMS word units (not model-token count)" in cli_inspect.stdout,
                f"portable model CLI failed:\n{cli_export.stdout}\n"
                f"{cli_export.stderr}\n{cli_inspect.stdout}\n{cli_inspect.stderr}")
        corpus_stats = model_database_research_stats(cli_database)
        require(corpus_stats is not None
                and corpus_stats["documents"] == 132
                and corpus_stats["utf8_bytes"] > 0
                and corpus_stats["word_units"] == expected_word_units,
                f"portable source-volume metrics are incomplete: {corpus_stats}")

        memories_only = export_model_database(
            root / "memories-only.sqlite", knowledge=root / "knowledge.json",
            rules=root / "rules.json")
        with sqlite3.connect(memories_only) as db:
            lean_metadata = dict(db.execute(
                "SELECT key, value FROM model_metadata"))
            lean_tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        require(lean_metadata["contains_research_index"] == "false"
                and lean_tables == {"model_metadata", "learned_memories"}
                and not model_database_has_research(memories_only),
                "memories-only portable database format regressed")

        # Runtime search must use the embedded database payload, not its source index.
        (root / "research.sqlite").unlink()
        new_source = root / "runtime-source.txt"
        new_source.write_text(
            "Zirconvale pump uses a six-stage ceramic impeller.\n",
            encoding="utf-8")

        runtime = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--model-db", str(database),
             "--dialogue-state", str(root / "dialogue.json")],
            input=("Who founded Example Lab?\n"
                   'Teach a fact pattern from labeled examples: '
                   '"Ada founded Example Lab." => "Ada" | "founded" | '
                   '"Example Lab"; "Grace founded Example Hub." => "Grace" | '
                   '"founded" | "Example Hub"\n'
                   'Remember that "Iris founded New Lab." as a fact from source '
                   '"chat:turn-42".\n'
                   "Who founded New Lab?\n"
                   "/apply-rule add 1 to each value then reverse the list|3,-1,7\n"
                   "/teach-rule increase each value by 2 before reversing it|"
                   "1,4,-2|0,6,3\n"
                   "/teach-rule increase each value by 2 before reversing it|"
                   "5,-3,8|10,-1,7\n"
                   "/practice-inference A|precedes|C\n"
                   "/summarize Starlingpoint rotor cooling\n"
                   f"/source {new_source}\n"
                   "/summarize Zirconvale six-stage ceramic impeller\n"
                   "/quit\n"), text=True, capture_output=True, cwd=root, timeout=30)
        require(runtime.returncode == 0
                and "Loaded portable learned model:" in runtime.stdout
                and "Ada founded Example Lab." in runtime.stdout
                and "Source: chat:design-review" in runtime.stdout
                and "Stored 2 teacher-labeled positive facts" in runtime.stdout
                and "Stored positive fact: Iris — founded → New Lab "
                "[source: chat:turn-42]." in runtime.stdout
                and "Iris founded New Lab." in runtime.stdout
                and "CRMS> [8, 0, 4]" in runtime.stdout
                and "Verified derivation stored as a separate derived case."
                in runtime.stdout
                and "dual-channel ceramic exchanger" in runtime.stdout
                and "Indexed runtime-source.txt." in runtime.stdout
                and "six-stage ceramic impeller" in runtime.stdout
                and "Updated portable model database with learned memories "
                "and source text."
                in runtime.stdout,
                f"chat did not run directly from model DB:\n"
                f"{runtime.stdout}\n{runtime.stderr}")
        packed_rules = json.loads(sqlite3.connect(database).execute(
            "SELECT payload_json FROM learned_memories WHERE kind='rules'").fetchone()[0])
        require("increase each value by 2 before reversing it"
                in packed_rules["procedures"],
                "newly learned procedure did not return to model database")
        require(packed_rules["max_search_expansions"] == 20_000
                and packed_rules["vsa_alpha"] == 0.7
                and packed_rules["vsa_min_similarity"] == 0.4
                and packed_rules["vsa_min_margin"] == 0.15,
                "repacking changed the model's learned runtime configuration")
        packed_knowledge = json.loads(sqlite3.connect(database).execute(
            "SELECT payload_json FROM learned_memories "
            "WHERE kind='knowledge'").fetchone()[0])
        require(any(fact["subject"] == "Iris"
                    and fact["object"] == "New Lab"
                    and "chat:turn-42" in fact["sources"]
                    for fact in packed_knowledge["facts"]),
                "chat-taught fact did not return to model database")
        packed_derived = packed_knowledge.get("derived_cases", [])
        require(any(case["conclusion"]["subject"] == "A"
                    and case["conclusion"]["relation"] == "precedes"
                    and case["conclusion"]["object"] == "C"
                    and "source:part" in case["lineage"]["sources"]
                    and "part-follow" in case["lineage"]["rule_ids"]
                    for case in packed_derived),
                "verified derived case and its lineage did not return to model DB")
        (root / "runtime-source.txt").unlink()
        restart = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--model-db", str(database),
             "--dialogue-state", str(root / "dialogue.json")],
            input=("Who founded New Lab?\n"
                   "/summarize Zirconvale six-stage ceramic impeller\n"
                   "/quit\n"), text=True,
            capture_output=True, cwd=root, timeout=30)
        require(restart.returncode == 0
                and "Loaded portable learned model:" in restart.stdout
                and "Iris founded New Lab." in restart.stdout
                and "six-stage ceramic impeller" in restart.stdout
                and "Updated portable model database" not in restart.stdout,
                f"updated model database could not be restarted:\n"
                f"{restart.stdout}\n{restart.stderr}")

        installed = install_model_database(database, root / "installed")
        require("research_index" in installed,
                "portable model installation omitted embedded source text")
        restored_research = CRMSSQLiteResearchIndex.load(installed["research_index"])
        source_hit = restored_research.search("Starlingpoint ceramic exchanger", limit=1)
        batch_hit = restored_research.search("Goldensparrow retrieval fixture", limit=1)
        require(len(source_hit) == 1
                and source_hit[0].document_id == "manual:rotor"
                and source_hit[0].page_number == 2
                and "dual-channel ceramic exchanger" in source_hit[0].snippet
                and restored_research.resolve_citation(
                    restored_research.citation(source_hit[0])) == source_hit[0].snippet,
                "embedded source text or citation did not survive installation")
        require(len(batch_hit) == 1
                and batch_hit[0].document_id == "fixture:129"
                and "Goldensparrow" in batch_hit[0].snippet,
                "batched portable corpus installation omitted a later document")
        restored_research.close()
        restored = CRMSKnowledgeBase.load(installed["knowledge"])
        require(any("chat:design-review#turn=18" in fact.sources
                        for fact in restored.facts())
                and any(fact.subject == "Iris" and fact.object == "New Lab"
                        and "chat:turn-42" in fact.sources
                        for fact in restored.facts()),
                "knowledge or provenance did not survive bundle round-trip")
        answer = restored.ask("Who founded Example Lab?")
        require(answer.status == "answered" and answer.answer == "Ada"
                and answer.evidence
                and "chat:design-review#turn=18" in answer.evidence[0]["sources"],
                "portable knowledge did not answer with its retained provenance")
        generalized = restored.ask("Who founded New Lab?")
        require(generalized.status == "answered" and generalized.answer == "Iris",
                "retained question frame did not generalize to the new fact")
        restored_rules = CRMSModel(
            max_search_expansions=20_000, vsa_alpha=0.7,
            vsa_min_similarity=0.4, vsa_min_margin=0.15)
        restored_rules.load(installed["rules"])
        prediction = restored_rules.predict(
            "add 1 to each value then reverse the list", [3, -1, 7])
        require(prediction.status == "ok" and prediction.output == [8, 0, 4],
                "learned rule did not run from installed memory")
        new_prediction = restored_rules.predict(
            "increase each value by 2 before reversing it", [3, 0])
        require(new_prediction.status == "ok" and new_prediction.output == [2, 5],
                "reintegrated procedure did not run from the model database")
        CRMSMath.load(installed["math"])
        CRMSTranslation.load(installed["translations"])

        # Tampering with any payload must be caught before installation.
        tampered = root / "tampered.sqlite"
        tampered.write_bytes(database.read_bytes())
        with sqlite3.connect(tampered) as db:
            db.execute("UPDATE learned_memories SET payload_json='{}' "
                       "WHERE kind='knowledge'")
        rejected = root / "rejected"
        try:
            install_model_database(tampered, rejected)
        except ValueError as error:
            require("integrity" in str(error), f"unexpected tamper error: {error}")
        else:
            raise AssertionError("tampered package was accepted")
        require(not rejected.exists(),
                "invalid package created an install destination")

        source_tampered = root / "source-tampered.sqlite"
        source_tampered.write_bytes(database.read_bytes())
        with sqlite3.connect(source_tampered) as db:
            db.execute("UPDATE research_documents SET body='changed' "
                       "WHERE document_id='manual:rotor'")
        try:
            inspect_model_database(source_tampered)
        except ValueError as error:
            require("source integrity" in str(error),
                    f"unexpected source tamper error: {error}")
        else:
            raise AssertionError("tampered embedded source text was accepted")

    print("Portable SQLite learned-model diagnostic: PASS")
    print("embedded and memories-only packaging, source retrieval with exact citations, "
          "provenance retention, runtime reintegration, and tamper rejection: PASS")


if __name__ == "__main__":
    main()
