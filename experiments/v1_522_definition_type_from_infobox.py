"""Use exact-title infobox type as cited fallback for definition questions."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import _natural_type_field_evidence
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex, CRMSSQLiteResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    memory_index = CRMSResearchIndex()
    memory_index.add_document(
        "python-disambiguated", "Python (programming language)",
        "Infobox programming language\ndesigner = Guido van Rossum",
        "python.txt")
    require([hit.document_id for hit in
             memory_index.exact_title_matches("Python programming language")]
            == ["python-disambiguated"],
            "normalized parenthetical title did not match the memory index")
    memory_index.add_document(
        "python-unqualified", "Python", "A separate exact-title page.",
        "python-short.txt")
    require([hit.document_id for hit in memory_index.exact_title_matches("Python")]
            == ["python-unqualified"],
            "the shorter exact title was confused with its disambiguated page")

    with tempfile.TemporaryDirectory(prefix="crms-v1-522-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "mount-everest", "Mount Everest",
            "Infobox mountain\nname = Mount Everest\n"
            "Mount Everest is in the Himalayas, a tall mountain range in Asia.",
            "mount-everest.txt")
        index.add_document(
            "everest-avalanche", "2014 Mount Everest avalanche",
            "On 18 April 2014, an avalanche on Mount Everest killed 16 people "
            "and injured 9 others.", "avalanche.txt")
        index.add_document(
            "photosynthesis", "Photosynthesis",
            "Infobox process\nname = Photosynthesis\n"
            "Photosynthesis is a process by which plants use sunlight to make food.",
            "photosynthesis.txt")
        index.add_document(
            "atlantis-report", "Atlantis report",
            "An expedition searched for Atlantis but found no evidence.",
            "atlantis-report.txt")

        field = _natural_type_field_evidence(index, "What is Mount Everest?")
        require(field is not None
                and field["realized_answer"]["field_text"] == "Infobox mountain"
                and index.resolve_citation(field["citation"]) == "Infobox mountain",
                f"exact-title infobox type was not cited exactly: {field!r}")
        require(_natural_type_field_evidence(index, "What is Atlantis?") is None,
                "an unrelated title mention was treated as a type field")
        index.close()

        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        state = root / "state"
        state.mkdir()
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(index_path),
            "--feedback-db", str(state / "feedback.sqlite3"),
            "--dialogue-state", str(state / "dialogue.json"),
            "--rules", str(state / "rules.json"),
            "--rule-session", str(state / "rule-session.json"),
            "--candidate-session", str(state / "candidates.json"),
            "--math", str(state / "math.json"),
            "--translations", str(state / "translations.json"),
        ]
        run = subprocess.run(
            command,
            input=("What is Mount Everest?\n"
                   "What is Photosynthesis?\n"
                   "What is Atlantis?\n/quit\n"),
            text=True, capture_output=True, cwd=state, timeout=30)
        require(run.returncode == 0,
                f"fresh chat failed: {run.stderr}\n{run.stdout}")
        require("The source classifies Mount Everest as a mountain." in run.stdout
                and "field “Infobox mountain”" in run.stdout,
                f"definition fallback omitted its cited type: {run.stdout}")
        require("Photosynthesis is a process by which plants use sunlight to make food."
                in run.stdout,
                f"a direct prose definition was displaced by metadata: {run.stdout}")
        require("The source classifies Atlantis" not in run.stdout,
                f"an event mention was promoted to a definition: {run.stdout}")

        reloaded = CRMSKnowledgeBase.load(knowledge_path)
        require(not reloaded.facts(),
                "structured evidence was silently promoted to accepted knowledge")

    print("exact-title infobox type supplies a cited definition fallback: PASS")
    print("direct prose definition remains preferred; unrelated mention abstains: PASS")
    print("structured evidence stays review-only and does not enter accepted facts: PASS")


if __name__ == "__main__":
    main()
