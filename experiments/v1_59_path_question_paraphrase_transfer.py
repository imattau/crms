"""Check grounded wording transfer for a licensed multi-hop relation path.

Run from the project root with:
    python3 experiments/v1_59_path_question_paraphrase_transfer.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def add_birth_path(kb: CRMSKnowledgeBase, person: str, city: str,
                   country: str, source: str) -> None:
    kb.add_fact(person, "born in", city, f"{source}:birth")
    kb.add_fact(city, "located in", country, f"{source}:location")


def main() -> None:
    kb = CRMSKnowledgeBase()
    add_birth_path(kb, "Ada Lovelace", "London", "United Kingdom", "bio:ada")
    add_birth_path(kb, "Albert Einstein", "Ulm", "Germany", "bio:einstein")
    add_birth_path(kb, "Alan Turing", "London", "United Kingdom", "bio:turing")

    q_ada = "Which country is Ada Lovelace born in?"
    q_einstein = "Which country is Albert Einstein born in?"
    q_turing = "What nation contains the birthplace of Alan Turing?"
    q_held_out = "What nation contains the birthplace of Ada Lovelace?"
    path = ["born in", "located in"]
    if kb.teach_path_question(
            q_ada, relations=path, bound_entity="Ada Lovelace",
            answer="United Kingdom"):
        raise SystemExit("first path frame example licensed too early")
    if not kb.teach_path_question(
            q_einstein, relations=path, bound_entity="Albert Einstein",
            answer="Germany"):
        raise SystemExit("two examples did not license the canonical path frame")
    if not kb.teach_path_question(
            q_turing, relations=path, bound_entity="Alan Turing",
            answer="United Kingdom"):
        raise SystemExit("licensed path did not transfer to a new exact wording")

    held_out = kb.ask(q_held_out)
    if (held_out.status != "answered"
            or held_out.answer != "United Kingdom"
            or len(held_out.proofs or []) != 1
            or len(held_out.proofs[0]) != 2):
        raise SystemExit(f"path paraphrase did not produce a proof-backed answer: {held_out}")
    unseen = kb.ask("What territory contains the birthplace of Ada Lovelace?")
    if unseen.status != "unknown":
        raise SystemExit(f"untrained path wording generalized: {unseen}")
    unknown_person = kb.ask("What nation contains the birthplace of Unknown Person?")
    if unknown_person.status != "unknown" or not unknown_person.matched_templates:
        raise SystemExit(f"missing path did not abstain in learned frame: {unknown_person}")

    kb.add_fact("Engine", "located in", "France", "geo:engine")
    kb.add_fact("Compiler", "located in", "Germany", "geo:compiler")
    if kb.teach_path_question(
            "What nation contains the Engine?", relations=["located in"],
            bound_entity="Engine", answer="France"):
        raise SystemExit("one example borrowed unrelated path-frame support")
    if kb.ask("What nation contains the Compiler?").status != "unknown":
        raise SystemExit("unlicensed path sequence generalized after one example")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        state_path = temp / "dialogue.json"
        rules_path = temp / "rules.json"
        session_path = temp / "rule-session.json"
        kb.save(knowledge_path)
        loaded = CRMSKnowledgeBase.load(knowledge_path).ask(q_held_out)
        if loaded.status != "answered" or loaded.answer != "United Kingdom":
            raise SystemExit(f"path wording transfer did not persist: {loaded}")

        seed = CRMSKnowledgeBase()
        add_birth_path(seed, "Ada Lovelace", "London", "United Kingdom", "bio:ada")
        add_birth_path(seed, "Albert Einstein", "Ulm", "Germany", "bio:einstein")
        add_birth_path(seed, "Alan Turing", "London", "United Kingdom", "bio:turing")
        seed.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        commands = [
            f"/teach-path-question {q_ada}|born in>located in|Ada Lovelace|United Kingdom",
            f"/teach-path-question {q_einstein}|born in>located in|Albert Einstein|Germany",
            f"/teach-path-question {q_turing}|born in>located in|Alan Turing|United Kingdom",
            "/quit",
        ]
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(knowledge_path), "--index", str(index_path),
               "--dialogue-state", str(state_path), "--rules", str(rules_path),
               "--rule-session", str(session_path)]
        trained = subprocess.run(
            cli, input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "Path question frame licensed." not in trained.stdout:
            raise SystemExit(f"CLI did not license transferred path wording:\n{trained.stdout}")
        asked = subprocess.run(
            cli, input=f"{q_held_out}\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "Answer: United Kingdom." not in asked.stdout or "Proof 1:" not in asked.stdout:
            raise SystemExit(f"CLI did not answer with the stored path proof:\n{asked.stdout}")

    print("path-question paraphrase transfer: PASS")
    print("same-path license, one-example new wording, proof-backed transfer, wording/entity abstention, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
