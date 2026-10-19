"""Teach a rule through cited chat examples and test on a held-out document."""
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


TRAINING = {
    "training-a": (
        ([3, 1, 2], [1, 2, 3]),
        ([4, -1, 7], [-1, 4, 7]),
        ([0, 5, -2, 8], [-2, 0, 5, 8]),
    ),
    "training-b": (
        ([-5, 9], [-5, 9]),
        ([12], [12]),
        ([], []),
        ([0, 0], [0, 0]),
    ),
}
HELD_OUT = ([15, 3, 8, 3], [3, 3, 8, 15])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def sentence(inputs: list[int], outputs: list[int]) -> str:
    return f"Sorting {inputs} produces {outputs}."


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
                          timeout=45, check=False)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-source-disjoint-rule-") as folder:
        root = Path(folder)
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSTranslation().save(root / "translations.json")

        index = CRMSResearchIndex()
        teaching_lines: list[str] = []
        training_citations: list[str] = []
        training_doc_ids = set(TRAINING)
        for document_id, examples in TRAINING.items():
            text = " ".join(sentence(inputs, outputs)
                             for inputs, outputs in examples)
            index.add_document(document_id, document_id, text,
                               f"fixture/{document_id}.txt")
            for inputs, outputs in examples:
                expected_sentence = sentence(inputs, outputs)
                hit = next(
                    hit for hit in index.search(expected_sentence, limit=10)
                    if hit.document_id == document_id
                    and index.resolve_citation(index.citation(hit))
                    == expected_sentence)
                citation = index.citation(hit)
                training_citations.append(citation)
                teaching_lines.append(
                    f"/teach-rule sort the numbers|"
                    f"{','.join(map(str, inputs))}|"
                    f"{','.join(map(str, outputs))}|{citation}")

        holdout_sentence = sentence(*HELD_OUT)
        index.add_document("held-out", "Held-out sorting example",
                           holdout_sentence,
                           "evaluation/held-out-sorting.txt")
        holdout_hit = next(
            hit for hit in index.search(holdout_sentence, limit=10)
            if hit.document_id == "held-out")
        holdout_citation = index.citation(holdout_hit)
        require(index.resolve_citation(holdout_citation) == holdout_sentence,
                "held-out source citation is not exact")
        index.save(root / "index.json")

        request = "Write Python code to sort the numbers"
        run = launch(root, [*teaching_lines, request,
                            "Show examples for that code"])
        require(run.returncode == 0,
                f"chat exited {run.returncode}: {run.stderr}")
        require("Rule learning status: learned." in run.stdout
                and "Generated Python for 'sort the numbers'" in run.stdout,
                f"chat did not learn and generate from cited examples: "
                f"{run.stdout[-2200:]!r}")
        require("The cited text contains this exact numeric pair" in run.stdout,
                "chat omitted its attribution limitation")

        rules = CRMSModel(root / "rules.json", max_workers=1)
        require(rules.example_documents("sort the numbers")
                == sorted(training_doc_ids),
                "training rule memory includes the held-out document or misses a training document")
        held_prediction = rules.predict("sort the numbers", HELD_OUT[0])
        require(held_prediction.status == "ok"
                and held_prediction.output == HELD_OUT[1],
                f"procedure did not transfer to held-out values: {held_prediction!r}")

        artifact = generate_python(rules, "sort the numbers")
        require(artifact is not None,
                "the trained procedure did not produce a standalone artifact")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<source-disjoint-sort>", "exec"),
             namespace)
        require(namespace["transform"](HELD_OUT[0]) == HELD_OUT[1]
                and namespace["validate_examples"](),
                "generated code failed held-out or parity validation")
        artifact_sources = {
            row["source_id"]
            for row in namespace["CRMS_PROVENANCE"]["examples"]
        }
        require(artifact_sources == set(training_citations)
                and holdout_citation not in artifact_sources,
                "artifact lineage includes held-out evidence or drops training citations")
        evidence_view = show_generated_code_evidence(artifact)
        require(all(citation in evidence_view for citation in training_citations)
                and holdout_citation not in evidence_view,
                "artifact evidence display violates the source split")

        paraphrase = rules.predict("put the integers in ascending order",
                                   HELD_OUT[0])
        if paraphrase.status == "ok":
            require(paraphrase.output == HELD_OUT[1],
                    f"paraphrase route returned a wrong answer: {paraphrase!r}")
        unsupported = rules.predict("rotate the numbers", HELD_OUT[0])
        require(unsupported.status != "ok",
                "unsupported operation received a learned positive answer")

    paraphrase_result = ("correct" if paraphrase.status == "ok" else "abstained")
    print("chat learned sort from exact citations in two training documents: PASS")
    print("held-out third-document citation was excluded from rule and artifact: PASS")
    print("held-out input and standalone artifact passed exact validation: PASS")
    print(f"unseen wording probe: {paraphrase_result}; unsupported operation: abstained")
    print("fixture documents are not independent-publisher evidence: LIMITATION")


if __name__ == "__main__":
    main()
