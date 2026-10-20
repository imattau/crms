"""Probe review-only procedure phrase extraction on cited publisher text.

These are short, source-checked sentence excerpts, not complete documents or a
precision sample. Codex supplies the interpretations and expected spans. The
probe checks whether the current grammar transfers across four publishers and
whether a nested noun phrase is incorrectly promoted to the subject.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_research import CRMSResearchIndex


PASSAGES = (
    {
        "id": "mdn-array-sort",
        "publisher": "MDN",
        "title": "Array.prototype.sort() - JavaScript | MDN",
        "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/sort",
        "sentence": "The following function will sort the array in ascending order (if it doesn't contain NaN).",
        "expected": "sort the array in ascending order",
        "scope": ("after: if it doesn't contain NaN",),
    },
    {
        "id": "numpy-sort-stable",
        "publisher": "NumPy",
        "title": "numpy.sort — NumPy v2.5 Manual",
        "url": "https://numpy.org/doc/stable/reference/generated/numpy.sort.html",
        "sentence": "If True, the returned array will maintain the relative order of a values which compare as equal.",
        "expected": "maintain the relative order of a values which compare as equal",
        "scope": ("before: If True",),
    },
    {
        "id": "aws-lambda-invocation",
        "publisher": "AWS",
        "title": "LambdaInvocationType API Reference",
        "url": "https://docs.aws.amazon.com/cdk/api/v2/java/software/amazon/awscdk/services/ses/actions/LambdaInvocationType.html",
        "sentence": "The function will be invoked asynchronously.",
        "expected": "be invoked asynchronously",
        "scope": (),
    },
    {
        "id": "microsoft-preferences-keys",
        "publisher": "Microsoft Learn",
        "title": "Preferences.Keys Method (Java.Util.Prefs)",
        "url": "https://learn.microsoft.com/en-us/dotnet/api/java.util.prefs.preferences.keys?view=net-android-36.0",
        "sentence": "(The returned array will be of size zero if this node has no preferences.)",
        "expected": "be of size zero",
        "scope": ("after: if this node has no preferences",),
    },
    {
        "id": "microsoft-copyofrange-subject-control",
        "publisher": "Microsoft Learn",
        "title": "Arrays.CopyOfRange Method (Java.Util)",
        "url": "https://learn.microsoft.com/en-us/dotnet/api/java.util.arrays.copyofrange?view=net-android-37.0",
        "sentence": "The length of the returned array will be to - from.",
        # The complete grammatical subject is "The length of the returned
        # array"; a broad boundary must retain it rather than choosing only
        # the nested "returned array" phrase.
        "expected": "be to - from",
        "expected_subject": "The length of the returned array",
        "scope": (),
    },
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    results = []
    for row in PASSAGES:
        index.add_document(row["id"], row["title"], row["sentence"], row["url"])
        hit = next((item for item in index.search(
            row["sentence"][:80], limit=20, context_chars=0)
            if item.document_id == row["id"]), None)
        require(hit is not None, f"retrieval missed {row['id']}")
        citation = index.citation(hit)
        require(index.resolve_citation(citation) == row["sentence"],
                f"citation did not resolve to the exact passage for {row['id']}")
        candidates = propose_procedure_phrase_candidates(
            row["sentence"], source_citation=citation)
        if row["expected"] is None:
            require(not candidates,
                    f"nested object was promoted to subject: {candidates!r}")
        else:
            require(len(candidates) == 1
                    and candidates[0].predicate_phrase == row["expected"]
                    and ("expected_subject" not in row
                         or candidates[0].subject == row["expected_subject"])
                    and candidates[0].scope_notes == row["scope"]
                    and candidates[0].polarity
                    and not candidates[0].quoted
                    and candidates[0].source_citation == citation,
                    f"unexpected candidate for {row['id']}: {candidates!r}")
        results.append((row, candidates))

    publishers = {row["publisher"] for row in PASSAGES}
    require(publishers == {"MDN", "NumPy", "AWS", "Microsoft Learn"},
            f"publisher coverage changed unexpectedly: {publishers}")
    require(all(propose_procedure_phrase_candidates(
        row["sentence"], source_citation="missing") == () for row in PASSAGES),
        "uncited source text produced a candidate")

    print("PASS: exact cited excerpts from four publisher families were handled")
    print("PASS: four positive constructions retained phrase and condition")
    print("PASS: nested 'length of returned array' subject stayed intact")
    print("LIMIT: five selected excerpts, Codex labels, and no complete-document recall/precision estimate")


if __name__ == "__main__":
    main()
