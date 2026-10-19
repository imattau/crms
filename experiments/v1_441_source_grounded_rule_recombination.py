"""Recombine reviewed source-derived procedure phrases in ordinary chat.

This joins the narrow phrase proposals from v1_436/v1_437 to CRMS's learned
sequence connective. The surface-to-operation mappings and connective examples
are explicitly Codex-labeled; the test does not claim autonomous extraction.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / "experiments")]

from crms_codegen import generate_python
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation
from v1_436_source_derived_rule_phrase_review import (
    NUMPY_FLIP_SOURCE, PYTHON_REVERSE_SOURCE, REVERSE_PAIR,
    REVERSE_REVIEW_CONTRASTS, propose_reverse_phrase,
)
from v1_437_heldout_publisher_phrase_review import (
    CONTRASTS, MDN_SOURCE, PAIR, PYTHON_SOURCE, extract_review_candidate,
)


UNIQUE_SOURCE = (
    "python-dict-fromkeys", "Python dict.fromkeys example",
    "https://docs.python.org/3/library/stdtypes.html#dict.fromkeys",
    ">>> list(dict.fromkeys([4, 1, 4, 2]))\n[4, 1, 2]",
)
UNIQUE_PHRASE = "remove duplicate values"
COMPOUND_PHRASES = (
    "sort the array in ascending order then reverse the order of elements",
    "reverse the order of elements then sort the array in ascending order",
)
HELD_OUT_COMPOSITION = (
    "remove duplicate values then sort the array in ascending order")
TRAINING_VALUES = (
    [3, 1, 2], [4, -1, 7], [0, 5, -2, 8], [-5, 9], [12], [],
)
COMPOUND_VALUES = (*TRAINING_VALUES, [0, 0])
UNIQUE_VALUES = (
    [4, 1, 4, 2], [3, 1, 3, 2], [-1, -1, 2, 0, 2], [0, 0],
    [2, 2, 1, 1], [1, 2, 3], [],
)
HELD_OUT_VALUES = (
    [4, 1, 4, 2], [-3, 5, 0, -3], [8, 2, 8, 1, 0], [],
)
REVIEWER = "codex:reviewed-source-alignment"
CONNECTIVE_LABELER = "codex:reviewed-sequence-connective"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(root: Path, prompt: str) -> subprocess.CompletedProcess[str]:
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
        command, input=prompt + "\n/quit\n", text=True, capture_output=True,
        cwd=root, timeout=90, check=False)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-source-recombination-") as tmp:
        root = Path(tmp)
        index = CRMSResearchIndex()
        for source in (MDN_SOURCE, PYTHON_SOURCE, NUMPY_FLIP_SOURCE,
                       PYTHON_REVERSE_SOURCE, UNIQUE_SOURCE):
            document_id, title, location, text = source
            index.add_document(document_id, title, text, location)

        sort_candidate = extract_review_candidate(index)
        reverse_candidate = propose_reverse_phrase(index)
        require(sort_candidate is not None and reverse_candidate is not None,
                "source prose and executable examples did not produce both proposals")
        require(sort_candidate["phrase"] == "sort the array in ascending order"
                and reverse_candidate.phrase == "reverse the order of elements",
                f"unexpected reviewed source phrases: {sort_candidate!r}; "
                f"{reverse_candidate!r}")

        sort_prose = sort_candidate["prose_citation"]
        sort_code = sort_candidate["code_citation"]
        reverse_prose = reverse_candidate.evidence[0].prose_citation
        reverse_code = reverse_candidate.evidence[1].code_citation
        require(all((sort_prose, sort_code, reverse_prose, reverse_code)),
                "source proposals lost a prose or code citation")
        require(index.resolve_citation(sort_prose) == sort_candidate["prose"]
                and index.resolve_citation(sort_code) == PYTHON_SOURCE[3]
                and index.resolve_citation(reverse_prose) == NUMPY_FLIP_SOURCE[3]
                and index.resolve_citation(reverse_code)
                    == PYTHON_REVERSE_SOURCE[3],
                "a reviewed source citation did not round-trip exactly")
        unique_hit = next((hit for hit in index.search(
            "dict.fromkeys 4 1 4 2", limit=10, context_chars=0)
            if hit.document_id == UNIQUE_SOURCE[0]), None)
        require(unique_hit is not None,
                "source retrieval missed the unique-value doctest")
        unique_code = index.citation(unique_hit)
        require(index.resolve_citation(unique_code) == UNIQUE_SOURCE[3],
                "unique-value doctest citation did not round-trip exactly")

        model = CRMSModel(max_composition_depth=2, max_workers=1)
        sort_examples = [(list(PAIR[0]), list(PAIR[1])), *CONTRASTS]
        sort_result = model.teach(
            sort_candidate["phrase"], sort_examples,
            source_ids=[sort_code, None, None],
            labeler_ids=[REVIEWER] * len(sort_examples),
            instruction_source_ids=[sort_prose] * len(sort_examples))
        require(sort_result.status == "learned"
                and sort_result.candidate_count == 1,
                f"reviewed sort procedure was not uniquely learned: {sort_result}")

        reverse_examples = [(list(REVERSE_PAIR[0]), list(REVERSE_PAIR[1])),
                            *REVERSE_REVIEW_CONTRASTS]
        reverse_result = model.teach(
            reverse_candidate.phrase, reverse_examples,
            source_ids=[reverse_code, *([None] * len(REVERSE_REVIEW_CONTRASTS))],
            labeler_ids=[REVIEWER] * len(reverse_examples),
            instruction_source_ids=[reverse_prose] * len(reverse_examples))
        require(reverse_result.status == "learned"
                and reverse_result.candidate_count == 1,
                f"reviewed reverse procedure was not uniquely learned: "
                f"{reverse_result}")

        unique_examples = [(values, list(dict.fromkeys(values)))
                           for values in UNIQUE_VALUES]
        unique_result = model.teach(
            UNIQUE_PHRASE, unique_examples,
            source_ids=[unique_code, *([None] * (len(unique_examples) - 1))],
            labeler_ids=[REVIEWER] * len(unique_examples))
        require(unique_result.status == "learned"
                and unique_result.candidate_count == 1,
                f"reviewer-labeled unique procedure was not learned: "
                f"{unique_result}")

        def sort_then_reverse(values: list[int]) -> list[int]:
            return list(reversed(sorted(values)))

        def reverse_then_sort(values: list[int]) -> list[int]:
            return sorted(reversed(values))

        for phrase, transform in zip(COMPOUND_PHRASES,
                                     (sort_then_reverse, reverse_then_sort)):
            compound_result = model.teach(
                phrase,
                [(values, transform(values)) for values in COMPOUND_VALUES],
                source_ids=[None] * len(COMPOUND_VALUES),
                labeler_ids=[CONNECTIVE_LABELER] * len(COMPOUND_VALUES))
            require(compound_result.status == "learned",
                    f"sequencing evidence did not learn {phrase!r}: "
                    f"{compound_result}")

        expected_evidence = {
            UNIQUE_PHRASE, sort_candidate["phrase"],
            *COMPOUND_PHRASES,
        }
        for values in HELD_OUT_VALUES:
            prediction = model.predict(HELD_OUT_COMPOSITION, values)
            expected = sorted(set(values))
            require(prediction.status == "ok" and prediction.output == expected
                    and "learned_sequence:then" in prediction.matched_templates
                    and expected_evidence <= set(prediction.evidence_phrases),
                    f"unseen source-grounded composition failed on {values}: "
                    f"{prediction}")

        artifact = generate_python(model, HELD_OUT_COMPOSITION)
        require(artifact is not None
                and expected_evidence <= set(artifact.evidence_phrases),
                f"composition did not produce evidence-linked code: {artifact}")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<crms-source-recombination>", "exec"),
             namespace)
        transform = namespace["transform"]
        require(all(transform(values) == sorted(set(values))
                    for values in HELD_OUT_VALUES)
                and namespace["validate_examples"](),
                "generated code failed the independent list oracle")

        unsupported = (
            "remove duplicate values then sort the array in descending order")
        require(model.predict(unsupported, [4, 1, 4, 2]).status != "ok"
                and generate_python(model, unsupported) is None,
                "unsupported direction unexpectedly composed or generated code")

        model.save(root / "rules.json")
        restored = CRMSModel(root / "rules.json", max_workers=1)
        for phrase, expected_citation in (
                (sort_candidate["phrase"], sort_code),
                (reverse_candidate.phrase, reverse_code)):
            records = restored.example_records(phrase)
            require(records[0].get("source_id") == expected_citation
                    and records[0].get("instruction_source_id")
                        == (sort_prose if phrase == sort_candidate["phrase"]
                            else reverse_prose)
                    and all(record.get("labeler_id") == REVIEWER
                            for record in records),
                    f"source/reviewer provenance did not survive reload: "
                    f"{phrase}: {records!r}")
        unique_records = restored.example_records(UNIQUE_PHRASE)
        require(unique_records[0].get("source_id") == unique_code
                and all(record.get("labeler_id") == REVIEWER
                        for record in unique_records),
                "unique-operation source or reviewer attribution was lost")
        restored_artifact = generate_python(restored, HELD_OUT_COMPOSITION)
        require(restored_artifact is not None
                and restored_artifact.provenance_id == artifact.provenance_id,
                "composition artifact changed after model reload")

        # The integrated task is through ordinary chat with a fresh process.
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        index.save(root / "index.json")
        chat = run_chat(
            root, f"Write Python code to {HELD_OUT_COMPOSITION}")
        require(chat.returncode == 0
                and f"Generated Python for '{HELD_OUT_COMPOSITION}'" in chat.stdout
                and all(phrase in chat.stdout for phrase in expected_evidence),
                f"fresh chat could not use the learned composition: "
                f"{chat.stdout[-1600:]}\n{chat.stderr}")

    print("reviewed source phrases learned with exact citations: PASS")
    print("new unique→sort composition used learned `then`: PASS")
    print("independent output oracle and generated-code checks: PASS")
    print("citation/reviewer provenance survived model reload: PASS")
    print("fresh chat generated held-out composition; descending near miss abstained: PASS")
    print("scope: bounded teacher-attributed composition, not autonomous prose learning")


if __name__ == "__main__":
    main()
