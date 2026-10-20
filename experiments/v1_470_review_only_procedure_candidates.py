"""Check a generic, review-only procedure phrase extraction construction.

The extractor recognizes a source sentence's ``will`` predicate without
knowing whether the operation is sort, reverse, or another action. The positive
sentences are attributed to documentation excerpts; negative and assertion
status controls are synthetic. Expected labels are development expectations,
not independent judgments. No candidate is accepted as a rule and no rule is
learned.
"""
from __future__ import annotations

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


SOURCES = {
    "mdn-active": (
        "MDN active operation",
        "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/sort",
        "The following function will sort the array in ascending order "
        "(if it doesn't contain NaN)."),
    "numpy-passive": (
        "NumPy stable sort return-order statement",
        "https://numpy.org/doc/stable/reference/generated/numpy.sort.html",
        "If True, the returned array will maintain the relative order of "
        "a values which compare as equal."),
    "negated": (
        "Negated operation control",
        "https://example.invalid/negated",
        "The following function will not sort the array in ascending order."),
    "quoted": (
        "Quoted operation control",
        "https://example.invalid/quoted",
        "The note says, 'The following function will sort the array in "
        "ascending order,' but this is only a quotation."),
    "denied-embedding": (
        "Denied embedding control",
        "https://example.invalid/denied-embedding",
        "The documentation does not guarantee that the following function "
        "will sort the array in ascending order."),
    "mention": (
        "Metalinguistic mention control",
        "https://example.invalid/mention",
        "The phrase 'sort the array in ascending order' is a label, not a "
        "statement about an operation."),
    "uncertain": (
        "Uncertain operation control",
        "https://example.invalid/uncertain",
        "The following function might sort the array in ascending order."),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def find_candidate(index: CRMSResearchIndex, document_id: str,
                   query: str):
    hit = next((item for item in index.search(query, limit=20, context_chars=0)
                if item.document_id == document_id), None)
    require(hit is not None, f"retrieval missed {document_id}")
    citation = index.citation(hit)
    sentence = index.resolve_citation(citation)
    require(sentence == SOURCES[document_id][2],
            f"citation did not resolve to the exact source sentence: {sentence!r}")
    return propose_procedure_phrase_candidates(
        sentence, source_citation=citation)


def main() -> None:
    index = CRMSResearchIndex()
    for document_id, (title, location, sentence) in SOURCES.items():
        index.add_document(document_id, title, sentence, location)

    active = find_candidate(index, "mdn-active", "function will sort array")
    require(len(active) == 1
            and active[0].predicate_phrase == "sort the array in ascending order"
            and active[0].polarity and not active[0].quoted,
            f"active publisher example was not extracted: {active!r}")
    require(active[0].scope_notes == ("after: if it doesn't contain NaN",),
            f"active applicability condition was lost: {active[0]!r}")

    passive = find_candidate(
        index, "numpy-passive", "returned array relative order equal")
    require(len(passive) == 1
            and passive[0].predicate_phrase
                == "maintain the relative order of a values which compare as equal"
            and passive[0].polarity and not passive[0].quoted,
            f"passive source example was not extracted: {passive!r}")
    require(passive[0].scope_notes == ("before: If True",),
            f"leading applicability condition was lost: {passive[0]!r}")

    negated = find_candidate(index, "negated", "function will not sort")
    require(len(negated) == 1 and not negated[0].polarity
            and not negated[0].quoted,
            f"explicit negative was confused with positive evidence: {negated!r}")
    quoted = find_candidate(index, "quoted", "function will sort array")
    require(len(quoted) == 1 and quoted[0].quoted,
            f"quoted language was treated as an unquoted statement: {quoted!r}")
    denied = find_candidate(index, "denied-embedding",
                            "documentation guarantee function will sort")
    require(len(denied) == 1 and denied[0].assertion_status == "denied",
            f"a denied embedding claim looked asserted: {denied!r}")
    for document_id, query in (("mention", "phrase sort ascending label"),
                               ("uncertain", "function might sort ascending")):
        require(not find_candidate(index, document_id, query),
                f"non-asserted operation text emitted a candidate: {document_id}")

    # Provenance is mandatory and extraction remains inert in the model.
    require(not propose_procedure_phrase_candidates(
        SOURCES["mdn-active"][2], source_citation="missing-citation"),
        "an uncited phrase became a candidate")
    model = CRMSModel(max_workers=1)
    require(not model.list_rules(), "candidate extraction taught a rule")
    require(active == find_candidate(index, "mdn-active", "function will sort array"),
            "candidate extraction is not deterministic")

    # Exercise the public chat command using a fresh process and an isolated
    # source index. The command must show exact evidence while leaving rules
    # untouched.
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="crms-procedure-candidate-chat-") as tmp:
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
            input="/suggest-procedure-phrases function sort array ascending\n"
                  "/rules\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(process.returncode == 0,
                f"chat command failed: {process.stderr}\n{process.stdout}")
        require("'sort the array in ascending order'" in process.stdout
                and "positive-polarity claim; operation meaning unverified"
                    in process.stdout
                and "embedding claim denied; not positive rule evidence"
                    in process.stdout
                and "MDN active operation" in process.stdout
                and "#sha256=" in process.stdout,
                f"chat did not render a cited review candidate: {process.stdout}")
        require("No transformation rules are committed yet." in process.stdout,
                "candidate command installed a procedure before review")

    print("PASS: operation phrases extracted without a sort/reverse lexicon")
    print("PASS: active and passive source forms retain exact citations and conditions")
    print("PASS: negation and quotation remain visible; mention and uncertainty abstain")
    print("PASS: uncited evidence is rejected and proposals remain inert")
    print("PASS: fresh chat renders a source citation without teaching a rule")
    print("LIMIT: construction is narrow, expectations are Codex-authored, and no operation alignment is learned")


if __name__ == "__main__":
    main()
