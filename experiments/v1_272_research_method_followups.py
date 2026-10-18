"""Resolve method follow-ups against the previous source without inventing why."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (
    _method_mechanism_followup, _natural_research_explanation_request,
    _render_research_explanation,
)
from crms_research import CRMSResearchIndex, CRMSSQLiteResearchIndex
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for question in ("Why does this method work?",
                     "How does that approach work?",
                     "Why does the model succeed so well?"):
        require(_method_mechanism_followup(question)
                and _natural_research_explanation_request(question),
                f"method follow-up was not recognized: {question}")
    require(not _method_mechanism_followup("Why does this paper matter?"),
            "a general question was captured as a method-mechanism follow-up")

    index = CRMSResearchIndex()
    index.add_document(
        "cause", "Vela calibration method",
        "Abstract: The Vela method improves calibration because it normalizes "
        "scores against a held-out reference set.", "cause.txt")
    index.add_document(
        "procedure", "Rho calibration method",
        "Abstract: The Rho method is used for calibration.", "procedure.txt")
    cause_hit = index.search("Vela calibration", limit=1)[0]
    cause_evidence = {"document_id": cause_hit.document_id,
                      "citation": index.citation(cause_hit),
                      "use_full_document": True}
    cause_reply = _render_research_explanation(
        index, cause_evidence, CRMSTranslation(),
        question="Why does this method work?")
    require("because it normalizes scores" in cause_reply
            and "[Source:" in cause_reply,
            f"causal source sentence was not quoted and cited: {cause_reply}")
    procedure_hit = index.search("Rho calibration", limit=1)[0]
    procedure_reply = _render_research_explanation(
        index, {"document_id": procedure_hit.document_id,
                "citation": index.citation(procedure_hit),
                "use_full_document": True},
        CRMSTranslation(), question="Why does this method work?")
    require("does not state why it works" in procedure_reply
            and "used for calibration" in procedure_reply,
            f"procedural description overstated effectiveness: {procedure_reply}")

    source_model = PROJECT / "data" / "crms_project_model_academic.sqlite"
    source_sidecar = source_model.with_name(source_model.name + ".memories")
    with tempfile.TemporaryDirectory(prefix="crms-method-followups-") as folder:
        root = Path(folder)
        model = root / source_model.name
        shutil.copy2(source_model, model)
        sidecar = model.with_name(model.name + ".memories")
        shutil.copytree(source_sidecar, sidecar)
        research = CRMSSQLiteResearchIndex(sidecar / "research.sqlite")
        try:
            research.add_document(
                "fixture:vela", "Vela calibration method",
                "Published: 2026-10-18T00:00:00Z\n"
                "Abstract: The Vela method improves calibration because it "
                "normalizes scores against a held-out reference set.",
                "https://example.test/vela")
            research.add_document(
                "fixture:rho", "Rho calibration method",
                "Published: 2026-10-19T00:00:00Z\n"
                "Abstract: The Rho method is used for calibration.",
                "https://example.test/rho")
        finally:
            research.close()
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(model),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
            "--math-session", str(root / "math.json"),
            "--translation-session", str(root / "translations.json"),
        ]
        run = subprocess.run(
            command,
            input=("What is the latest research in Vela calibration?\n"
                   "Why does this method work?\n"
                   "What is the latest research in Rho calibration?\n"
                   "Why does this method work?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=45)
        require(run.returncode == 0,
                f"chat exited {run.returncode}: {run.stderr}\n{run.stdout}")
        require("because it normalizes scores" in run.stdout
                and "does not state why it works" in run.stdout
                and run.stdout.count("fixture:vela#sha256=") == 1
                and run.stdout.count("fixture:rho#sha256=") == 1
                and "Please name the entity this pronoun refers to." not in run.stdout,
                f"chat follow-up lost source identity or overclaimed: {run.stdout}")

    print("research method follow-up diagnostic: PASS")
    print("prior source is retained; direct causal language is quoted, unsupported explanations are explicit")


if __name__ == "__main__":
    main()
