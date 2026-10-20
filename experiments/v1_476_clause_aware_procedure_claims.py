"""Check source claim boundaries and the fresh-chat review-only surface."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
import subprocess
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


PASSAGES = (
    {
        "id": "numpy-out-array",
        "title": "numpy.add API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.add.html",
        "text": "At locations where the condition is True, the `out` array "
                "will be set to the ufunc result.",
        "expected": (("the `out` array", "be set to the ufunc result",
                      ("before: At locations where the condition is True",), True),),
    },
    {
        "id": "numpy-infinity",
        "title": "numpy.nan_to_num API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.nan_to_num.html",
        "text": "If no values are passed then positive infinity values will be "
                "replaced with a very large number.",
        "expected": (("positive infinity values", "be replaced with a very large number",
                      ("before: If no values are passed",), True),),
    },
    {
        "id": "numpy-inline-literal",
        "title": "numpy.power API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.power.html",
        "text": "Negative values raised to a non-integral value will return ``nan``.",
        "expected": (("Negative values raised to a non-integral value",
                      "return ``nan``", (), True),),
    },
    {
        "id": "pandas-callable",
        "title": "pandas.read_csv API reference",
        "url": "https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html",
        "text": "If callable, the callable function will be evaluated against the "
                "row indices, returning ``True`` if the row should be skipped "
                "and ``False`` otherwise.",
        "expected": (("the callable function",
                      "be evaluated against the row indices, returning ``True``",
                      ("before: If callable",
                       "after: if the row should be skipped and ``False`` otherwise"),
                      True),),
    },
    {
        "id": "numpy-contrast",
        "title": "numpy.full_like API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.full_like.html",
        "text": "If True, then the newly created array will use the sub-class type "
                "of `a`, otherwise it will be a base-class array.",
        "expected": (("the newly created array", "use the sub-class type of `a`",
                      ("before: If True",
                       "after: otherwise it will be a base-class array"), True),),
    },
    {
        "id": "numpy-contrast-subject",
        "title": "numpy.nanmedian API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.nanmedian.html",
        "text": "Treat the input as undefined, but it will probably be fully "
                "or partially sorted.",
        "expected": (("it", "probably be fully or partially sorted",
                      ("before: contrast (but): Treat the input as undefined",),
                      True),),
    },
    {
        "id": "numpy-shape-parentheses",
        "title": "numpy.mask_indices API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.mask_indices.html",
        "text": "The returned indices will be valid to access arrays of "
                "shape (n, n).",
        "expected": (("The returned indices",
                      "be valid to access arrays of shape (n, n)", (), True),),
    },
    {
        "id": "numpy-example-subject",
        "title": "numpy.genfromtxt API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.genfromtxt.html",
        "text": "For example, ``usecols = (1, 4, 5)`` will extract the 2nd, "
                "5th and 6th columns.",
        "expected": (("``usecols = (1, 4, 5)``",
                      "extract the 2nd, 5th and 6th columns",
                      ("before: For example",), True),),
    },
    {
        "id": "pandas-wrapped-leading-context",
        "title": "pandas.array API reference",
        "url": "https://pandas.pydata.org/docs/reference/api/pandas.array.html",
        "text": "When `data` is an Index or Series, the underlying array "
                "will be extracted from `data`.",
        "expected": (("the underlying array", "be extracted from `data`",
                      ("before: When `data` is an Index or Series",), True),),
    },
    {
        "id": "pandas-multi-comma-condition",
        "title": "pandas.read_csv API reference",
        "url": "https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html",
        "text": "If a column or index cannot be represented as an array of "
                "``datetime``, say because of an unparsable value or a mixture "
                "of timezones, the column or index will be returned unaltered "
                "as an ``object`` data type.",
        "expected": (("the column or index",
                      "be returned unaltered as an ``object`` data type",
                      ("before: If a column or index cannot be represented as an "
                       "array of ``datetime``, say because of an unparsable "
                       "value or a mixture of timezones",), True),),
    },
    {
        "id": "numpy-balanced-parenthetical-subject",
        "title": "numpy.nanquantile API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.nanquantile.html",
        "text": "It must have the same shape and buffer length as the expected "
                "output, but the type (of the output) will be cast if necessary.",
        "expected": (("the type (of the output)", "be cast",
                      ("before: contrast (but): It must have the same shape and "
                       "buffer length as the expected output",
                       "after: if necessary"), True),),
    },
    {
        "id": "pandas-coordinated-instruction",
        "title": "pandas.date_range API reference",
        "url": "https://pandas.pydata.org/docs/reference/api/pandas.date_range.html",
        "text": "Use ``inclusive='right'`` to exclude `start` if it falls on "
                "the boundary, and similarly ``inclusive='neither'`` will "
                "exclude both `start` and `end`.",
        "expected": (("``inclusive='neither'``", "exclude both `start` and `end`",
                      ("before: contrast (and similarly): Use "
                       "``inclusive='right'`` to exclude `start` if it falls "
                       "on the boundary",), True),),
    },
    {
        "id": "numpy-single-verb-predicate",
        "title": "numpy.load API reference",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.load.html",
        "text": "Loading object arrays will fail.",
        "expected": (("Loading object arrays", "fail", (), True),),
    },
    {
        "id": "pandas-bullet-list",
        "title": "pandas.pivot_table API reference",
        "url": "https://pandas.pydata.org/docs/reference/api/pandas.pivot_table.html",
        "text": "* rows with an NA value in any column will be omitted before "
                "computing margins, * index/column keys containing NA values "
                "will be dropped (see ``dropna`` parameter in "
                ":meth:``DataFrame.groupby``).",
        "expected": (
            ("rows with an NA value in any column",
             "be omitted before computing margins", (), True),
            ("index/column keys containing NA values", "be dropped",
             ("after-note: see ``dropna`` parameter in "
              ":meth:``DataFrame.groupby``",), True),
        ),
    },
    {
        "id": "microsoft-length",
        "title": "Arrays.CopyOfRange API reference",
        "url": "https://learn.microsoft.com/en-us/dotnet/api/java.util.arrays.copyofrange",
        "text": "The length of the returned array will be to - from.",
        "expected": (("The length of the returned array", "be to - from", (), True),),
    },
    {
        "id": "pandas-output-order",
        "title": "pandas.read_stata API reference",
        "url": "https://pandas.pydata.org/docs/reference/api/pandas.read_stata.html",
        "text": "Columns will be returned in the given order.",
        "expected": (("Columns", "be returned in the given order", (), True),),
    },
    {
        "id": "pandas-factorize",
        "title": "pandas.factorize API reference",
        "url": "https://pandas.pydata.org/docs/reference/api/pandas.factorize.html",
        "text": "If False, NaN values will be encoded as non-negative integers "
                "and will not drop the missing value.",
        "expected": (("NaN values", "be encoded as non-negative integers",
                      ("before: If False",
                       "after: and will not drop the missing value"), True),),
    },
    {
        "id": "discourse-preface-before-condition",
        "title": "Synthetic boundary fixture",
        "url": "https://example.invalid/discourse-condition",
        "text": "For example, if the matrix is diagonal, then ``diag`` will "
                "refer to its diagonal entries.",
        "expected": (("``diag``", "refer to its diagonal entries",
                      ("before: For example, if the matrix is diagonal",),
                      True),),
    },
    {
        "id": "setting-clause-before-explicit-subject",
        "title": "Synthetic boundary fixture",
        "url": "https://example.invalid/setting-clause",
        "text": "For a triangle with base ``b``, height ``h``, and unit scale "
                "of ``1``, the area will be ``b*h/2``.",
        "expected": (("the area", "be ``b*h/2``",
                      ("before: For a triangle with base ``b``, height ``h``, "
                       "and unit scale of ``1``",), True),),
    },
    {
        "id": "setting-clause-coordinated-subject-ambiguity",
        "title": "Ambiguous subject control",
        "url": "https://example.invalid/ambiguous-subject",
        "text": "For a spring, force and displacement will be recorded.",
        "expected": (("force and displacement", "be recorded",
                      ("before: For a spring",), True),),
    },
    {
        "id": "negative-claim",
        "title": "Negative control",
        "url": "https://example.invalid/negative",
        "text": "The result will not be sorted.",
        "expected": (("The result", "be sorted", (), False),),
    },
    {
        "id": "denied-claim",
        "title": "Denial control",
        "url": "https://example.invalid/denied",
        "text": "The documentation does not guarantee that the function will "
                "sort the array in ascending order.",
        "expected": (("The documentation does not guarantee that the function",
                      "sort the array in ascending order", (), True, "denied"),),
    },
    {
        "id": "quoted-claim",
        "title": "Quotation control",
        "url": "https://example.invalid/quoted",
        "text": "The documentation says, 'The function will sort the array.'",
        "expected": (("The documentation says, 'The function", "sort the array",
                      (), True, "asserted", True),),
    },
    {
        "id": "uncertain-claim",
        "title": "Uncertainty control",
        "url": "https://example.invalid/uncertain",
        "text": "The function might sort the array.",
        "expected": (),
    },
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def check_passages() -> tuple[CRMSResearchIndex, dict[str, str]]:
    index = CRMSResearchIndex()
    citations = {}
    for row in PASSAGES:
        index.add_document(row["id"], row["title"], row["text"], row["url"])
        hit = next((item for item in index.search(
            row["text"][:90], limit=20, context_chars=0)
                    if item.document_id == row["id"]), None)
        require(hit is not None, f"retrieval missed {row['id']}")
        citation = index.citation(hit)
        sentence = index.resolve_citation(citation)
        require(sentence == row["text"],
                f"citation did not resolve to exact source for {row['id']}")
        citations[row["id"]] = citation
        proposals = propose_procedure_phrase_candidates(
            sentence, source_citation=citation)
        expected = row["expected"]
        require(len(proposals) == len(expected),
                f"unexpected candidate count for {row['id']}: {proposals!r}")
        for proposal, wanted in zip(proposals, expected):
            subject, predicate, scope, positive = wanted[:4]
            assertion_status = wanted[4] if len(wanted) > 4 else "asserted"
            quoted = wanted[5] if len(wanted) > 5 else False
            require(proposal.subject == subject
                    and proposal.predicate_phrase == predicate
                    and proposal.scope_notes == scope
                    and proposal.polarity is positive
                    and proposal.assertion_status == assertion_status
                    and proposal.quoted is quoted,
                    f"wrong claim boundary for {row['id']}: {proposal!r}")
    wrapped = ("When `data` is an Index or Series, the underlying array\n"
               "    will be extracted from `data`.")
    wrapped_hash = hashlib.sha256(wrapped.encode("utf-8")).hexdigest()
    wrapped_candidates = propose_procedure_phrase_candidates(
        wrapped,
        source_citation=(f"pandas:array#sha256={wrapped_hash}"
                         f"&chars=0:{len(wrapped)}"))
    require(len(wrapped_candidates) == 1
            and wrapped_candidates[0].subject == "the underlying array"
            and wrapped_candidates[0].scope_notes == (
                "before: When `data` is an Index or Series",),
            f"wrapped source line was not clause-bounded: {wrapped_candidates!r}")
    return index, citations


def check_chat(index: CRMSResearchIndex) -> None:
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="crms-clause-aware-chat-") as tmp:
        root = Path(tmp)
        index.save(root / "index.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSMath().save(root / "math.json")
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSTranslation().save(root / "translations.json")
        process = subprocess.run(
            [sys.executable, str(project / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--math", str(root / "math.json"),
             "--rules", str(root / "rules.json"),
             "--translations", str(root / "translations.json"),
             "--index", str(root / "index.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--candidate-session", str(root / "candidates.json"),
             "--rule-session", str(root / "rule-session.json")],
            input="/suggest-procedure-phrases out array ufunc result\n"
                  "/rules\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        require("the `out` array — 'be set to the ufunc result'"
                in process.stdout,
                f"chat did not state the repaired subject/predicate: {process.stdout}")
        require("Scope: before: At locations where the condition is True"
                in process.stdout,
                f"chat hid the source condition: {process.stdout}")
        require("numpy.add API reference" in process.stdout
                and "#sha256=" in process.stdout,
                "chat did not preserve source title and exact citation")
        require("No transformation rules are committed yet." in process.stdout,
                "review-only candidate changed the rule store")


def main() -> None:
    index, _citations = check_passages()
    check_chat(index)
    print("PASS: full subjects, qualifiers, conditions, contrast, and literals retained")
    print("PASS: multiple list claims receive separate candidates")
    print("PASS: negative, quoted, denied, and uncertain controls retain their status")
    print("PASS: fresh chat shows subject, predicate, scope, and exact evidence")
    print("PASS: candidates remain review-only and do not change rules")
    print(f"LIMIT: {len(PASSAGES)} cited sentence fixtures; "
          "publisher-held-out transfer remains open")


if __name__ == "__main__":
    main()
