"""Run the terminal chat shell through source ingestion and fact review.

Run from the project root with:
    python3 experiments/v1_39_terminal_chat.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        index = CRMSResearchIndex()
        kb = CRMSKnowledgeBase()
        for doc_id, sentence, subject, obj in (
                ("a", "Ada Lovelace designed the Analytical Engine.",
                 "Ada Lovelace", "the Analytical Engine"),
                ("b", "Grace Hopper designed the Compiler.",
                 "Grace Hopper", "the Compiler")):
            index.add_document(doc_id, doc_id, sentence, f"sources/{doc_id}.txt")
            hit = index.search(sentence, limit=1)[0]
            kb.add_fact_from_hit(subject, "designed", obj, index, hit)
            kb.teach_fact_pattern_from_hit(
                hit.snippet, subject=subject, relation="designed", obj=obj,
                research_index=index, hit=hit)
            kb.teach_question(f"Who designed {obj}?", relation="designed",
                              answer_field="subject", bound_entity=obj,
                              answer=subject)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        state_path = temp / "nested" / "dialogue.json"
        rules_path = temp / "rules.json"
        rule_session_path = temp / "rule-session.json"
        candidate_session_path = temp / "candidate-session.json"
        kb.save(knowledge_path)
        index.save(index_path)
        source_path = temp / "trajectory.txt"
        source_path.write_text(
            "Katherine Johnson designed the trajectory table.", encoding="utf-8")

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(index_path),
            "--dialogue-state", str(state_path),
            "--rules", str(rules_path),
            "--rule-session", str(rule_session_path),
            "--candidate-session", str(candidate_session_path),
        ]
        result = subprocess.run(
            command,
            input=f"/source {source_path}\n"
                  "Who designed the trajectory table?\n"
                  "/accept 1\n"
                  "Who designed it?\n"
                  "/quit\n",
            text=True, capture_output=True, check=False, timeout=20,
        )
        output = result.stdout
        if result.returncode:
            raise SystemExit(
                f"terminal chat exited with status {result.returncode}:\n"
                f"{output}{result.stderr}")
        required = (
            "Indexed trajectory.txt.",
            "1 source claim available for review; use /pending-candidates to inspect.",
            "Accepted positive fact: Katherine Johnson — designed → the trajectory table.",
            "Katherine Johnson designed the trajectory table. "
            "[Source: trajectory.txt; accepted fact]",
            "CRMS state saved. Goodbye.",
        )
        missing = [phrase for phrase in required if phrase not in output]
        if missing:
            raise SystemExit(f"terminal chat omitted expected interactions {missing}:\n{output}")
        restored = CRMSKnowledgeBase.load(knowledge_path)
        if len(restored.facts()) != 3:
            raise SystemExit("terminal candidate acceptance was not persisted")
        if not index_path.exists() or not state_path.exists():
            raise SystemExit("terminal chat did not persist source/dialogue state")

    print("terminal chat diagnostic: PASS")
    print("source ingestion, conversational research, explicit acceptance, pronoun follow-up, persistence: PASS")


if __name__ == "__main__":
    main()
