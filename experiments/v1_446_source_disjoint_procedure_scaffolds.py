"""Require complete document-disjoint provenance for procedure scaffolds.

The ordinary scaffold route remains compatible. Its stricter mode must use
resolved source citations for every example and instruction label, keep the
held-out documents out of training lineage, and remain report-only.
"""
from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


INPUTS = ([1, 4, -2], [5, -3, 8], [0, 6, -7], [9, 2, 1])
PHRASES = (("alpha", 1), ("bravo", 2), ("charlie", 3), ("delta", 4))


def cite(index: CRMSResearchIndex, document_id: str, text: str) -> str:
    index.add_document(document_id, document_id, text, f"{document_id}.txt")
    hit = next((item for item in index.search(text, limit=20, context_chars=0)
                if item.document_id == document_id), None)
    require(hit is not None, f"indexed evidence was not searchable: {document_id}")
    citation = index.citation(hit)
    require(index.resolve_citation(citation) == text,
            f"citation did not resolve to exact source text: {document_id}")
    return citation


def make_model(*, shared_document: bool = False,
               incomplete_phrase: str | None = None):
    index = CRMSResearchIndex()
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    for phrase, offset in PHRASES:
        source_suffix = "shared" if shared_document else phrase
        if shared_document:
            # The strict provenance path treats citation prefixes as document
            # identity; fake hashes are sufficient for this rejection case.
            instruction_source = "instruction-shared#sha256=shared"
            example_source = "examples-shared#sha256=shared"
        else:
            instruction_source = cite(
                index, f"instruction-{source_suffix}",
                f"For this example, {phrase} means add {offset} to each value, "
                "then reverse the list.")
            example_source = cite(
                index, f"examples-{source_suffix}",
                f"Examples for {phrase} demonstrate the list transformation "
                f"with offset {offset}.")
        examples = [
            (list(values), list(reversed([value + offset for value in values])))
            for values in INPUTS
        ]
        instruction_sources = (
            [None] * len(examples) if phrase == incomplete_phrase
            else [instruction_source] * len(examples))
        result = model.teach(
            phrase, examples,
            source_ids=[example_source] * len(examples),
            labeler_ids=["codex:source-rule-labeler-v1"] * len(examples),
            instruction_source_ids=instruction_sources)
        require(result.status == "learned" and result.procedure is not None,
                f"could not learn fixture procedure {phrase}: {result}")
    return model, index


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-source-disjoint-") as folder:
        model, index = make_model()
        before = model.list_rules()
        default = model.propose_procedure_scaffolds()
        strict = model.propose_procedure_scaffolds(
            require_source_disjoint=True)
        require(default and strict,
                "complete, document-disjoint evidence did not propose a scaffold")
        require(all(not proposal["require_source_disjoint"]
                    for proposal in default),
                "default proposal unexpectedly claimed source independence")
        proposal = strict[0]
        require(proposal["require_source_disjoint"]
                and proposal["held_out_valid"] and proposal["mdl_gate_passed"]
                and proposal["report_only"],
                f"strict candidate did not satisfy its review-only gates: {proposal}")
        training = [row for row in proposal["lineage"]
                    if row["role"] == "training"]
        heldout = [row for row in proposal["lineage"]
                   if row["role"] == "held_out"]
        training_documents = set().union(*(
            set(row["source_provenance"]["source_documents"])
            for row in training))
        heldout_documents = set().union(*(
            set(row["source_provenance"]["source_documents"])
            for row in heldout))
        require(training_documents.isdisjoint(heldout_documents),
                "held-out phrase shares a source document with training")
        require(len(heldout) == 1
                and all(row["source_provenance"]["labeler_ids"]
                        == ["codex:source-rule-labeler-v1"] * row["example_count"]
                        for row in proposal["lineage"]),
                "lineage lost held-out role or labeler contribution")
        require(all(index.resolve_citation(source)
                    for row in proposal["lineage"]
                    for source in (
                        row["source_provenance"]["example_source_ids"]
                        + row["source_provenance"]["instruction_source_ids"])),
                "proposal contains a stale or unresolved source citation")
        require(model.retrieve_procedure_scaffold(
                    proposal["artifact_id"], require_source_disjoint=True)
                == proposal
                and model.retrieve_procedure_scaffold(
                    proposal["artifact_id"]) is None,
                "artifact retrieval did not preserve its strict validation policy")
        require(model.list_rules() == before,
                "report-only proposal changed the active procedure library")

        root = Path(folder)
        rules_path = root / "rules.json"
        index_path = root / "index.json"
        model.save(rules_path)
        index.save(index_path)
        cli = subprocess.run(
            [sys.executable,
             str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(rules_path),
             "--rule-session", str(root / "rule-session.json")],
            input="/procedure-scaffolds --source-disjoint\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(cli.returncode == 0
                and "citations resolved" in cli.stdout
                and "documents disjoint" in cli.stdout
                and "Publisher independence is not established" in cli.stdout
                and "Report only: no rules or grammar changed." in cli.stdout,
                f"chat did not expose strict source validation honestly:\n"
                f"{cli.stdout}\n{cli.stderr}")

        shared, _ = make_model(shared_document=True)
        require(not shared.propose_procedure_scaffolds(
                    require_source_disjoint=True),
                "source overlap was accepted as a disjoint holdout")
        incomplete, _ = make_model(incomplete_phrase="bravo")
        require(not incomplete.propose_procedure_scaffolds(
                    require_source_disjoint=True),
                "incomplete label provenance was accepted for strict validation")
        require(incomplete.propose_procedure_scaffolds(),
                "strict provenance gate changed the existing default route")

    print("source-disjoint procedure scaffold proposal: PASS")
    print("complete citations, distinct train/holdout documents, and labeler lineage: PASS")
    print("overlapping sources and incomplete provenance refused: PASS")
    print("strict retrieval policy and report-only behavior: PASS")
    print("chat inspection resolves citations and discloses the publisher limit: PASS")
    print("scope: validates a held-out phrase scaffold, not autonomous prose extraction")


if __name__ == "__main__":
    main()
