"""Teach a cited connective in chat and test an unseen held-out composition."""
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


INPUTS = ([3, 1, 2], [4, -1, 7], [0, 5, -2, 8], [-5, 9], [12], [])
CONTRAST = [0, 0]
BASE = (
    ("sort the list", "sort"),
    ("reverse the list", "reverse"),
    ("sort the values", "sort"),
    ("reverse the values", "reverse"),
    ("remove duplicate values", "unique"),
)
COMPOUNDS = (
    ("sort the list then reverse the values", "sort", "reverse"),
    ("reverse the list then sort the values", "reverse", "sort"),
)
HELD_OUT = (
    "remove duplicate values then sort the list then reverse the values")
HELD_INPUTS = ([4, 1, 4, 2], [3, 3, 1, 2, 1], [-1, -1, 2, 0, 2], [])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def apply(values: list[int], operation: str) -> list[int]:
    if operation == "sort":
        return sorted(values)
    if operation == "reverse":
        return list(reversed(values))
    if operation == "unique":
        return list(dict.fromkeys(values))
    raise ValueError(operation)


def sequence(values: list[int], operations: tuple[str, ...]) -> list[int]:
    result = list(values)
    for operation in operations:
        result = apply(result, operation)
    return result


def example_sentence(phrase: str, inputs: list[int],
                     outputs: list[int]) -> str:
    return f"For '{phrase}', {inputs} produces {outputs}."


def add_source_examples(index: CRMSResearchIndex, phrase: str,
                        document_id: str,
                        examples: list[tuple[list[int], list[int]]],
                        teaching_lines: list[str],
                        all_citations: list[str]) -> None:
    sentences = [example_sentence(phrase, inputs, outputs)
                 for inputs, outputs in examples]
    index.add_document(document_id, document_id, " ".join(sentences),
                       f"fixture/{document_id}.txt")
    for (inputs, outputs), text in zip(examples, sentences):
        hit = next(
            hit for hit in index.search(text, limit=10)
            if hit.document_id == document_id
            and index.resolve_citation(index.citation(hit)) == text)
        citation = index.citation(hit)
        all_citations.append(citation)
        input_csv = ",".join(map(str, inputs))
        output_csv = ",".join(map(str, outputs))
        teaching_lines.append(
            f"/teach-rule {phrase}|{input_csv}|{output_csv}|{citation}")


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
    return subprocess.run(command, input="\n".join([*lines, "/quit", ""]),
                          text=True, capture_output=True, cwd=root,
                          timeout=120, check=False)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-cited-sequence-") as folder:
        root = Path(folder)
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSTranslation().save(root / "translations.json")
        index = CRMSResearchIndex()
        teaching_lines: list[str] = []
        training_citations: list[str] = []
        training_document_ids: set[str] = set()

        base_inputs = [*INPUTS, CONTRAST]
        for number, (phrase, operation) in enumerate(BASE):
            examples = [(list(values), apply(list(values), operation))
                        for values in base_inputs]
            document_id = f"base-{number}-{operation}"
            training_document_ids.add(document_id)
            add_source_examples(index, phrase, document_id, examples,
                                teaching_lines, training_citations)

        for number, (phrase, first, second) in enumerate(COMPOUNDS):
            examples = [(list(values),
                         sequence(list(values), (first, second)))
                        for values in base_inputs]
            document_id = f"connective-{number}"
            training_document_ids.add(document_id)
            add_source_examples(index, phrase, document_id, examples,
                                teaching_lines, training_citations)

        # A separate source carries only evaluation material. None of its
        # citations are sent to /teach-rule.
        heldout_sentences = [
            example_sentence(HELD_OUT, values,
                             sequence(list(values), ("unique", "sort", "reverse")))
            for values in HELD_INPUTS
        ]
        index.add_document("held-out-composition", "Held-out composition",
                           " ".join(heldout_sentences),
                           "evaluation/held-out-composition.txt")
        heldout_citations = []
        for text in heldout_sentences:
            hit = next(hit for hit in index.search(text, limit=10)
                       if hit.document_id == "held-out-composition")
            citation = index.citation(hit)
            require(index.resolve_citation(citation) == text,
                    "held-out composition citation is not exact")
            heldout_citations.append(citation)
        index.save(root / "index.json")

        answer = f"Write Python code to {HELD_OUT}"
        run = launch(root, [*teaching_lines, answer,
                            "Explain that code", "Show examples for that code"])
        require(run.returncode == 0,
                f"chat exited {run.returncode}: {run.stderr}")
        require("Generated Python for '" + HELD_OUT + "'" in run.stdout,
                f"chat did not generate the unseen composition: {run.stdout[-2400:]!r}")
        require("Evidence for generated artifact" in run.stdout
                and "The cited text contains this exact numeric pair" in run.stdout,
                "chat did not expose artifact evidence or attribution limits")

        rules = CRMSModel(root / "rules.json", max_workers=1)
        expected_documents = sorted(training_document_ids)
        observed_documents = sorted({
            document_id
            for phrase in rules._examples
            for document_id in rules.example_documents(phrase)
        })
        require(observed_documents == expected_documents,
                f"trained rules have an incorrect source-document set: "
                f"{observed_documents!r}")
        require("held-out-composition" not in observed_documents,
                "held-out document leaked into the learned rule memory")

        artifact = generate_python(rules, HELD_OUT)
        require(artifact is not None,
                "held-out composition did not produce a standalone artifact")
        expected_sources = {
            citation for phrase in artifact.evidence_phrases
            for citation in rules.example_sources(phrase)
        }
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<cited-unseen-composition>", "exec"),
             namespace)
        provenance = namespace["CRMS_PROVENANCE"]
        artifact_sources = {row["source_id"]
                            for row in provenance["examples"]}
        require(artifact_sources == expected_sources
                and not (artifact_sources & set(heldout_citations)),
                "generated artifact lost training lineage or used held-out sources")
        evidence = show_generated_code_evidence(artifact)
        require(all(citation in evidence for citation in expected_sources)
                and all(citation not in evidence for citation in heldout_citations),
                "user-visible artifact evidence violates the document split")

        expected_results = [
            sequence(list(values), ("unique", "sort", "reverse"))
            for values in HELD_INPUTS
        ]
        transform = namespace["transform"]
        require([transform(values) for values in HELD_INPUTS] == expected_results
                and namespace["validate_examples"](),
                "independent held-out composition validation failed")

        incomplete = rules.predict(
            "remove duplicate values then rotate the list then reverse the values",
            [4, 1, 4, 2])
        require(incomplete.status != "ok",
                "composition with an unsupported middle stage did not abstain")
        incomplete_chat = launch(root, [
            "Write Python code to remove duplicate values then rotate the list "
            "then reverse the values",
        ])
        require(incomplete_chat.returncode == 0
                and "Generated Python" not in incomplete_chat.stdout,
                "chat emitted an artifact for the unsupported middle stage")

        # A fresh process must reuse the cited training model and reproduce the
        # same deterministic artifact without training on the held-out source.
        replay = launch(root, [answer])
        require(replay.returncode == 0
                and artifact.provenance_id in replay.stdout,
                "fresh chat restart changed or lost the composed artifact")

    print("chat learned the sequencing connective from cited examples: PASS")
    print("unseen unique→sort→reverse composition passed held-out inputs: PASS")
    print("artifact contains training citations and excludes held-out citations: PASS")
    print("chat refused an unsupported middle operation; restart was deterministic: PASS")
    print("source documents are authored fixtures, not independent publishers: LIMITATION")


if __name__ == "__main__":
    main()
