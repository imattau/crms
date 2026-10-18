"""Check date-ordered source research requests and portable chat routing."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_latest_research_request
from crms_import_arxiv import search_arxiv
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(_natural_latest_research_request(
        "What is the latest research in machine learning in this corpus?")
        == "machine learning", "did not extract the corpus topic")
    require(_natural_latest_research_request(
        "What are the newest papers about graph theory?") == "graph theory",
        "did not extract a paper topic")
    require(_natural_latest_research_request("What is the latest research?")
            == "", "topic-free request should request latest dated sources")

    requested: dict[str, str] = {}

    def fetch(url: str, *, max_bytes: int) -> bytes:
        del max_bytes
        requested.update({key: values[0] for key, values
                          in parse_qs(urlparse(url).query).items()})
        return (b'<feed xmlns="http://www.w3.org/2005/Atom" />')

    search_arxiv("cat:cs.AI", sort_by="submittedDate", fetch=fetch)
    require(requested.get("sortBy") == "submittedDate"
            and requested.get("sortOrder") == "descending",
            f"arXiv submission-date ordering was not requested: {requested}")

    with tempfile.TemporaryDirectory() as directory:
        index = CRMSSQLiteResearchIndex(Path(directory) / "research.sqlite")
        index.add_document(
            "recent", "Recent machine learning paper",
            "Published: 2025-02-03T12:00:00Z\n"
            "Abstract: This paper studies machine learning systems.",
            "https://example.test/recent")
        index.add_document(
            "older", "Older machine learning paper",
            "Published: 2023-11-02T12:00:00Z\n"
            "Abstract: This paper studies machine learning systems.",
            "https://example.test/older")
        index.add_document(
            "partial", "Machine paper without the second topic term",
            "Published: 2026-01-01T12:00:00Z\n"
            "Abstract: This paper studies machine systems.",
            "https://example.test/partial")
        index.add_document(
            "undated", "Undated machine learning paper",
            "Abstract: This paper studies machine learning systems.",
            "https://example.test/undated")
        latest = index.search_latest("machine learning", limit=5)
        require([item.hit.document_id for item in latest] == ["recent", "older"],
                f"date sort or all-term matching failed: {latest}")
        require(index.citation(latest[0].hit).startswith("recent#sha256="),
                "latest hit citation did not verify")
        all_recent = index.search_latest("", limit=1)
        require(len(all_recent) == 1
                and all_recent[0].publication_date == "2026-01-01",
                f"topic-free latest search did not use corpus dates: {all_recent}")
        index.close()

    index = (PROJECT / "data" / "crms_project_model_academic.sqlite.memories"
             / "research.sqlite")
    require(index.is_file(), f"large-corpus research index is missing: {index}")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index),
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
        run = subprocess.run(
            command,
            input=("What is the latest research in machine learning in this corpus?\n"
                   "Can you explain the result in simpler terms?\n"
                   "What is the main result of On the cop number of toroidal graphs?\n"
                   "Can you explain the result in simpler terms?\n"
                   "What is 2 + 3?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        require("2026-10-15" in run.stdout
                and "Controlling the False Discovery Rate via Model-Agnostic Importance Measures"
                in run.stdout
                and "Time to Fake It: Continual Machine Learning Intensifies Unfairness"
                in run.stdout
                and "PocketTSLM" not in run.stdout
                and "grounded cardinal value" not in run.stdout,
                f"latest-source question did not use dated research evidence: {run.stdout}")
        require("CRMS> 5 (exact arithmetic" in run.stdout,
                f"research routing intercepted an arithmetic question: {run.stdout}")
        require("I don't have a verified language rule to paraphrase this result yet."
                in run.stdout
                and "We show that the cop number of toroidal graphs is at most 3."
                in run.stdout
                and "PocketTSLM" not in run.stdout
                and "Learning to Explain: Answering Why-Questions" not in run.stdout,
                f"research follow-up drifted from the cited result: {run.stdout}")

        summary = subprocess.run(
            command,
            input=("/summarize the paper on the cop number of toroidal graphs\n"
                   "Show more sentences\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30).stdout
        marker = "Extractive summary for: the paper on the cop number of toroidal graphs"
        require(marker in summary
                and "arxiv:1904.07946v3" in summary
                and "Chromatic Number of Joins of Signed Graphs" not in summary,
                f"paper-bounded summary included a neighboring paper: {summary}")

        ambiguous = subprocess.run(
            command,
            input="/summarize the paper about Python\n/quit\n",
            text=True, capture_output=True, check=True, timeout=30).stdout
        require("Give me more of the paper's title." in ambiguous
                and "Extractive summary for:" not in ambiguous,
                f"ambiguous paper request was summarized without clarification: {ambiguous}")

    print("latest dated research and portable chat routing: PASS")


if __name__ == "__main__":
    main()
