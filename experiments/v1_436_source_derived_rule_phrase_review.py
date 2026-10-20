"""Propose a review-only procedure phrase from two indexed source origins.

The phrase is extracted from cited prose and paired with a separately cited
executable example. A proposal cannot mutate the rule store; Codex explicitly
reviews it before the existing teach path is invoked. This bounded experiment
does not claim open-vocabulary synonym discovery.
"""
from __future__ import annotations

import subprocess
import re
import shutil
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
from crms_package import (export_model_database, inspect_model_database,
                          model_database_research_stats)
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
NEGATED_SORT_SOURCE = (
    "negated-sort-instruction", "Controlled negated sort near miss",
    "https://example.invalid/negative-sort-fixture",
    "Do not sort values ascending; use descending order instead.",
)
NEGATED_REVERSE_SOURCE = (
    "negated-reverse-instruction", "Controlled negated reverse near miss",
    "https://example.invalid/negative-reverse-fixture",
    "Do not reverse the order of elements; preserve their original order.",
)
MENTIONED_SORT_SOURCE = (
    "mentioned-sort-phrase", "Controlled metalinguistic sort near miss",
    "https://example.invalid/mentioned-sort-fixture",
    "The note mentions the phrase 'sort values ascending', but gives no sorting instruction.",
)
MENTIONED_REVERSE_SOURCE = (
    "mentioned-reverse-phrase", "Controlled metalinguistic reverse near miss",
    "https://example.invalid/mentioned-reverse-fixture",
    "The phrase 'reverse the order of elements' is a label here, not a requested operation.",
)
UNRELATED_SORT_SOURCE = (
    "unrelated-sort-text", "Controlled unrelated sort passage",
    "https://example.invalid/unrelated-sort-fixture",
    "A table contains values from several experiments and reports their means.",
)
UNRELATED_REVERSE_SOURCE = (
    "unrelated-reverse-text", "Controlled unrelated reverse passage",
    "https://example.invalid/unrelated-reverse-fixture",
    "A sequence of measurements is shown with its original order preserved.",
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


def phrase_is_directly_negated(text: str, phrase: str) -> bool:
    """Reject a target phrase under a small, explicit negation window."""
    pattern = (r"\b(?:do\s+not|don't|never|must\s+not|should\s+not)\s+"
               r"(?:\w+\s+){0,2}" + re.escape(phrase) + r"\b")
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def phrase_starts_instruction(text: str, phrase: str) -> bool:
    """Require the cited sentence to state the operation, not mention it."""
    pattern = r"^\s*(?:please\s+)?" + re.escape(phrase) + r"\b"
    return re.match(pattern, text, flags=re.IGNORECASE) is not None


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
    if not phrase_starts_instruction(prose, "sort values ascending"):
        return None
    if phrase_is_directly_negated(prose, "sort values ascending"):
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


def propose_reverse_phrase(index: CRMSResearchIndex,
                           prose_source_id: str = NUMPY_FLIP_SOURCE[0]
                           ) -> RulePhraseCandidate | None:
    """Link a verbatim reverse phrase to a separately cited reverse example."""
    prose_hit = hit_for(index, prose_source_id, "reverse order elements")
    code_hit = hit_for(index, PYTHON_REVERSE_SOURCE[0],
                       "reversed range 1 10 2 9 7 5 3 1")
    if prose_hit is None or code_hit is None:
        return None
    prose = index.resolve_citation(index.citation(prose_hit))
    code = index.resolve_citation(index.citation(code_hit))
    phrase = "reverse the order of elements"
    if phrase not in " ".join(prose.casefold().split()):
        return None
    if not phrase_starts_instruction(prose, phrase):
        return None
    if phrase_is_directly_negated(prose, phrase):
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

        # Reintegrate the reviewed operation rule, its label/source lineage,
        # and the searchable source text into a portable SQLite model. The
        # clean-process check must start with that single file only.
        portable_knowledge = root / "portable-knowledge.sqlite"
        portable_rules = root / "portable-rules.sqlite"
        CRMSKnowledgeBase().save(portable_knowledge)
        restored.save(portable_rules)
        portable = root / "portable-model.sqlite"
        export_model_database(
            portable, knowledge=portable_knowledge, rules=portable_rules,
            research_index=root / "index.json")
        require({"knowledge", "rules"} <= inspect_model_database(portable).keys(),
                "portable model omitted its knowledge or accepted procedure rules")
        portable_sources = model_database_research_stats(portable)
        require(portable_sources is not None
                and portable_sources["documents"] == 4,
                f"portable model omitted source text: {portable_sources}")
        clean_dir = root / "clean-portable"
        clean_dir.mkdir()
        clean_model = clean_dir / "model.sqlite"
        shutil.copy2(portable, clean_model)
        for source_path in (portable_knowledge, portable_rules,
                            root / "index.json", root / "rules.json",
                            root / "knowledge.json", root / "math.json",
                            root / "translations.json"):
            source_path.unlink(missing_ok=True)
        require(list(clean_dir.iterdir()) == [clean_model],
                "clean chat did not start with only the copied model file")
        portable_chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--model-db", str(clean_model),
             "--dialogue-state", str(clean_dir / "dialogue.json"),
             "--candidate-session", str(clean_dir / "candidates.json"),
             "--rule-session", str(clean_dir / "rule-session.json"),
             "--math-session", str(clean_dir / "math-session.json"),
             "--translation-session", str(clean_dir / "translation-session.json")],
            input=(f"Write Python code to {candidate.phrase}\n/quit\n"),
            text=True, capture_output=True, cwd=clean_dir, timeout=120,
            check=False)
        require(portable_chat.returncode == 0,
                "copied model failed to start fresh chat: "
                f"{portable_chat.stderr}\n{portable_chat.stdout}")
        code_blocks = re.findall(
            r"```python\n(.*?)```", portable_chat.stdout, re.DOTALL)
        require(len(code_blocks) == 1
                and f"Generated Python for '{candidate.phrase}'"
                    in portable_chat.stdout,
                "copied model did not generate the learned operation in chat: "
                f"{portable_chat.stdout[-1200:]}")
        portable_namespace: dict[str, object] = {}
        exec(compile(code_blocks[0], "<portable-reviewed-sort>", "exec"),
             portable_namespace)
        require(all(portable_namespace["transform"](values) == expected
                    for values, expected in HELD_OUT),
                "code generated from the copied model failed held-out inputs")
        require(prose_citation in code_blocks[0]
                and candidate.phrase in code_blocks[0]
                and PYTHON_SOURCE[0] in code_blocks[0],
                "portable artifact lost phrase/source/example provenance")

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

        negative_sort_index = CRMSResearchIndex()
        negative_sort_index.add_document(
            PYTHON_SOURCE[0], PYTHON_SOURCE[1], PYTHON_SOURCE[3],
            PYTHON_SOURCE[2],
        )
        negative_sort_index.add_document(
            NEGATED_SORT_SOURCE[0], NEGATED_SORT_SOURCE[1],
            NEGATED_SORT_SOURCE[3], NEGATED_SORT_SOURCE[2],
        )
        require(propose_sort_phrase(
            negative_sort_index, NEGATED_SORT_SOURCE[0]) is None,
            "negated sort wording produced a positive source proposal")
        negative_reverse_index = CRMSResearchIndex()
        for document_id, title, location, text in (
                PYTHON_REVERSE_SOURCE, NEGATED_REVERSE_SOURCE):
            negative_reverse_index.add_document(
                document_id, title, text, location)
        require(propose_reverse_phrase(
            negative_reverse_index, NEGATED_REVERSE_SOURCE[0]) is None,
                "negated reverse wording produced a positive source proposal")

        # A source that merely quotes the phrase is not an instruction mapping;
        # unrelated prose should also abstain. Keep the examples explicit and
        # report the size of this deliberately small controlled negative set.
        negative_controls = (
            (PYTHON_SOURCE, MENTIONED_SORT_SOURCE,
             lambda idx: propose_sort_phrase(idx, MENTIONED_SORT_SOURCE[0]),
             "mentioned sort phrase"),
            (PYTHON_SOURCE, UNRELATED_SORT_SOURCE,
             lambda idx: propose_sort_phrase(idx, UNRELATED_SORT_SOURCE[0]),
             "unrelated sort text"),
            (PYTHON_REVERSE_SOURCE, MENTIONED_REVERSE_SOURCE,
             lambda idx: propose_reverse_phrase(idx, MENTIONED_REVERSE_SOURCE[0]),
             "mentioned reverse phrase"),
            (PYTHON_REVERSE_SOURCE, UNRELATED_REVERSE_SOURCE,
             lambda idx: propose_reverse_phrase(idx, UNRELATED_REVERSE_SOURCE[0]),
             "unrelated reverse text"),
        )
        for code_source, prose_source, proposer, label in negative_controls:
            control_index = CRMSResearchIndex()
            for document_id, title, location, text in (code_source, prose_source):
                control_index.add_document(document_id, title, text, location)
            require(proposer(control_index) is None,
                    f"{label} produced a positive source proposal")

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
    print("copied SQLite model generated an independently checked artifact: PASS")
    print("descending, negated, mentioned-phrase, unrelated, tampered, and "
          "single-origin controls rejected: PASS")
    print("controlled source-text controls: 0 false candidates in 7 cases")
    print("limitation: phrase and source association used a bounded cue rule; Codex reviewed before teaching")


if __name__ == "__main__":
    main()
