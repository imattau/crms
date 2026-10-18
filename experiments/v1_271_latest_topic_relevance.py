"""Rank recent-topic results by topical focus before date ordering."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _render_latest_research
from crms_research import CRMSResearchIndex, CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document(
        "new-broad-mention", "Clinical Event Graphs for Risk Prediction",
        "Published: 2026-10-16T00:00:00Z\n"
        "Abstract: Clinical events form a temporal graph. The model predicts "
        "risk from patient histories. We compare it with graph neural networks.",
        "broad.txt")
    index.add_document(
        "focused-newer", "Graph Neural Networks for Clinical Prediction",
        "Published: 2026-10-15T00:00:00Z\n"
        "Abstract: Graph neural networks learn from graph-structured data.",
        "focused-newer.txt")
    index.add_document(
        "focused-older", "Graph Neural Network Methods",
        "Published: 2026-10-14T00:00:00Z\n"
        "Abstract: We study graph neural networks in detail.",
        "focused-older.txt")
    rendered, _evidence, documents = _render_latest_research(
        index, "graph neural networks")
    require(rendered.index("focused-newer") < rendered.index("new-broad-mention")
            and "Recent related mentions" in rendered,
            f"new broad mention outranked focused topic papers: {rendered}")
    require([item["document_id"] for item in documents] == [
                "focused-newer", "focused-older", "new-broad-mention"],
            f"display-order context did not retain relevance tiers: {documents}")

    model_sidecar = PROJECT / "data" / "crms_project_model_academic.sqlite.memories" / "research.sqlite"
    real = CRMSSQLiteResearchIndex(model_sidecar)
    try:
        graph_text, _evidence, graph_docs = _render_latest_research(
            real, "graph neural networks")
        titles = [item["title"] for item in graph_docs]
        require(titles == [
                    "MAEM: Mitigating Recency Bias via a Replay-Free, Capacity-Controlled Dynamic Mixture of Experts for Class-Incremental Graph Learning",
                    "Graph Additive Models disentangling feature, topology, and interactions",
                    "GraphBEAT: Graph-based Bucketized Event Aggregation Over Time for Early Risk Stratification of Gastrointestinal Cancers"],
                f"real corpus did not rank focused latest papers first: {titles}")
        require("Recent related mentions" in graph_text
                and "GraphBEAT" in graph_text,
                f"recent broad mention was not labeled as related: {graph_text}")
        ml_text, _evidence, _ml_docs = _render_latest_research(real, "machine learning")
        require("Controlling the False Discovery Rate" in ml_text
                and "Time to Fake It" in ml_text
                and "PocketTSLM" not in ml_text,
                f"machine-learning list retained a weak topical match: {ml_text}")
    finally:
        real.close()

    print("latest research topicality diagnostic: PASS")
    print("focused title/opening evidence ranks before later abstract mentions; recency is preserved within each group")


if __name__ == "__main__":
    main()
