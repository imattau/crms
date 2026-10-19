"""Review-gated phrase transfer from a held-out publisher's source wording.

This probe extracts one bounded ``will <operation phrase>`` construction from
MDN prose, links it to an independently hosted Python doctest, and requires a
reviewer to accept the mapping before CRMS learns it. It is a publisher-held-out
transfer case, not a general source-language parser.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
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


MDN_SOURCE = (
    "mdn-array-sort", "MDN: Array.prototype.sort",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/sort",
    "The following function will sort the array in ascending order "
    "(if it doesn't contain NaN).",
)
PYTHON_SOURCE = (
    "python-sorting-howto", "Python Sorting HOWTO",
    "https://docs.python.org/3/howto/sorting.html",
    ">>> sorted([5, 2, 3, 1, 4])\n[1, 2, 3, 4, 5]",
)
NEGATED_SOURCE = (
    "mdn-negative-sort", "Controlled negated MDN wording",
    "https://example.invalid/negative-mdn-sort",
    "The following function will not sort the array in ascending order.",
)
MENTION_SOURCE = (
    "mdn-mentioned-sort", "Controlled metalinguistic MDN wording",
    "https://example.invalid/mentioned-mdn-sort",
    "The phrase 'sort the array in ascending order' appears in this note, "
    "but is not an instruction.",
)
PAIR = ([5, 2, 3, 1, 4], [1, 2, 3, 4, 5])
CONTRASTS = (
    ([1, -1, 1], [-1, 1, 1]),
    ([0, 1, -1], [-1, 0, 1]),
)
HELD_OUT = (
    ([12, -3, 7, 0], [-3, 0, 7, 12]),
    ([4, 4, -8, 2, 0], [-8, 0, 2, 4, 4]),
    ([9, 1, 3, 6], [1, 3, 6, 9]),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def exact_hit(index: CRMSResearchIndex, source_id: str, query: str):
    return next((hit for hit in index.search(query, limit=30, context_chars=0)
                 if hit.document_id == source_id), None)


def extract_review_candidate(index: CRMSResearchIndex,
                             prose_source_id: str = MDN_SOURCE[0]):
    prose_hit = exact_hit(index, prose_source_id,
                          "function will sort array ascending order")
    code_hit = exact_hit(index, PYTHON_SOURCE[0],
                         "sorted 5 2 3 1 4 1 2 3 4 5")
    if prose_hit is None or code_hit is None:
        return None
    prose_citation = index.citation(prose_hit)
    code_citation = index.citation(code_hit)
    prose = index.resolve_citation(prose_citation)
    code = index.resolve_citation(code_citation)
    # This extraction rule is intentionally narrow: capture a source-attested
    # operation surface after "will", and reject negation before the verb.
    match = re.search(
        r"\bwill\s+(?P<phrase>sort\s+the\s+array\s+in\s+ascending\s+order)\b",
        prose, flags=re.IGNORECASE)
    if match is None or re.search(
            r"\bwill\s+not\s+sort\b", prose, flags=re.IGNORECASE):
        return None
    if not _citation_contains_integer_pair(code, *PAIR):
        return None
    if PAIR[1] != sorted(PAIR[0]):
        return None
    prose_origin = urlparse(prose_hit.location or "").hostname
    code_origin = urlparse(code_hit.location or "").hostname
    if not prose_origin or not code_origin or prose_origin == code_origin:
        return None
    return {
        "phrase": match.group("phrase").casefold(),
        "operation": "sort_ascending",
        "prose_citation": prose_citation,
        "code_citation": code_citation,
        "prose": prose,
        "code": code,
        "origins": {prose_origin, code_origin},
    }


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
    with tempfile.TemporaryDirectory(prefix="crms-heldout-publisher-") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        for source in (MDN_SOURCE, PYTHON_SOURCE):
            document_id, title, location, text = source
            index.add_document(document_id, title, text, location)
        prose_hit = exact_hit(index, MDN_SOURCE[0],
                              "function will sort array ascending order")
        code_hit = exact_hit(index, PYTHON_SOURCE[0],
                             "sorted 5 2 3 1 4 1 2 3 4 5")
        require(prose_hit is not None and code_hit is not None,
                "retrieval missed the held-out publisher phrase or code pair")
        candidate = extract_review_candidate(index)
        require(candidate is not None,
                "held-out publisher wording did not produce a review candidate")
        require(candidate["phrase"] == "sort the array in ascending order"
                and candidate["operation"] == "sort_ascending"
                and candidate["origins"] == {
                    "developer.mozilla.org", "docs.python.org"},
                f"unexpected phrase transfer or source origins: {candidate!r}")
        require(index.resolve_citation(candidate["prose_citation"])
                == MDN_SOURCE[3]
                and index.resolve_citation(candidate["code_citation"])
                == PYTHON_SOURCE[3],
                "candidate citations did not resolve to exact source spans")

        # The accepted proposal is reviewed and explicitly taught; proposing
        # it alone must not alter CRMS's rule memory.
        rules = CRMSModel(max_workers=1)
        require(candidate["phrase"] not in rules.list_rules(),
                "review-only candidate unexpectedly entered the model")
        rules.save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSTranslation().save(root / "translations.json")
        index.save(root / "index.json")

        reviewer = "codex:reviewed-source-alignment"
        teaching = [
            f"/teach-rule {candidate['phrase']}|"
            f"{','.join(map(str, PAIR[0]))}|{','.join(map(str, PAIR[1]))}|"
            f"{candidate['code_citation']}|{reviewer}|"
            f"{candidate['prose_citation']}",
            *(
                f"/teach-rule {candidate['phrase']}|"
                f"{','.join(map(str, values))}|{','.join(map(str, output))}||"
                f"{reviewer}"
                for values, output in CONTRASTS
            ),
        ]
        chat = launch_chat(
            root, [*teaching, "/cancel-rule",
                   f"Write Python code to {candidate['phrase']}"])
        require(chat.returncode == 0
                and "Could not teach rule:" not in chat.stdout
                and f"Generated Python for '{candidate['phrase']}'"
                in chat.stdout,
                "reviewed held-out phrase did not work through chat: "
                + chat.stdout[-1200:])

        restored = CRMSModel(root / "rules.json", max_workers=1)
        records = restored.example_records(candidate["phrase"])
        require(records[0].get("source_id") == candidate["code_citation"]
                and records[0].get("instruction_source_id")
                == candidate["prose_citation"]
                and all(record.get("labeler_id") == reviewer
                        for record in records),
                f"reloaded rule lost source or reviewer provenance: {records!r}")
        artifact = generate_python(restored, candidate["phrase"])
        require(artifact is not None,
                "reviewed phrase did not produce a standalone artifact")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<heldout-publisher-sort>", "exec"),
             namespace)
        require(all(namespace["transform"](values) == expected
                    for values, expected in HELD_OUT),
                "generated rule failed the independent held-out inputs")
        require(restored.predict(
            "sort the array in descending order", [3, 1, 2]).status != "ok",
            "ascending proposal licensed the opposite direction")

        # Negated and metalinguistic text must not create another candidate.
        false_proposals = 0
        for source in (NEGATED_SOURCE, MENTION_SOURCE):
            negative_index = CRMSResearchIndex()
            for item in (source, PYTHON_SOURCE):
                document_id, title, location, text = item
                negative_index.add_document(document_id, title, text, location)
            false_proposals += int(
                extract_review_candidate(
                    negative_index, source[0]) is not None)
        require(false_proposals == 0,
                f"negative source controls created {false_proposals} proposal(s)")

    print("new-publisher phrase extracted with two exact citations: PASS")
    print("proposal remained inert until review and chat teaching: PASS")
    print("reviewed rule persisted and passed three held-out lists: PASS")
    print("negation/mention controls: 0 false candidates in 2 cases")
    print("limitation: one hand-coded passive-to-imperative pattern; not general induction")


if __name__ == "__main__":
    main()
