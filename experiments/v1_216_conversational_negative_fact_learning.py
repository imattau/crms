"""Check conversational teaching of explicit source-backed negative facts."""
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
        root = Path(folder)
        index = CRMSResearchIndex()
        examples = (
            ("ada", "Ada did not design the Engine.", "Ada", "the Engine"),
            ("bea", "Bea did not design the Compiler.", "Bea", "the Compiler"),
            ("cal", "Cal did not design the Device.", "Cal", "the Device"),
        )
        for document_id, sentence, _subject, _obj in examples:
            index.add_document(document_id, document_id, sentence)
        index_path = root / "index.json"
        knowledge_path = root / "knowledge.json"
        index.save(index_path)
        teaching = "Teach a sourced fact pattern from examples: " + "; ".join(
            f'"{sentence}" => "{subject}" | "designed" | "{obj}" '
            f'| "negative" ["{subject}" | "did not design" | "{obj}"]'
            for _document_id, sentence, subject, obj in examples[:2])
        polar_teaching = (
            'Teach a yes/no frame from examples: '
            '"Is it true that Ada designed the Engine?" => no; '
            '"Is it true that Bea designed the Compiler?" => no')
        command = [sys.executable, str(PROJECT / "crms_chat.py"),
                   "--knowledge", str(knowledge_path), "--index", str(index_path),
                   "--dialogue-state", str(root / "dialogue.json"),
                   "--rule-session", str(root / "rule-session.json")]
        output = subprocess.run(
            command, input="\n".join((teaching, "/facts", polar_teaching,
                                       "Is it true that Cal designed the Device?",
                                       "/accept 1",
                                       "Is it true that Cal designed the Device?",
                                       "/write-about Cal",
                                       "/quit")) + "\n", text=True,
            capture_output=True, check=True, timeout=20).stdout
        if ("Sourced fact pattern licensed from 2 examples." not in output
                or "NOT: Ada — designed → the Engine" not in output
                or "NOT: Bea — designed → the Compiler" not in output
                or "Yes/no frame licensed from 2 explicit fact examples" not in output
                or "Review candidate 1 (negative)" not in output
                or "Accepted negative fact: Cal — designed → the Device." not in output
                or "Answer: No." not in output
                or "Cal did not design the Device." not in output
                or "FACT: Ada — designed → the Engine" in output):
            raise SystemExit(f"negative conversational teaching failed:\n{output}")

        knowledge = CRMSKnowledgeBase.load(knowledge_path)
        if knowledge.facts() or len(knowledge.negative_facts()) != 3:
            raise SystemExit("negative teaching/review entered the positive fact store")
        if knowledge.ask("Is it true that Dan designed the Device?").status != "unknown":
            raise SystemExit("missing negative evidence was treated as false")
        sentence = examples[2][1]
        hit = index.search(sentence, limit=1)[0]
        proposals = knowledge.propose_facts_from_hit(
            sentence, research_index=index, hit=hit)
        matching = [candidate for candidate in proposals if (
            candidate.subject, candidate.relation, candidate.object,
            candidate.polarity
        ) == ("Cal", "designed", "the Device", False)]
        if len(matching) != 1:
            raise SystemExit(f"negative frame failed to transfer: {proposals}")
        if knowledge.facts():
            raise SystemExit("negative extraction created an asserted positive fact")

    print("conversational negative fact-learning diagnostic: PASS")
    print("explicit negative labels, cited review and acceptance, polarity-preserving "
          "QA and writing, positive/negative store separation, open-world unknown: PASS")


if __name__ == "__main__":
    main()
