"""Exercise topic-based multi-paper retrieval and topicality labels."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_research_list_request, _render_research_list
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for question, expected in (
            ("Which papers discuss protein function prediction?",
             "protein function prediction"),
            ("List studies about graph neural networks in this corpus",
             "graph neural networks")):
        require(_natural_research_list_request(question) == expected,
                f"paper-list intent was not parsed: {question}")
    require(_natural_research_list_request("What is protein function prediction?")
            is None,
            "ordinary factual question was captured as a list request")

    index = CRMSResearchIndex()
    index.add_document(
        "direct", "Protein Function Prediction by Sequence Models",
        "Abstract: Protein function prediction can use sequence features. "
        "We evaluate the method on a held-out dataset.", "direct.txt")
    index.add_document(
        "related", "Protein Interface Prediction with Neural Networks",
        "Abstract: We predict protein interfaces from structure.",
        "related.txt")
    index.add_document(
        "lexical-distractor", "Function Approximation for Prediction",
        "Abstract: This paper studies function approximation and prediction.",
        "distractor.txt")
    index.add_document(
        "off-topic", "Quantum Biology and Coherence",
        "Abstract: We study coherence in biological systems.", "other.txt")
    rendered, fixture_documents = _render_research_list(
        index, "protein function prediction")
    require("Protein Function Prediction by Sequence Models" in rendered
            and "Protein Interface Prediction with Neural Networks" in rendered,
            f"direct and related paper hits were not both listed: {rendered}")
    require("Function Approximation for Prediction" not in rendered
            and "Quantum Biology" not in rendered,
            f"weak lexical hit leaked into the topical paper list: {rendered}")
    require("3/3 topic terms" in rendered and "2/3 topic terms" in rendered,
            f"title-topic coverage was not made explicit: {rendered}")
    require([item["document_id"] for item in fixture_documents]
            == ["direct", "related"],
            f"display order was not retained for follow-ups: {fixture_documents}")
    empty, empty_documents = _render_research_list(index, "quantum cryptobotany")
    require("couldn't find papers with enough" in empty,
            f"weak single-term matches were not rejected: {empty}")
    require(not empty_documents, "an empty topic result created follow-up context")

    source_model = PROJECT / "data" / "crms_project_model_academic.sqlite"
    source_sidecar = source_model.with_name(source_model.name + ".memories")
    with tempfile.TemporaryDirectory(prefix="crms-topic-paper-list-") as folder:
        root = Path(folder)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(source_sidecar / "research.sqlite"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "learned-rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
            "--math-session", str(root / "math.json"),
            "--translation-session", str(root / "translations.json"),
        ]
        result = subprocess.run(
            command,
            input=("Which papers discuss protein function prediction?\n"
                   "What does the second paper say?\n"
                   "Which papers discuss quantum cryptobotany?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=45)
        require(result.returncode == 0,
                f"chat exited {result.returncode}: {result.stderr}")
        require("Metamorphic Testing for Quality Assurance of Protein Function Prediction Tools"
                in result.stdout
                and "Deep Learning of High-Order Interactions for Protein Interface Prediction"
                in result.stdout,
                f"live corpus list omitted direct/related sources: {result.stdout}")
        require("Extractive summary for: Deep Learning of High-Order Interactions for Protein Interface Prediction"
                in result.stdout,
                f"ordinal follow-up did not summarize the second listed source: {result.stdout}")
        require("Background Independent Quantum Mechanics" not in result.stdout
                and "couldn't find papers with enough" in result.stdout,
                f"live corpus list admitted weakly related papers: {result.stdout}")

    print("topic paper-list retrieval diagnostic: PASS")
    print("direct and related title matches are separated; unrelated one-term hits abstain")


if __name__ == "__main__":
    main()
