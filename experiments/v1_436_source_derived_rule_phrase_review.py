"""Propose a review-only procedure phrase from two indexed source origins.

The phrase is extracted from cited prose and paired with a separately cited
executable example. A proposal cannot mutate the rule store; Codex explicitly
reviews it before the existing teach path is invoked. This bounded experiment
does not claim open-vocabulary synonym discovery.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _citation_contains_integer_pair
from crms_codegen import generate_python
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation

PYTHON_SOURCE = (
    "python-sorting-howto", "Python Sorting HOWTO",
    "https://docs.python.org/3/howto/sorting.html",
    "A simple ascending sort is very easy: just call the sorted() function. "
    "It returns a new sorted list:\n\n"
    ">>> sorted([5, 2, 3, 1, 4])\n[1, 2, 3, 4, 5]",
)
PANDAS_SOURCE = (
    "pandas-series-sort-values", "pandas.Series.sort_values",
    "https://pandas.pydata.org/docs/reference/api/pandas.Series.sort_values.html",
    "Sort values ascending order (default behavior).",
)
PYTHON_REVERSE_SOURCE = (
    "python-reversed-range", "Python Tutorial: Data Structures",
    "https://docs.python.org/3/tutorial/datastructures.html",
    ">>> for i in reversed(range(1, 10, 2)):\n"
    "...     print(i)\n...\n9\n7\n5\n3\n1",
)
NUMPY_FLIP_SOURCE = (
    "numpy-flip", "NumPy: numpy.flip",
    "https://numpy.org/doc/stable/reference/generated/numpy.flip.html",
    "Reverse the order of elements in an array along the given axis.",
)
PANDAS_DESCENDING_SOURCE = (
    "pandas-series-descending", "pandas.Series.sort_values descending",
    PANDAS_SOURCE[2], "Sort values descending order (default behavior).",
)
TRAINING_PAIR = ([5, 2, 3, 1, 4], [1, 2, 3, 4, 5])
REVERSE_PAIR = ([1, 3, 5, 7, 9], [9, 7, 5, 3, 1])
REVIEW_CONTRASTS = (
    ([1, -1, 1], [-1, 1, 1]),
    ([0, 1, -1], [-1, 0, 1]),
)
REVERSE_REVIEW_CONTRASTS = (
    ([3, 1, 2], [2, 1, 3]),
    ([4, -1, 7], [7, -1, 4]),
    ([0, 5, -2, 8], [8, -2, 5, 0]),
    ([-5, 9], [9, -5]),
    ([12], [12]),
    ([], []),
    ([0, 0], [0, 0]),
)
HELD_OUT = (
    ([12, -3, 7, 0], [-3, 0, 7, 12]),
    ([4, 4, -8, 2, 0], [-8, 0, 2, 4, 4]),
    ([], []),
)
REVERSE_HELD_OUT = (
    ([4, -1, 7, 0], [0, 7, -1, 4]),
    ([2, 2, -3, 8], [8, -3, 2, 2]),
    ([9, 1, 3, 6], [6, 3, 1, 9]),
)


@dataclass(frozen=True)
class AlignmentEvidence:
    origin: str
    source_id: str
    prose_citation: str | None
    code_citation: str | None
    surface_text: str
    input_values: tuple[int, ...] | None = None
    output_values: tuple[int, ...] | None = None


@dataclass(frozen=True)
class RulePhraseCandidate:
    phrase: str
    operation: str
    evidence: tuple[AlignmentEvidence, ...]
    status: str = "needs_review"
    review_required: bool = True


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def hit_for(index: CRMSResearchIndex, document_id: str,
            query: str):
    return next((hit for hit in index.search(
        query, limit=30, context_chars=0)
        if hit.document_id == document_id), None)


def propose_sort_phrase(index: CRMSResearchIndex,
                        prose_source_id: str = PANDAS_SOURCE[0]
                        ) -> RulePhraseCandidate | None:
    """Link a narrow source phrase to a separately cited sorting doctest."""
    prose_hit = hit_for(index, prose_source_id, "sort values ascending")
    code_hit = hit_for(index, PYTHON_SOURCE[0], "sorted 5 2 3 1 4 1 2 3 4 5")
    if prose_hit is None or code_hit is None:
        return None
    prose = index.resolve_citation(index.citation(prose_hit))
    code = index.resolve_citation(index.citation(code_hit))
    normalized = " ".join(prose.casefold().split())
    if "sort values ascending" not in normalized:
        return None
    if not _citation_contains_integer_pair(code, *TRAINING_PAIR):
        return None
    input_values, output_values = TRAINING_PAIR
    if output_values != sorted(input_values):
        return None
    prose_origin = urlparse(prose_hit.location or "").hostname or prose_hit.document_id
    code_origin = urlparse(code_hit.location or "").hostname or code_hit.document_id
    if prose_origin == code_origin:
        return None
    evidence = (
        AlignmentEvidence(
            prose_origin, prose_hit.document_id,
            index.citation(prose_hit), None, prose,
        ),
        AlignmentEvidence(
            code_origin, code_hit.document_id,
            None, index.citation(code_hit), code,
            tuple(input_values), tuple(output_values),
        ),
    )
    return RulePhraseCandidate(
        phrase="sort values ascending", operation="sort", evidence=evidence)


def propose_reverse_phrase(index: CRMSResearchIndex
                           ) -> RulePhraseCandidate | None:
    """Link a verbatim reverse phrase to a separately cited reverse example."""
    prose_hit = hit_for(index, NUMPY_FLIP_SOURCE[0], "reverse order elements")
    code_hit = hit_for(index, PYTHON_REVERSE_SOURCE[0],
                       "reversed range 1 10 2 9 7 5 3 1")
    if prose_hit is None or code_hit is None:
        return None
    prose = index.resolve_citation(index.citation(prose_hit))
    code = index.resolve_citation(index.citation(code_hit))
    phrase = "reverse the order of elements"
    if phrase not in " ".join(prose.casefold().split()):
        return None
    if not _citation_contains_integer_pair(code, *REVERSE_PAIR):
        return None
    input_values, output_values = REVERSE_PAIR
    if output_values != list(reversed(input_values)):
        return None
    prose_origin = urlparse(prose_hit.location or "").hostname or prose_hit.document_id
    code_origin = urlparse(code_hit.location or "").hostname or code_hit.document_id
    if prose_origin == code_origin:
        return None
    return RulePhraseCandidate(
        phrase=phrase,
        operation="reverse",
        evidence=(
            AlignmentEvidence(
                prose_origin, prose_hit.document_id,
                index.citation(prose_hit), None, prose,
            ),
            AlignmentEvidence(
                code_origin, code_hit.document_id,
                None, index.citation(code_hit), code,
                tuple(input_values), tuple(output_values),
            ),
        ),
    )


def launch_chat(root: Path, lines: list[str]):
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
    with tempfile.TemporaryDirectory(prefix="crms-source-rule-proposal-") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        sources = (PYTHON_SOURCE, PANDAS_SOURCE,
                   PYTHON_REVERSE_SOURCE, NUMPY_FLIP_SOURCE)
        for document_id, title, location, text in sources:
            index.add_document(document_id, title, text, location)

        python_hit = hit_for(index, PYTHON_SOURCE[0], "sorted 5 2 3 1 4 1 2 3 4 5")
        pandas_hit = hit_for(index, PANDAS_SOURCE[0], "sort values ascending")
        require(python_hit is not None and pandas_hit is not None,
                "retrieval missed one of the two primary source spans")
        code_citation = index.citation(python_hit)
        prose_citation = index.citation(pandas_hit)
        require(index.resolve_citation(code_citation)
                == ">>> sorted([5, 2, 3, 1, 4])\n[1, 2, 3, 4, 5]",
                "executable source citation did not resolve exactly")
        require(index.resolve_citation(prose_citation)
                == PANDAS_SOURCE[3],
                "instruction phrase citation did not resolve exactly")
        reverse_code_hit = hit_for(
            index, PYTHON_REVERSE_SOURCE[0],
            "reversed range 1 10 2 9 7 5 3 1")
        numpy_prose_hit = hit_for(
            index, NUMPY_FLIP_SOURCE[0], "reverse order elements")
        require(reverse_code_hit is not None and numpy_prose_hit is not None,
                "retrieval missed the reverse phrase or code example")
        reverse_code_citation = index.citation(reverse_code_hit)
        reverse_prose_citation = index.citation(numpy_prose_hit)
        require(index.resolve_citation(reverse_code_citation)
                == PYTHON_REVERSE_SOURCE[3]
                and _citation_contains_integer_pair(
                    index.resolve_citation(reverse_code_citation), *REVERSE_PAIR),
                "reverse doctest citation failed exact pair verification")
        require(index.resolve_citation(reverse_prose_citation)
                == NUMPY_FLIP_SOURCE[3],
                "reverse phrase citation did not resolve exactly")

        candidate = propose_sort_phrase(index)
        reverse_candidate = propose_reverse_phrase(index)
        require(candidate is not None,
                "source text and example did not produce a review proposal")
        require(reverse_candidate is not None,
                "reverse source text and example did not produce a proposal")
        require(candidate.status == "needs_review" and candidate.review_required,
                "source-derived mapping was not review-gated")
        require(candidate.phrase == "sort values ascending"
                and candidate.operation == "sort",
                f"wrong proposed alignment: {candidate!r}")
        require(reverse_candidate.status == "needs_review"
                and reverse_candidate.review_required
                and reverse_candidate.phrase == "reverse the order of elements"
                and reverse_candidate.operation == "reverse",
                f"wrong reverse proposal: {reverse_candidate!r}")
        require({item.origin for item in candidate.evidence}
                == {"docs.python.org", "pandas.pydata.org"},
                "proposal did not retain its distinct source origins")
        require({item.origin for item in reverse_candidate.evidence}
                == {"docs.python.org", "numpy.org"},
                "reverse proposal did not retain distinct source origins")
        require(all(item.prose_citation or item.code_citation
                    for item in candidate.evidence),
                "proposal evidence lost its exact citations")

        rules = CRMSModel(max_workers=1)
        before = rules.list_rules()
        # Proposal is inert. Only the explicit review action below calls teach.
        require(candidate.phrase not in before,
                "proposal was written to the rule store before review")
        require(reverse_candidate.phrase not in before,
                "reverse proposal was written before review")
        rules.save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSTranslation().save(root / "translations.json")
        index.save(root / "index.json")

        # Codex reviews the exact prose and executable citations, accepts the
        # proposed phrase-to-sort mapping, and supplies two explicit contrasts.
        review_labeler = "codex:reviewed-source-alignment"
        teaching = [
            f"/teach-rule {candidate.phrase}|"
            f"{','.join(map(str, TRAINING_PAIR[0]))}|"
            f"{','.join(map(str, TRAINING_PAIR[1]))}|"
            f"{code_citation}|{review_labeler}|{prose_citation}"
        ]
        teaching.append(
            f"/teach-rule {reverse_candidate.phrase}|"
            f"{','.join(map(str, REVERSE_PAIR[0]))}|"
            f"{','.join(map(str, REVERSE_PAIR[1]))}|"
            f"{reverse_code_citation}|{review_labeler}|{reverse_prose_citation}"
        )
        teaching.extend(
            f"/teach-rule {candidate.phrase}|"
            f"{','.join(map(str, values))}|{','.join(map(str, output))}||"
            f"{review_labeler}"
            for values, output in REVIEW_CONTRASTS)
        teaching.extend(
            f"/teach-rule {reverse_candidate.phrase}|"
            f"{','.join(map(str, values))}|{','.join(map(str, output))}||"
            f"{review_labeler}"
            for values, output in REVERSE_REVIEW_CONTRASTS)
        chat_run = launch_chat(
            # Rule teaching may leave an optional next contrast pending after
            # the accepted examples. Close that prompt explicitly before
            # switching the evaluation to code generation; otherwise the next
            # request is interpreted as an answer to the contrast.
            root, [*teaching, "/cancel-rule",
                  f"Write Python code to {candidate.phrase}",
                  f"Write Python code to {reverse_candidate.phrase}",
                  "Show examples for that code"])
        require(chat_run.returncode == 0
                and "Could not teach rule:" not in chat_run.stdout
                and f"Generated Python for '{candidate.phrase}'"
                in chat_run.stdout
                and f"Generated Python for '{reverse_candidate.phrase}'"
                in chat_run.stdout,
                "reviewed source proposal did not learn through chat: "
                + chat_run.stdout[-1800:])
        restored = CRMSModel(root / "rules.json", max_workers=1)
        require(restored.example_documents(candidate.phrase)
                == [PYTHON_SOURCE[0]],
                "accepted source-pair citation did not survive reload")
        require(restored.example_documents(reverse_candidate.phrase)
                == [PYTHON_REVERSE_SOURCE[0]],
                "accepted reverse source-pair citation did not survive reload")
        records = restored.example_records(candidate.phrase)
        require(records[0].get("instruction_source_id") == prose_citation
                and all(record.get("labeler_id")
                        == "codex:reviewed-source-alignment"
                        for record in records),
                "reviewer and phrase-source provenance did not survive reload")
        reverse_records = restored.example_records(reverse_candidate.phrase)
        require(reverse_records[0].get("instruction_source_id")
                == reverse_prose_citation
                and all(record.get("labeler_id") == review_labeler
                        for record in reverse_records),
                "reverse proposal lost reviewer or prose provenance")

        for values, expected in HELD_OUT:
            prediction = restored.predict(candidate.phrase, values)
            require(prediction.status == "ok" and prediction.output == expected,
                    f"reviewed rule failed held-out input {values}: {prediction!r}")
        artifact = generate_python(restored, candidate.phrase)
        require(artifact is not None,
                "reviewed source proposal generated no code artifact")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<source-reviewed-sort>", "exec"),
             namespace)
        require(all(namespace["transform"](values) == expected
                    for values, expected in HELD_OUT),
                "generated artifact failed the held-out lists")
        reverse_artifact = generate_python(restored, reverse_candidate.phrase)
        require(reverse_artifact is not None,
                "reviewed reverse proposal generated no artifact")
        reverse_namespace: dict[str, object] = {}
        exec(compile(reverse_artifact.source, "<source-reviewed-reverse>", "exec"),
             reverse_namespace)
        require(all(reverse_namespace["transform"](values) == expected
                    for values, expected in REVERSE_HELD_OUT),
                "generated reverse artifact failed held-out lists")
        require(restored.predict("sort values descending", [3, 1, 2]).status
                != "ok",
                "ascending candidate incorrectly licensed descending wording")
        descending_index = CRMSResearchIndex()
        descending_index.add_document(
            PYTHON_SOURCE[0], PYTHON_SOURCE[1], PYTHON_SOURCE[3],
            PYTHON_SOURCE[2],
        )
        descending_index.add_document(
            PANDAS_DESCENDING_SOURCE[0], PANDAS_DESCENDING_SOURCE[1],
            PANDAS_DESCENDING_SOURCE[3], PANDAS_DESCENDING_SOURCE[2],
        )
        require(propose_sort_phrase(
            descending_index, PANDAS_DESCENDING_SOURCE[0]) is None,
            "descending prose was accepted as ascending instruction evidence")

        # Bad code output cannot enter the candidate, even when its prose cue is
        # identical. A single source cannot pass the independent-origin gate.
        bad_index = CRMSResearchIndex()
        bad_index.add_document(
            PYTHON_SOURCE[0], PYTHON_SOURCE[1],
            PYTHON_SOURCE[3].replace("[1, 2, 3, 4, 5]", "[5, 4, 3, 2, 1]"),
            PYTHON_SOURCE[2],
        )
        bad_index.add_document(
            PANDAS_SOURCE[0], PANDAS_SOURCE[1], PANDAS_SOURCE[3],
            PANDAS_SOURCE[2],
        )
        require(propose_sort_phrase(bad_index) is None,
                "tampered code pair produced a source alignment proposal")
        one_origin_index = CRMSResearchIndex()
        one_origin_index.add_document(
            PYTHON_SOURCE[0], PYTHON_SOURCE[1], PYTHON_SOURCE[3],
            PYTHON_SOURCE[2],
        )
        one_origin_index.add_document(
            PANDAS_SOURCE[0], PANDAS_SOURCE[1], PANDAS_SOURCE[3],
            "https://docs.python.org/3/library/pandas-reference-fixture.html",
        )
        require(propose_sort_phrase(one_origin_index) is None,
                "same-origin documents passed the independent-origin gate")

    print("two-origin prose/code evidence proposed a phrase mapping: PASS")
    print("proposal remained review-only and preserved exact citations: PASS")
    print("reviewed rule learned, persisted, and passed three held-out lists: PASS")
    print("descending wording and tampered/single-origin evidence were rejected: PASS")
    print("limitation: phrase and source association used a bounded cue rule; Codex reviewed before teaching")


if __name__ == "__main__":
    main()
