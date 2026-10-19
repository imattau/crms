"""Ground yes/no language frames to derived, proof-backed relations."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for subject, middle, target, source in (
            ("Ada", "Bea", "Cal", "one"),
            ("Dee", "Eli", "Fay", "two"),
            ("Nia", "Oren", "Pia", "three")):
        kb.add_fact(subject, "parent", middle, f"{source}:first")
        kb.add_fact(middle, "parent", target, f"{source}:second")
    kb.add_inference_rule("parent-transitivity", "parent", "parent", "ancestor")
    return kb


def main() -> None:
    kb = seed()
    for question, subject, obj in (
            ("Is Ada an ancestor of Cal?", "Ada", "Cal"),
            ("Is Dee an ancestor of Fay?", "Dee", "Fay")):
        licensed = kb.teach_polar_question(
            question, subject=subject, relation="ancestor", obj=obj, answer=True)
    if not licensed:
        raise SystemExit("two proof-backed examples did not license the polar frame")
    learned = kb.ask("Is Nia an ancestor of Pia?")
    if (learned.status != "answered" or learned.truth is not True
            or not learned.inference_proofs):
        raise SystemExit(f"learned language frame did not execute inference: {learned}")
    rendered = kb.render(learned)
    if "parent-transitivity" not in rendered or "three:first" not in rendered:
        raise SystemExit(f"rendered answer omitted rule proof provenance:\n{rendered}")

    unknown = kb.ask("Could Nia have been an ancestor of Pia?")
    if unknown.status != "unknown":
        raise SystemExit(f"unlicensed wording was generalized: {unknown}")

    kb.add_negative_fact("Nia", "ancestor", "Pia", "explicit:negative")
    conflict = kb.ask("Is Nia an ancestor of Pia?")
    if (conflict.status != "ambiguous" or not conflict.inference_proofs
            or "three:first" not in kb.render(conflict)):
        raise SystemExit(f"inferred-positive/explicit-negative conflict was hidden: {conflict}")

    negative_kb = seed()
    negative_kb.add_fact("Gus", "parent", "Hal", "Gus:first")
    negative_kb.add_fact("Hal", "parent", "Ivy", "Hal:second")
    negative_kb.add_negative_fact("Gus", "ancestor", "Ivy", "negative:source")
    try:
        negative_kb.teach_polar_question(
            "Is Gus an ancestor of Ivy?", subject="Gus", relation="ancestor",
            obj="Ivy", answer=False)
    except ValueError:
        pass
    else:
        raise SystemExit("negative example with a positive inferred proof was accepted")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json", "session.json")}
        kb = seed()
        kb.save(paths["knowledge.json"])
        CRMSResearchIndex().save(paths["index.json"])
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(paths["knowledge.json"]),
               "--index", str(paths["index.json"]),
               "--dialogue-state", str(paths["dialogue.json"]),
               "--rules", str(paths["rules.json"]),
               "--rule-session", str(paths["session.json"])]
        commands = [
            "/teach-polar Is Ada an ancestor of Cal?|Ada|ancestor|Cal|yes",
            "/teach-polar Is Dee an ancestor of Fay?|Dee|ancestor|Fay|yes",
            "Is Nia an ancestor of Pia?",
            "why?",
            "/quit",
        ]
        output = subprocess.run(
            cli, input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20).stdout
        if ("CRMS> Yes." not in output
                or "Because Nia — parent → Oren and Oren — parent → Pia" not in output
                or "parent-transitivity" not in output
                or "three:first" not in output or "three:second" not in output):
            raise SystemExit(f"CLI did not answer through the learned frame and rule:\n{output}")
        loaded = CRMSKnowledgeBase.load(paths["knowledge.json"])
        response = loaded.ask("Is Nia an ancestor of Pia?")
        if response.status != "answered" or not response.inference_proofs:
            raise SystemExit("learned language-to-inference path did not persist")
    print("language frame over inference diagnostic: PASS")
    print("proof-backed teaching, held-out derived answer, wording gate, conflict, CLI, persistence: PASS")


if __name__ == "__main__":
    main()
