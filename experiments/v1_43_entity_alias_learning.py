"""Check source-cited entity aliases in question answering and the CLI.

Run from the project root with:
    python3 experiments/v1_43_entity_alias_learning.py
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


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        kb = CRMSKnowledgeBase()
        index = CRMSResearchIndex()
        examples = [
            ("a", "Ada Lovelace designed the Analytical Engine.",
             "Ada Lovelace", "the Analytical Engine"),
            ("b", "Grace Hopper designed the Compiler.",
             "Grace Hopper", "the Compiler"),
        ]
        for doc_id, sentence, subject, obj in examples:
            index.add_document(doc_id, doc_id, sentence, f"sources/{doc_id}.txt")
            hit = index.search(sentence, limit=1)[0]
            citation = index.citation(hit)
            kb.add_fact(subject, "designed", obj, citation)
            kb.teach_fact_pattern_from_hit(
                hit.snippet, subject=subject, relation="designed", obj=obj,
                research_index=index, hit=hit)
            kb.teach_question(f"Who designed {obj}?", relation="designed",
                              answer_field="subject", bound_entity=obj,
                              answer=subject)
        kb.add_fact("the Analytical Engine", "uses", "steam", "a2")
        kb.add_fact("the Compiler", "uses", "electricity", "b2")
        index.add_document(
            "alias", "Engine terminology",
            "The Analytical Engine is also called the Engine in these notes.",
            "sources/alias.txt")
        index.add_document(
            "compiler-alias", "Compiler terminology",
            "The Compiler is also called the Engine in these notes.",
            "sources/compiler-alias.txt")
        kb_path, index_path, state_path = (
            temp / "knowledge.json", temp / "index.json", temp / "dialogue.json")
        kb.save(kb_path)
        index.save(index_path)

        turns = [
            "/teach-alias the Engine|the Analytical Engine|Engine terminology",
            "/aliases",
            "/teach-alias the Engine|the Compiler|Compiler terminology",
            "/teach-path-question What does the Analytical Engine use?|uses|the Analytical Engine|steam",
            "/teach-path-question What does the Compiler use?|uses|the Compiler|electricity",
            "Who designed the Engine?",
            "What does the Engine use?",
            "/forget-alias the Engine",
            "/teach-alias the Engine|the Compiler|Compiler terminology",
            "Who designed the Engine?",
            "What does the Engine use?",
            "Who designed the quantum machine?",
            "/quit",
        ]
        result = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(kb_path), "--index", str(index_path),
             "--dialogue-state", str(state_path)],
            input="\n".join(turns) + "\n", text=True, capture_output=True,
            check=True, timeout=20)
        output = result.stdout
        required = ("Learned cited alias: the Engine → the Analytical Engine.",
                    "the engine → the Analytical Engine", "Could not teach alias:",
                    "Answer: Ada Lovelace.", "Answer: steam.",
                    "Forgot entity alias: the Engine.",
                    "Learned cited alias: the Engine → the Compiler.",
                    "Answer: Grace Hopper.", "Answer: electricity.",
                    "I found relevant passages, but no learned fact pattern produced a candidate answer.")
        missing = [phrase for phrase in required if phrase not in output]
        if missing:
            raise SystemExit(f"alias dialogue omitted {missing}:\n{output}")
        restored = CRMSKnowledgeBase.load(kb_path)
        answer = restored.ask("Who designed the Engine?")
        unknown = restored.ask("Who designed the quantum machine?")
        if answer.status != "answered" or answer.answer != "Grace Hopper":
            raise SystemExit(f"saved alias did not resolve: {answer}")
        if unknown.status != "unknown":
            raise SystemExit(f"unlearned name was treated as an alias: {unknown}")
        aliases = restored.entity_aliases()
        if len(aliases) != 1 or aliases[0]["entity"] != "the Compiler":
            raise SystemExit("alias provenance did not persist")

    print("entity alias learning diagnostic: PASS")
    print("cited alias acquisition, collision rejection, correction, QA/path transfer, abstention, persistence: PASS")


if __name__ == "__main__":
    main()
