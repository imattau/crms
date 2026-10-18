"""Learn a reviewed question slot that maps inside a fact endpoint."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def teach(kb: CRMSKnowledgeBase, place: str, topic: str, source: str) -> bool:
    kb.add_fact(f"Researchers at {place}", "studied", topic, source)
    return kb.teach_subject_pattern_question(
        f"What research happened at {place}?", relation="studied",
        answer_field="object", bound_entity=place, answer=topic)


def main() -> None:
    kb = CRMSKnowledgeBase()
    require(not teach(kb, "Meridian Institute", "quartz field", "study:one"),
            "one example licensed a subject-pattern question")
    first = kb.ask("What research happened at Meridian Institute?")
    require(first.status != "answered",
            "a single subject-pattern example answered a question")
    require(teach(kb, "Atlas Center", "basalt samples", "study:two"),
            "two distinct fact-backed examples did not license the frame")

    kb.add_fact("Researchers at Boreal Station", "studied", "mica", "study:three")
    transferred = kb.ask("What research happened at Boreal Station?")
    require(transferred.status == "answered" and transferred.answer == "mica",
            f"learned event question did not transfer to a held-out place: {transferred}")
    require(any(item.get("kind") == "subject_pattern_question_frame"
                and item.get("fact_endpoint_pattern") == "researchers at {entity}"
                for item in transferred.language_evidence or []),
            "answer omitted the learned role-pattern explanation")
    require(any("study:three" in fact.get("sources", [])
                for fact in transferred.evidence or []),
            "held-out answer lost its direct source evidence")

    unsupported = kb.ask("What science happened at Boreal Station?")
    require(unsupported.status != "answered",
            "the learned frame transferred to unrelated question wording")
    missing = kb.ask("What research happened at Unknown Institute?")
    require(missing.status == "unknown",
            f"unsupported place received an answer: {missing}")

    kb.add_negative_fact("Researchers at Boreal Station", "studied", "mica",
                         "study:negative")
    conflict = kb.ask("What research happened at Boreal Station?")
    require(conflict.status == "ambiguous",
            f"positive and negative direct evidence were not surfaced: {conflict}")

    object_pattern_kb = CRMSKnowledgeBase()
    for site, place in (("Granite Quarry", "North Valley"),
                        ("Basalt Mine", "East Valley")):
        object_pattern_kb.add_fact(
            site, "supplies", f"material from {place}", f"supply:{place}")
        licensed = object_pattern_kb.teach_subject_pattern_question(
            f"Which site supplies from {place}?", relation="supplies",
            answer_field="subject", bound_entity=place, answer=site)
    require(licensed, "object-endpoint patterns did not license transfer")
    object_pattern_kb.add_fact(
        "Slate Works", "supplies", "material from South Valley", "supply:south")
    object_transfer = object_pattern_kb.ask(
        "Which site supplies from South Valley?")
    require(object_transfer.status == "answered"
            and object_transfer.answer == "Slate Works",
            f"learned object-endpoint pattern did not transfer: {object_transfer}")

    conflicted_teaching = CRMSKnowledgeBase()
    conflicted_teaching.add_fact(
        "Researchers at Meridian Institute", "studied", "quartz field", "teach:positive")
    conflicted_teaching.add_negative_fact(
        "Researchers at Meridian Institute", "studied", "quartz field", "teach:negative")
    try:
        conflicted_teaching.teach_subject_pattern_question(
            "What research happened at Meridian Institute?", relation="studied",
            answer_field="object", bound_entity="Meridian Institute",
            answer="quartz field")
    except ValueError:
        pass
    else:
        raise SystemExit("conflicted fact pair licensed a question pattern")

    with tempfile.TemporaryDirectory(prefix="crms-subject-pattern-question-") as folder:
        root = Path(folder)
        json_path = root / "knowledge.json"
        kb.save(json_path)
        restored = CRMSKnowledgeBase.load(json_path)
        require(restored.ask("What research happened at Atlas Center?").answer
                == "basalt samples",
                "JSON persistence lost the subject-pattern question frame")
        sqlite_path = root / "knowledge.sqlite"
        kb.save(sqlite_path)
        sqlite_restored = CRMSKnowledgeBase.load(sqlite_path)
        require(sqlite_restored.ask(
                    "What research happened at Atlas Center?").answer
                == "basalt samples",
                "SQLite persistence lost the subject-pattern question frame")
        sqlite_restored.close()

        cli_knowledge = root / "cli-knowledge.json"
        seeded = CRMSKnowledgeBase()
        seeded.add_fact("Researchers at Meridian Institute", "studied",
                        "quartz field", "cli:one")
        seeded.add_fact("Researchers at Atlas Center", "studied",
                        "basalt samples", "cli:two")
        seeded.add_fact("Researchers at Boreal Station", "studied", "mica",
                        "cli:three")
        seeded.save(cli_knowledge)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(cli_knowledge),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
        ]
        run = subprocess.run(
            command,
            input=("/teach-question-pattern What research happened at "
                   "Meridian Institute?|studied|object|Meridian Institute|quartz field\n"
                   "/teach-question-pattern What research happened at "
                   "Atlas Center?|studied|object|Atlas Center|basalt samples\n"
                   "What research happened at Boreal Station?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=30, check=False)
        require(run.returncode == 0
                and "Subject-pattern question frame licensed." in run.stdout
                and "Researchers at Boreal Station studied mica." in run.stdout
                and "Source: cli:three" in run.stdout,
                f"CLI teaching/persistence setup failed: {run.stdout}\n{run.stderr}")

    require(kb.remove_fact("Researchers at Meridian Institute", "studied",
                           "quartz field", "study:one"),
            "could not retract subject-pattern training evidence")
    stale_frame = kb.ask("What research happened at Boreal Station?")
    require(stale_frame.status != "answered",
            "a role-pattern frame remained active after losing a required example")

    print("subject-pattern question learning diagnostic: PASS")
    print("two-example gate, held-out role-pattern transfer, exact fact evidence, "
          "unsupported wording/place abstention, conflict handling, JSON/SQLite "
          "persistence, subject/object endpoint transfer, conflict rejection "
          "during teaching, source-retraction invalidation, and CLI: PASS")


if __name__ == "__main__":
    main()
