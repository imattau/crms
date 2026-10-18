"""Verify indexed fact lookup, provenance updates, qualifiers, and reload."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_fact_store import SQLiteFactMap
from crms_model import CRMSModel
from crms_package import export_model_database


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    for number in range(10_000):
        kb.add_fact(f"Author {number}", "wrote", f"Book {number}",
                    f"source:{number}")
    kb.add_fact("Ada", "wrote", "Analytical Engine", "source:ada")
    kb.add_fact("Ada", "wrote", "Analytical Engine", "source:ada-2")
    kb.add_fact("Ada", "wrote", "Analytical Engine", "source:ada-1843",
                qualifiers={"year": "1843"})
    kb.add_fact("Grace", "wrote", "Compiler", "source:grace")
    kb.add_fact("Ann", "parent", "Bea", "source:ann-bea")
    kb.add_fact("Bea", "parent", "Cara", "source:bea-cara")
    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    kb.teach_question("Who wrote Analytical Engine?", relation="wrote",
                      answer_field="subject", bound_entity="Analytical Engine",
                      answer="Ada")
    kb.teach_question("Who wrote Compiler?", relation="wrote",
                      answer_field="subject", bound_entity="Compiler",
                      answer="Grace")

    object_key = (("wrote",), ("analytical", "engine"))
    subject_key = (("wrote",), ("ada",))
    object_candidates = kb._facts_by_relation_object[object_key]
    subject_candidates = kb._facts_by_relation_subject[subject_key]
    require(len(object_candidates) == 2 and len(subject_candidates) == 2,
            "fact lookup index includes unrelated records or loses qualifiers")
    exact = kb._find_fact("wrote", "object", "Analytical Engine", "Ada")
    qualified = kb._find_fact(
        "wrote", "object", "Analytical Engine", "Ada",
        kb._normalize_qualifiers({"year": "1843"}))
    require(len(exact) == 2 and len(qualified) == 1
            and qualified[0].qualifiers == (("year", "1843"),),
            "indexed lookup changed existing qualifier-subset behavior")
    inverse = kb._find_fact("wrote", "subject", "Ada", "Analytical Engine")
    require(len(inverse) == 2,
            "subject-side indexed lookup lost direct fact evidence")

    require(kb.remove_fact("Ada", "wrote", "Analytical Engine", "source:ada"),
            "source retraction failed")
    remaining = kb._find_fact("wrote", "object", "Analytical Engine", "Ada")
    require(len(remaining) == 2 and len(remaining[0].sources) == 1,
            "retraction dropped an alternate source or qualified fact")
    require(kb.remove_fact("Ada", "wrote", "Analytical Engine", "source:ada-2"),
            "last unqualified source retraction failed")
    require(len(kb._facts_by_relation_object[object_key]) == 1
            and len(kb._find_fact("wrote", "object", "Analytical Engine", "Ada")) == 1,
            "index retained a retracted record")

    with tempfile.TemporaryDirectory(prefix="crms-fact-index-") as folder:
        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        require(len(restored._find_fact(
            "wrote", "object", "Analytical Engine", "Ada",
            restored._normalize_qualifiers({"year": "1843"}))) == 1,
            "fact indexes were not rebuilt on load")
        require(len(restored._facts_by_relation_subject[subject_key]) == 1,
                "subject index did not survive persistence rebuild")
        sqlite_path = Path(folder) / "fact-store.sqlite"
        disk_backed = CRMSKnowledgeBase.load(path, fact_db=sqlite_path)
        require(isinstance(disk_backed._facts, SQLiteFactMap)
                and isinstance(disk_backed._negative_facts, SQLiteFactMap)
                and len(disk_backed._facts) == len(restored._facts)
                and len(disk_backed.facts()) == len(restored.facts()),
                "SQLite fact store did not preserve loaded records")
        require(len(disk_backed._find_fact(
            "wrote", "object", "Analytical Engine", "Ada")) == 1,
            "SQLite indexed lookup did not return the source-backed fact")
        answer = disk_backed.ask("Who wrote Analytical Engine?")
        require(answer.status == "answered" and answer.answer == "Ada",
                f"question answering did not use the SQLite fact backend: {answer}")
        # Direct stored-relation question parsing must use indexed relation / 
        # object lookups rather than loading the entire SQLite fact payload set.
        direct_kb = CRMSKnowledgeBase()
        for number in range(10_000):
            direct_kb.add_fact(f"Author {number}", "wrote", f"Book {number}",
                               f"source:direct-{number}")
        direct_kb.add_fact("Ada Lovelace", "designed", "Analytical Engine",
                           "source:direct-ada")
        direct_json = Path(folder) / "direct-knowledge.json"
        direct_kb.save(direct_json)
        direct_sqlite = CRMSKnowledgeBase.load(
            direct_json, fact_db=Path(folder) / "direct-facts.sqlite")
        direct_answer = direct_sqlite.ask(
            "Who designed the Analytical Engine?")
        require(direct_answer.status == "answered"
                and direct_answer.answer == "Ada Lovelace",
                "SQLite direct-relation question failed with many unrelated facts")
        direct_sqlite.close()
        direct_kb.close()
        inference_facts, inference_negatives, inference_rules = (
            disk_backed._sqlite_inference_snapshot(
                "ancestor", (), list(disk_backed._inference_rules.values())))
        require(len(inference_facts) == 2 and not inference_negatives
                and len(inference_rules) == 1
                and all(item["relation"] == "parent" for item in inference_facts),
                "SQLite inference snapshot included unrelated relation facts")
        inferred = disk_backed.infer_relation("Ann", "ancestor", "Cara")
        require(inferred.status == "answered" and inferred.proofs,
                f"bounded inference failed over SQLite relation snapshot: {inferred}")
        practiced = disk_backed.practice_relation("Ann", "ancestor", "Cara")
        require(practiced.status == "answered"
                and disk_backed.retrieve_derived_case(
                    "Ann", "ancestor", "Cara") is not None,
                "SQLite-backed proof practice was not stored and validated")
        cached = disk_backed.infer_relation("Ann", "ancestor", "Cara")
        require(cached.status == "answered" and cached.expansions == 0,
                "SQLite inference did not reuse an unchanged practiced proof")
        disk_backed.add_fact("Zed", "wrote", "Unrelated Book", "source:unrelated")
        unaffected = disk_backed.infer_relation("Ann", "ancestor", "Cara")
        require(unaffected.status == "answered" and unaffected.expansions == 0,
                "unrelated SQLite fact invalidated the scoped proof cache")
        disk_backed.add_negative_fact(
            "Ann", "ancestor", "Cara", "source:planted-negative")
        conflicted = disk_backed.infer_relation("Ann", "ancestor", "Cara")
        require(conflicted.status == "ambiguous"
                and conflicted.reason_code == "contradiction",
                "relevant negative SQLite evidence did not invalidate proof reuse")
        disk_backed.remove_negative_fact(
            "Ann", "ancestor", "Cara", "source:planted-negative")
        disk_backed.add_fact("Cara", "parent", "Dee", "source:cara-dee")
        disk_backed.add_inference_rule(
            "derived-route", "ancestor", "parent", "reaches")
        reused_subgoal = disk_backed.infer_relation("Ann", "reaches", "Dee")
        require(reused_subgoal.status == "answered" and reused_subgoal.proofs,
                "SQLite-backed derived proof was not reusable as a subgoal")
        for subject, relation, obj, source in (
                ("Nia", "employs", "Sam", "typed:employs"),
                ("Sam", "owns", "Jet", "typed:owns"),
                ("Jet", "located in", "Sydney", "typed:location"),
                ("Sam", "is-a", "person", "typed:person"),
                ("Jet", "is-a", "asset", "typed:asset")):
            disk_backed.add_fact(subject, relation, obj, source)
        disk_backed.add_inference_rule(
            "typed-route", "employs", "owns", "reaches",
            third_relation="located in", middle_kind="person",
            second_middle_kind="asset")
        typed_inference = disk_backed.infer_relation("Nia", "reaches", "Sydney")
        require(typed_inference.status == "answered"
                and typed_inference.proofs
                and typed_inference.proofs[0].get("middle_kind_facts"),
                f"typed three-premise SQLite inference failed: {typed_inference}")
        disk_backed.add_fact("Bea", "wrote", "Compiler", "source:bea")
        require(len(disk_backed._find_fact(
            "wrote", "object", "Compiler", "Bea")) == 1,
            "SQLite fact store did not index an added fact")
        snapshot = copy.deepcopy(disk_backed)
        snapshot.add_fact("Cal", "wrote", "Parser", "source:cal")
        require(not disk_backed._find_fact("wrote", "object", "Parser", "Cal")
                and len(snapshot._find_fact(
                    "wrote", "object", "Parser", "Cal")) == 1,
                "deep-copied SQLite-backed knowledge did not isolate its facts")
        disk_backed.close()
        reused_store = CRMSKnowledgeBase.load(path, fact_db=sqlite_path)
        require(isinstance(reused_store._facts, SQLiteFactMap)
                and len(reused_store._facts) == len(restored._facts)
                and len(reused_store._find_fact(
                    "wrote", "object", "Analytical Engine", "Ada")) == 1,
                "existing CRMS fact sidecar was not safely rebuilt from JSON")
        reused_store.close()
        missing_source = Path(folder) / "missing-source.json"
        missing_source.write_text(json.dumps({
            "format_version": CRMSKnowledgeBase.FORMAT_VERSION,
            "facts": [{"subject": "A", "relation": "r", "object": "B",
                       "sources": []}],
        }), encoding="utf-8")
        try:
            CRMSKnowledgeBase.load(missing_source)
        except ValueError as error:
            require("provenance" in str(error),
                    f"stream loader changed missing-source validation: {error}")
        else:
            raise SystemExit("stream loader accepted a fact without provenance")
        truncated = Path(folder) / "truncated.json"
        truncated.write_text('{"format_version":1,"facts":[', encoding="utf-8")
        try:
            CRMSKnowledgeBase.load(truncated)
        except ValueError:
            pass
        else:
            raise SystemExit("stream loader accepted truncated fact JSON")

        chat_root = Path(folder) / "chat"
        chat_root.mkdir()
        chat_knowledge = chat_root / "knowledge.json"
        chat_rules = chat_root / "rules.json"
        chat_kb = CRMSKnowledgeBase()
        chat_kb.add_fact("Ada", "designed", "Engine", "src:ada")
        chat_kb.add_fact("Grace", "designed", "Compiler", "src:grace")
        chat_kb.teach_question("Who designed Engine?", relation="designed",
                               answer_field="subject", bound_entity="Engine",
                               answer="Ada")
        chat_kb.teach_question("Who designed Compiler?", relation="designed",
                               answer_field="subject", bound_entity="Compiler",
                               answer="Grace")
        chat_kb.save(chat_knowledge)
        CRMSModel().save(chat_rules)
        model_database = chat_root / "model.sqlite"
        export_model_database(model_database, knowledge=chat_knowledge,
                              rules=chat_rules)
        cli = [sys.executable,
               str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
               "--model-db", str(model_database)]
        for _ in range(2):
            run = subprocess.run(
                cli, input="Who designed Engine?\n/quit\n", text=True,
                capture_output=True, check=False, timeout=30)
            require(run.returncode == 0 and "Ada" in run.stdout,
                    f"portable-model SQLite fact chat failed:\n{run.stdout}\n{run.stderr}")

    print("fact lookup index diagnostic: PASS")
    print("10,000 unrelated facts, indexed SQLite QA/inference, selective relation snapshots, source updates, JSON streaming, sidecar reuse, CLI/model reload, and malformed input rejection: PASS")


if __name__ == "__main__":
    main()
