"""Learn a numeric sorting rule from cited Python and NumPy doctests.

The examples are small excerpts from official documentation pages. This tests
source attribution and bounded transfer; the two training examples are not a
representative measure of coding skill or independent user evaluation.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _citation_contains_integer_pair
from crms_codegen import generate_python, show_generated_code_evidence
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex, CRMSSQLiteResearchIndex
from crms_translation import CRMSTranslation


PYTHON_SORT_DOC = ">>> sorted([5, 2, 3, 1, 4])\n[1, 2, 3, 4, 5]"
NUMPY_SORT_DOC = (
    ">>> a = np.array([2, 1, 5, 3, 7, 4, 6, 8])\n"
    ">>> np.sort(a)\n"
    "array([1, 2, 3, 4, 5, 6, 7, 8])")
PYTHON_REVERSE_DOC = (
    ">>> for i in reversed(range(1, 10, 2)):\n"
    "...     print(i)\n"
    "...\n"
    "9\n7\n5\n3\n1")
TRAINING = (
    ("python-sorting-howto", "Python Sorting HOWTO",
     "https://docs.python.org/3/howto/sorting.html", PYTHON_SORT_DOC,
     [5, 2, 3, 1, 4], [1, 2, 3, 4, 5]),
    ("numpy-sorting-basics", "NumPy: absolute basics",
     "https://numpy.org/doc/stable/user/absolute_beginners.html",
     NUMPY_SORT_DOC, [2, 1, 5, 3, 7, 4, 6, 8],
     [1, 2, 3, 4, 5, 6, 7, 8]),
)
HELD_OUT = (
    ([12, -3, 7, 0], [-3, 0, 7, 12]),
    ([4, 4, -8, 2, 0], [-8, 0, 2, 4, 4]),
    ([], []),
)
TEACHER_CONTRASTS = (
    ([1, -1, 1], [-1, 1, 1]),
    ([0, 1, -1], [-1, 0, 1]),
)
CRLF_DOCTEST_DOCUMENT = (
    "Example follows.\r\n\r\n"
    ">>> sorted([3, 1, 2])\r\n[1, 2, 3]\r\n \t\r\n"
    "This paragraph is outside the example.")
CRLF_DOCTEST_BLOCK = ">>> sorted([3, 1, 2])\r\n[1, 2, 3]"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def citation_for(index: CRMSResearchIndex, document_id: str, title: str,
                 location: str, text: str, *, query: str | None = None
                 ) -> str:
    index.add_document(document_id, title, text, location)
    search_query = query or ("sorted" if "sorted(" in text else "sort")
    hits = index.search(search_query, limit=10, context_chars=0)
    hit = next((hit for hit in hits if hit.document_id == document_id), None)
    require(hit is not None,
            f"search did not retrieve the doctest in {document_id}")
    citation = index.citation(hit)
    require(index.resolve_citation(citation) == text,
            f"{document_id} citation is not the exact code example")
    return citation


def check_sqlite_doctest_citations(path: Path) -> None:
    index = CRMSSQLiteResearchIndex(path)
    try:
        for document_id, title, location, text, *_ in TRAINING:
            index.add_document(document_id, title, text, location)
        for document_id, _title, _location, text, *_ in TRAINING:
            query = "sorted" if "sorted(" in text else "sort"
            hits = index.search(query, limit=10, context_chars=0)
            hit = next((hit for hit in hits
                        if hit.document_id == document_id), None)
            require(hit is not None,
                    f"SQLite search missed doctest {document_id}")
            citation = index.citation(hit)
            require(index.resolve_citation(citation) == text,
                    f"SQLite citation did not cover the full doctest: "
                    f"{document_id}")
        check_python_reverse_citation(index)
        check_crlf_doctest_citation(index)
    finally:
        index.close()


def check_python_reverse_citation(index: CRMSResearchIndex) -> None:
    citation_for(
        index, "python-reversed-range", "Python Tutorial: Data Structures",
        "https://docs.python.org/3/tutorial/datastructures.html",
        PYTHON_REVERSE_DOC, query="reversed")


def check_crlf_doctest_citation(index: CRMSResearchIndex) -> None:
    index.add_document("crlf-doctest", "CRLF doctest",
                       CRLF_DOCTEST_DOCUMENT)
    hits = index.search("sorted", limit=10, context_chars=0)
    hit = next((hit for hit in hits if hit.document_id == "crlf-doctest"), None)
    require(hit is not None, "search missed the CRLF doctest")
    require(index.resolve_citation(index.citation(hit)) == CRLF_DOCTEST_BLOCK,
            "CRLF/whitespace separator did not preserve the exact doctest")


def launch(root: Path, lines: list[str]) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--rules", str(root / "rules.json"),
        "--math", str(root / "math.json"),
        "--knowledge", str(root / "knowledge.json"),
        "--translations", str(root / "translations.json"),
        "--index", str(root / "index.json"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
    ]
    return subprocess.run(
        command, input="\n".join([*lines, "/quit", ""]), text=True,
        capture_output=True, cwd=root, timeout=120, check=False)


def main() -> None:
    require(_citation_contains_integer_pair(
        PYTHON_SORT_DOC, [5, 2, 3, 1, 4], [1, 2, 3, 4, 5]),
        "plain Python doctest was not recognized as a cited list pair")
    require(_citation_contains_integer_pair(
        NUMPY_SORT_DOC, [2, 1, 5, 3, 7, 4, 6, 8],
        [1, 2, 3, 4, 5, 6, 7, 8]),
        "NumPy variable-backed doctest was not recognized as a cited pair")
    require(_citation_contains_integer_pair(
        ">>> np.unique([3, 1, 3, 2])\narray([1, 2, 3])",
        [3, 1, 3, 2], [1, 2, 3]),
        "NumPy unique doctest was not recognized")
    require(_citation_contains_integer_pair(
        ">>> list(reversed([3, 1, 2]))\n[2, 1, 3]",
        [3, 1, 2], [2, 1, 3]),
        "Python reverse doctest was not recognized")
    require(_citation_contains_integer_pair(
        ">>> np.flip(np.array([3, 1, 2]))\narray([2, 1, 3])",
        [3, 1, 2], [2, 1, 3]),
        "NumPy flip doctest was not recognized")
    require(_citation_contains_integer_pair(
        PYTHON_REVERSE_DOC, [1, 3, 5, 7, 9], [9, 7, 5, 3, 1]),
        "documented reversed-range loop was not recognized")
    require(not _citation_contains_integer_pair(
        PYTHON_REVERSE_DOC.replace("9\n7\n5", "9\n8\n5"),
        [1, 3, 5, 7, 9], [9, 7, 5, 3, 1]),
        "reversed-range validator trusted a tampered output")
    require(not _citation_contains_integer_pair(
        PYTHON_REVERSE_DOC.replace("print(i)", "print(i + 1)"),
        [1, 3, 5, 7, 9], [9, 7, 5, 3, 1]),
        "reversed-range validator accepted an unsupported loop body")
    require(not _citation_contains_integer_pair(
        ">>> for i in reversed(range(0, 1001)):\n"
        "...     print(i)\n...\n1000",
        list(range(1001)), list(reversed(range(1001)))),
        "reversed-range validator exceeded its bounded iteration limit")
    require(not _citation_contains_integer_pair(
        ">>> list(reversed([3, 1, 2], ignored=True))\n[2, 1, 3]",
        [3, 1, 2], [2, 1, 3]),
        "reverse parser accepted a call with unsupported arguments")
    require(not _citation_contains_integer_pair(
        ">>> a = np.array([3, 1, 2])\n>>> a = None\n"
        ">>> np.sort(a)\narray([1, 2, 3])",
        [3, 1, 2], [1, 2, 3]),
        "doctest parser reused an overwritten variable value")
    wrong_result = PYTHON_SORT_DOC.replace(
        "[1, 2, 3, 4, 5]", "[5, 4, 3, 2, 1]")
    require(not _citation_contains_integer_pair(
        wrong_result, [5, 2, 3, 1, 4], [5, 4, 3, 2, 1]),
        "citation validator trusted an output inconsistent with the code")

    with tempfile.TemporaryDirectory(prefix="crms-cited-doctest-") as folder:
        root = Path(folder)
        check_sqlite_doctest_citations(root / "research.sqlite3")
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSTranslation().save(root / "translations.json")
        index = CRMSResearchIndex()
        training_citations = []
        teaching_lines = []
        for (document_id, title, location, text, inputs,
             outputs) in TRAINING:
            citation = citation_for(index, document_id, title, location, text)
            training_citations.append(citation)
            teaching_lines.append(
                f"/teach-rule sort the numbers|"
                f"{','.join(map(str, inputs))}|"
                f"{','.join(map(str, outputs))}|{citation}")
        check_python_reverse_citation(index)
        check_crlf_doctest_citation(index)
        index.save(root / "index.json")

        # Both cited documentation examples are positive-only, so the learner
        # correctly asks for a contrastive example before licensing a rule.
        # These contrastive examples are explicitly teacher-supplied and
        # unattributed.
        teaching_lines.extend(
            f"/teach-rule sort the numbers|"
            f"{','.join(map(str, inputs))}|"
            f"{','.join(map(str, outputs))}"
            for inputs, outputs in TEACHER_CONTRASTS)
        request = "Write Python code to sort the numbers"
        run = launch(root, [*teaching_lines, request,
                            "Show examples for that code"])
        require(run.returncode == 0,
                f"chat exited {run.returncode}: {run.stderr}")
        require("Rule learning status: learned." in run.stdout
                and "Generated Python for 'sort the numbers'" in run.stdout,
                f"chat did not learn and generate from cited doctests: "
                f"{run.stdout[-2400:]!r}")
        require("The cited text demonstrates this exact numeric pair" in run.stdout,
                "chat did not state what citation verification established")

        rules = CRMSModel(root / "rules.json", max_workers=1)
        require(rules.example_documents("sort the numbers")
                == ["numpy-sorting-basics", "python-sorting-howto"],
                "learned rule did not retain both documentation sources")
        records = rules.example_records("sort the numbers")
        require(any(record.get("source_id") is None for record in records)
                and set(rules.example_sources("sort the numbers"))
                == set(training_citations),
                "teacher contrast or source citations lost their attribution status")
        for values, expected in HELD_OUT:
            prediction = rules.predict("sort the numbers", values)
            require(prediction.status == "ok" and prediction.output == expected,
                    f"held-out values did not transfer correctly: {prediction!r}")

        artifact = generate_python(rules, "sort the numbers")
        require(artifact is not None, "learned rule produced no code artifact")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<cited-doctest-sort>", "exec"), namespace)
        transform = namespace["transform"]
        require(all(transform(values) == expected for values, expected in HELD_OUT)
                and namespace["validate_examples"](),
                "standalone generated code failed held-out validation")
        provenance = namespace["CRMS_PROVENANCE"]["examples"]
        artifact_sources = {row["source_id"] for row in provenance
                            if row["source_id"] is not None}
        require(artifact_sources == set(training_citations),
                f"generated artifact citations differ: {artifact_sources!r} "
                f"!= {set(training_citations)!r}")
        evidence = show_generated_code_evidence(artifact)
        require(all(citation in evidence for citation in training_citations),
                "user-facing artifact evidence omitted a source citation")

        unsupported = rules.predict("rotate the numbers", [3, 1, 2])
        require(unsupported.status != "ok",
                "an unsupported operation was licensed by the sort examples")

    print("Python and NumPy doctest citations verified without executing source: PASS")
    print("official reversed-range example is verified and retrievable: PASS")
    print("in-memory and SQLite search cite complete doctest blocks: PASS")
    print("chat learned sort from two cited docs plus two teacher contrasts: PASS")
    print("three held-out lists and generated Python passed independent checks: PASS")
    print("unsupported rotation remained unlicensed: PASS")
    print("coverage is one operation, two cited docs from two publishers: LIMITATION")


if __name__ == "__main__":
    main()
