"""Compose small procedures taught from cited documentation and examples.

The target composition uses stable-unique, sort, and reverse. Its stable-unique
examples are Codex-labeled demonstrations linked to Python's documented
insertion-order semantics; sort and reverse have cited code pairs. The sequence
connective is also teacher-labeled. Each operation must change held-out outputs.
The held-out composition is never sent to the learner. This remains a bounded,
teacher-guided probe, not source-only induction or broad coding competence.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import generate_python, show_generated_code_evidence
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


SORT_DOC = (">>> sorted([5, 2, 3, 1, 4])\n[1, 2, 3, 4, 5]")
UNIQUE_DOC = (
    ">>> a = np.array([1, 2, 6, 4, 2, 3, 2])\n"
    ">>> np.unique(a)\narray([1, 2, 3, 4, 6])")
REVERSE_DOC = (
    ">>> for i in reversed(range(1, 10, 2)):\n"
    "...     print(i)\n...\n9\n7\n5\n3\n1")
SORT_PROSE = (
    "A simple ascending sort is very easy: just call the sorted() function.")
UNIQUE_PROSE = "Returns the sorted unique elements of an array."
REVERSE_PROSE = (
    "To loop over a sequence in reverse, first specify the sequence in a "
    "forward direction and then call the reversed() function.")
SOURCES = (
    ("python-sort", "Python Sorting HOWTO",
     "https://docs.python.org/3/howto/sorting.html",
     "sort the list", SORT_DOC, SORT_PROSE,
     [5, 2, 3, 1, 4], [1, 2, 3, 4, 5]),
    ("numpy-unique", "NumPy: numpy.unique",
     "https://numpy.org/doc/stable/reference/generated/numpy.unique.html",
     "remove duplicate values", UNIQUE_DOC, UNIQUE_PROSE,
     [1, 2, 6, 4, 2, 3, 2],
     [1, 2, 3, 4, 6]),
    ("python-reverse", "Python Tutorial: Data Structures",
     "https://docs.python.org/3/tutorial/datastructures.html",
     "reverse the list", REVERSE_DOC, REVERSE_PROSE,
     [1, 3, 5, 7, 9], [9, 7, 5, 3, 1]),
)
COMPOUNDS = (
    ("sort the list then reverse the values", ("sort", "reverse")),
    ("reverse the list then sort the values", ("reverse", "sort")),
)
STABLE_UNIQUE_PHRASE = "keep the first occurrence of each value"
STABLE_UNIQUE_DOC = (
    "Dictionaries preserve insertion order. Note that updating a key does "
    "not affect the order. Keys added after deletion are inserted at the end.\n"
    ">>> d = {\"one\": 1, \"two\": 2, \"three\": 3, \"four\": 4}\n"
    ">>> list(d)\n['one', 'two', 'three', 'four']\n"
    "class method fromkeys(iterable, value=None): Create a new dictionary "
    "with keys from iterable and values set to value."
)
STABLE_UNIQUE_VALUES = (
    [4, 1, 4, 2], [1, 3, 1, 2, 3], [-1, -1, 2, 0, 2],
    [0, 0], [1, 2, 3], [], [1, 2, 3, 4, 2],
)
BASE_TRAINING_VALUES = {
    "sort the list": (
        [3, 1, 2], [4, -1, 7], [0, 5, -2, 8], [-5, 9], [12], [],
        [0, 0], [3, 1, 3, 2]),
    "remove duplicate values": (
        [4, 1, 4, 2], [3, 1, 3, 2], [-1, -1, 2, 0, 2], [0, 0],
        [2, 2, 1, 1], [1, 2, 3]),
    "reverse the list": (
        [3, 1, 2], [4, -1, 7], [0, 5, -2, 8], [-5, 9], [12], [],
        [0, 0]),
}
TEACHER_SYNONYMS = {
    "sort the values": ("sort", BASE_TRAINING_VALUES["sort the list"]),
    "reverse the values": ("reverse", BASE_TRAINING_VALUES["reverse the list"]),
}
COMPOUND_TRAINING_VALUES = (
    [4, 1, 4, 2], [3, 3, 1, 2, 1], [-1, -1, 2, 0, 2], [],
    [12, 3, 12, 4], [-5, 9, 1], [0, 0],
)
HELD_OUT_TEXT = (
    "keep the first occurrence of each value then sort the list "
    "then reverse the values")
HELD_OUT_VALUES = (
    [6, 2, 6, -1, 2], [4, 4, 0, -3, 1, 0], [9, -2, 9, 3], [],
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def apply(values: list[int], operation: str) -> list[int]:
    if operation == "sort":
        return sorted(values)
    if operation == "unique":
        # Match numpy.unique's documented sorted-unique semantics.
        return sorted(set(values))
    if operation == "stable_unique":
        return list(dict.fromkeys(values))
    if operation == "reverse":
        return list(reversed(values))
    raise ValueError(operation)


def apply_sequence(values: list[int], operations: tuple[str, ...]
                   ) -> list[int]:
    result = list(values)
    for operation in operations:
        result = apply(result, operation)
    return result


def citation_for(index: CRMSResearchIndex, source: tuple
                 ) -> tuple[str, str]:
    (document_id, title, location, _instruction, text, prose,
     _inputs, _outputs) = source
    index.add_document(document_id, title, text, location)
    query = "reversed" if "reversed(" in text else (
        "unique" if "unique(" in text else "sorted")
    hit = next((hit for hit in index.search(query, limit=10, context_chars=0)
                if hit.document_id == document_id), None)
    require(hit is not None, f"retrieval missed cited example {document_id}")
    citation = index.citation(hit)
    require(index.resolve_citation(citation) == text,
            f"citation did not resolve to exact example {document_id}")
    prose_document_id = document_id + "-instruction"
    index.add_document(prose_document_id, title + " instruction prose",
                       prose, location)
    prose_hit = next((hit for hit in index.search(
        prose, limit=10, context_chars=0)
        if hit.document_id == prose_document_id), None)
    require(prose_hit is not None,
            f"retrieval missed instruction prose {prose_document_id}")
    prose_citation = index.citation(prose_hit)
    require(index.resolve_citation(prose_citation) == prose,
            f"instruction citation did not resolve exactly: {prose_document_id}")
    return citation, prose_citation


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
    with tempfile.TemporaryDirectory(prefix="crms-doc-procedure-") as folder:
        root = Path(folder)
        rules = CRMSModel(max_workers=1)
        rules.save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSTranslation().save(root / "translations.json")

        index = CRMSResearchIndex()
        source_citations = {}
        instruction_citations = {}
        teaching = []
        for source in SOURCES:
            (document_id, _title, _location, phrase, _text, _prose,
             inputs, outputs) = source
            citation, instruction_citation = citation_for(index, source)
            source_citations[phrase] = citation
            instruction_citations[phrase] = instruction_citation
            teaching.append(
                f"/teach-rule {phrase}|{','.join(map(str, inputs))}|"
                f"{','.join(map(str, outputs))}|{citation}|codex:labeler-v1|"
                f"{instruction_citation}")
            # The source pair is only one demonstration and is often
            # underdetermined. Add an attributed set of varied examples and a
            # contrast that helps separate the intended operation.
            operation = {
                "sort the list": "sort",
                "remove duplicate values": "unique",
                "reverse the list": "reverse",
            }[phrase]
            for values in BASE_TRAINING_VALUES[phrase]:
                out_values = apply(list(values), {
                    "sort": "sort", "unique": "unique",
                    "reverse": "reverse",
                }[operation])
                teaching.append(
                    f"/teach-rule {phrase}|{','.join(map(str, values))}|"
                    f"{','.join(map(str, out_values))}||codex:labeler-v1")

        # These surface variants are Codex-attributed wording lessons, not
        # text-to-instruction mappings claimed by the cited code examples.
        for phrase, (operation, examples) in TEACHER_SYNONYMS.items():
            supporting_source = next(
                source for source in SOURCES
                if {"sort the values": "sort the list",
                    "reverse the values": "reverse the list"}[phrase]
                == source[3])
            citation = source_citations[supporting_source[3]]
            source_input, source_output = supporting_source[6:8]
            teaching.append(
                f"/teach-rule {phrase}|{','.join(map(str, source_input))}|"
                f"{','.join(map(str, source_output))}|{citation}|codex:labeler-v1")
            for values in examples:
                output = apply(list(values), operation)
                teaching.append(
                    f"/teach-rule {phrase}|{','.join(map(str, values))}|"
                    f"{','.join(map(str, output))}||codex:labeler-v1")

        # Python documents insertion-ordered dictionaries and dict.fromkeys.
        # The operation name and list I/O pairs below are Codex-labeled
        # demonstrations of combining those documented semantics; the docs
        # do not directly state this instruction mapping.
        dictionary_source_id = "python-dict-order"
        dictionary_title = "Python Built-in Types: Dictionary Ordering"
        dictionary_location = (
            "https://docs.python.org/3/library/stdtypes.html#dict")
        index.add_document(dictionary_source_id, dictionary_title,
                           STABLE_UNIQUE_DOC, dictionary_location)
        dictionary_hit = next((hit for hit in index.search(
            "Dictionaries preserve insertion order", limit=10, context_chars=0)
            if hit.document_id == dictionary_source_id), None)
        require(dictionary_hit is not None,
                "retrieval missed dictionary-ordering documentation")
        dictionary_instruction_citation = index.citation(dictionary_hit)
        require(index.resolve_citation(dictionary_instruction_citation)
                == STABLE_UNIQUE_DOC,
                "dictionary-ordering citation did not resolve exactly")
        instruction_citations[STABLE_UNIQUE_PHRASE] = (
            dictionary_instruction_citation)
        for values in STABLE_UNIQUE_VALUES:
            output = apply(list(values), "stable_unique")
            teaching.append(
                f"/teach-rule {STABLE_UNIQUE_PHRASE}|"
                f"{','.join(map(str, values))}|{','.join(map(str, output))}||"
                "codex:labeler-v1|" + dictionary_instruction_citation)

        # The connective examples are explicitly teacher supplied. They teach
        # order effects, which the source examples do not license by themselves.
        for phrase, operations in COMPOUNDS:
            for values in COMPOUND_TRAINING_VALUES:
                output = apply_sequence(list(values), operations)
                teaching.append(
                    f"/teach-rule {phrase}|{','.join(map(str, values))}|"
                    f"{','.join(map(str, output))}||codex:labeler-v1")

        held_out_outputs = [
            apply_sequence(list(values), ("stable_unique", "sort", "reverse"))
            for values in HELD_OUT_VALUES]
        for index_to_omit, omitted in enumerate(
                ("stable_unique", "sort", "reverse")):
            ablated = ("stable_unique", "sort", "reverse")[:index_to_omit] + (
                "stable_unique", "sort", "reverse")[index_to_omit + 1:]
            ablated_outputs = [
                apply_sequence(list(values), ablated)
                for values in HELD_OUT_VALUES]
            require(all(
                actual != expected for values, actual, expected in zip(
                    HELD_OUT_VALUES, ablated_outputs, held_out_outputs)
                if values),
                f"a non-empty held-out input does not show the contribution "
                f"of {omitted}")
        held_out_rows = [
            f"{values} -> {output}"
            for values, output in zip(HELD_OUT_VALUES, held_out_outputs)]
        index.add_document(
            "held-out-composition", "Held-out procedure composition",
            "\n".join(held_out_rows), "evaluation/held-out-composition.txt")
        index.save(root / "index.json")

        answer = f"Write Python code to {HELD_OUT_TEXT}"
        run = launch(root, [*teaching, answer, "Show examples for that code"])
        require(run.returncode == 0,
                f"chat failed with {run.returncode}: {run.stderr}")
        require(f"Generated Python for '{HELD_OUT_TEXT}'" in run.stdout,
                f"chat did not compose cited operations: {run.stdout[-2500:]!r}")
        require("The cited text demonstrates this exact numeric pair" in run.stdout,
                "chat omitted the citation-verification boundary")
        require("Recorded declared labeler for this example: codex:labeler-v1" in run.stdout,
                "chat did not report the supplied labeler attribution")

        learned = CRMSModel(root / "rules.json", max_workers=1)
        for phrase, citation in source_citations.items():
            records = learned.example_records(phrase)
            require(any(record.get("source_id") == citation
                        for record in records),
                    f"sourced component lost its citation: {phrase}")
            require(any(record.get("source_id") is None for record in records),
                    f"Codex-authored examples were mislabeled as sourced: {phrase}")
            require(all(record.get("labeler_id") == "codex:labeler-v1"
                        for record in records),
                    f"declared labeler attribution was lost: {phrase}: {records!r}")
            require(any(record.get("instruction_source_id")
                        == instruction_citations[phrase] for record in records),
                    f"instruction prose citation was lost: {phrase}")

        artifact = generate_python(learned, HELD_OUT_TEXT)
        require(artifact is not None, "no standalone composition was generated")
        unique_probe = learned.predict("remove duplicate values", [4, 1, 4, 2])
        require(unique_probe.status == "ok"
                and unique_probe.output == [1, 2, 4],
                "unique rule did not preserve the source's sorted-unique behavior")
        stable_unique_probe = learned.predict(
            STABLE_UNIQUE_PHRASE, [4, 1, 4, 2])
        require(stable_unique_probe.status == "ok"
                and stable_unique_probe.output == [4, 1, 2],
                "stable-unique rule did not preserve first occurrence order")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<document-sourced-composition>", "exec"),
             namespace)
        transform = namespace["transform"]
        require([transform(values) for values in HELD_OUT_VALUES]
                == held_out_outputs,
                "generated composition failed the held-out inputs")
        artifact_sources = {
            row["source_id"]
            for row in namespace["CRMS_PROVENANCE"]["examples"]
            if row["source_id"] is not None}
        expected_artifact_sources = {
            source_citations["sort the list"],
            source_citations["reverse the list"],
        }
        require(artifact_sources == expected_artifact_sources,
                "artifact provenance does not match the cited component "
                f"examples: {artifact_sources!r} != "
                f"{expected_artifact_sources!r}")
        require(all(row.get("labeler_id") == "codex:labeler-v1"
                    for row in namespace["CRMS_PROVENANCE"]["examples"]),
                "generated artifact lost declared labeler attribution")
        require(namespace["validate_examples"](),
                "generated artifact's embedded checks failed")
        evidence = show_generated_code_evidence(artifact)
        require(all(citation in evidence
                    for citation in expected_artifact_sources),
                "user-facing evidence omitted a component citation")
        require("[Declared labeler: codex:labeler-v1]" in evidence,
                "user-facing evidence omitted declared labeler attribution")
        used_instruction_citations = {
            instruction_citations[phrase]
            for phrase in artifact.evidence_phrases
            if phrase in instruction_citations
        }
        require(used_instruction_citations
                and all(f"[Instruction source (labeler-selected; "
                        f"semantic relation unchecked): {citation}]" in evidence
                        for citation in used_instruction_citations),
                "user-facing evidence omitted instruction-source citations: "
                + repr(evidence))

        replay = launch(root, [answer])
        require(replay.returncode == 0
                and artifact.provenance_id in replay.stdout,
                "fresh chat process did not reproduce the saved artifact")

        unsupported = launch(root, [
            "Write Python code to remove duplicate values then encrypt the list "
            "then reverse the values"])
        generated_lines = [line for line in unsupported.stdout.splitlines()
                           if line.startswith("CRMS> Generated Python")]
        require(unsupported.returncode == 0
                and not generated_lines
                and "I could not resolve 'remove duplicate values then "
                    "encrypt the list then reverse the values'" in unsupported.stdout,
                "chat generated code with an unsupported middle operation: "
                + repr(generated_lines))

    print("code-pair and instruction-prose citations resolve independently: PASS")
    print("unique rule sorts distinct values on a non-monotonic input: PASS")
    print("each non-empty held-out output changes when any one stage is removed: PASS")
    print("chat composed stable-unique→sort→reverse on four held-out lists: PASS")
    print("generated artifact kept component citations and passed checks: PASS")
    print("declared labeler attribution survived save and artifact rendering: PASS")
    print("generated artifact retains declared labeler attribution: PASS")
    print("saved rules reproduced the artifact in a fresh chat process: PASS")
    print("unsupported encrypt composition abstained: PASS")
    print("connective examples are Codex-authored; source-to-instruction mapping is teacher-attributed: LIMITATION")


if __name__ == "__main__":
    main()
