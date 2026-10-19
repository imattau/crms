"""Review source-derived object-question facts and learn their sentence frame.

Run from the project root with:
    python3 experiments/v1_283_reviewed_object_wh_source_learning.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def response_chunks(output: str, turns: list[str]) -> dict[str, str]:
    chunks = [chunk.strip() for chunk in output.split("you> ")[1:]]
    if len(chunks) != len(turns):
        raise SystemExit(
            f"chat emitted {len(chunks)} responses for {len(turns)} turns")
    return dict(zip(turns, chunks))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-object-wh-learning-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        examples = (
            ("0266", "quartz field 0266"),
            ("0300", "lab-grown opal 0300"),
            ("0400", "graph theory 0400"),
        )
        for identifier, topic in examples:
            surface = "investigated" if identifier == "0400" else "studied"
            sentence = (
                f"Researchers at the Meridian Institute {identifier} "
                f"{surface} {topic}.")
            index.add_document(
                f"record-{identifier}", f"Research Record {identifier}",
                sentence, f"fixture://record-{identifier}")
        index.close()

        knowledge_path = root / "knowledge.json"
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(knowledge_path),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
        ]
        questions = [
            "What did researchers at the Meridian Institute 0266 study?",
            "accept candidate 1",
            "What did researchers at the Meridian Institute 0300 study?",
            "accept candidate 1",
            "What did researchers at the Meridian Institute 0400 study?",
            "accept candidate 1",
            "What did researchers at the Meridian Institute 0400 study?",
            "What did researchers at the Meridian Institute 0400 investigate?",
            "What did researchers at the Meridian Institute 0266 study?",
            "What did researchers at the Meridian Institute 9999 study?",
            "What did researchers at the Meridian Institute 0266 invent?",
            "/quit",
        ]
        run = subprocess.run(
            command, input="\n".join(questions) + "\n", text=True,
            capture_output=True, cwd=root, timeout=45, check=False)
        require(run.returncode == 0,
                f"chat failed ({run.returncode}):\n{run.stderr}\n{run.stdout}")
        output = run.stdout
        expected_sources = (
            "Researchers at the Meridian Institute 0266 studied quartz field 0266.",
            "Researchers at the Meridian Institute 0300 studied lab-grown opal 0300.",
            "Researchers at the Meridian Institute 0400 investigated graph theory 0400.",
        )
        require(all(text in output for text in expected_sources),
                f"source candidates or accepted facts lost exact evidence: {output}")
        require(output.count("1 source claim awaiting review") == 3
                and output.count("Accepted positive fact: ") == 3
                and "Possible relation alignment for review" in output
                and "your question uses 'study'" in output
                and "the source uses 'investigated'" in output,
                f"source facts or relation-alignment proposal missed review: {output}")
        by_turn = response_chunks(output, questions)
        learned_relation = by_turn[
            "What did researchers at the Meridian Institute 0400 investigate?"]
        require("graph theory 0400" in learned_relation
                and "accepted fact" in learned_relation,
                f"reviewed predicate wording did not transfer after acceptance: {learned_relation}")
        missing = by_turn[
            "What did researchers at the Meridian Institute 9999 study?"]
        require("quartz field 0266" not in missing
                and "lab-grown opal 0300" not in missing,
                f"a licensed question frame answered an unsupported entity: {missing}")
        wrong_relation = by_turn[
            "What did researchers at the Meridian Institute 0266 invent?"]
        require("Unverified source candidate" not in wrong_relation
                and "quartz field 0266" not in wrong_relation,
                f"an unlicensed relation was proposed as a source candidate: {wrong_relation}")

        knowledge = CRMSKnowledgeBase.load(knowledge_path)
        facts = {(fact.subject, fact.relation, fact.object)
                 for fact in knowledge.facts()}
        require(("Researchers at the Meridian Institute 0266", "study",
                 "quartz field 0266") in facts
                and ("Researchers at the Meridian Institute 0300", "study",
                     "lab-grown opal 0300") in facts
                and ("Researchers at the Meridian Institute 0400", "study",
                     "graph theory 0400") in facts,
                f"reviewed canonical relation facts were not stored: {facts}")
        licensed = [
            (key, examples_by_pair)
            for key, examples_by_pair in knowledge._fact_pattern_examples.items()
            if key[1] == ("study",)
            and knowledge._fact_pattern_is_licensed(key, examples_by_pair)
        ]
        require(licensed,
                "varied reviewed source examples did not license the study frame")

    print("reviewed object-question source learning: PASS")
    print("exact cited evidence, human review before storage, canonical relation, "
          "varied-frame licensing, unsupported-entity and wrong-relation guards: PASS")


if __name__ == "__main__":
    main()
