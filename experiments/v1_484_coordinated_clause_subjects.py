"""Recover explicit subjects after a coordinated clause in API prose.

Run with:
    python3 experiments/v1_484_coordinated_clause_subjects.py

The real Adam API docstring is used as a source-context regression. Its
candidate remains review-only; this does not license a yes/no answer.
"""
from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def citation(text: str) -> str:
    import hashlib
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"fixture#sha256={digest}&chars=0:{len(text)}"


def check_real_source() -> str:
    adam_module = importlib.import_module("torch.optim.adam")
    doc = inspect.getdoc(adam_module.Adam)
    require(bool(doc), "PyTorch Adam API docstring missing")
    start = doc.index("decoupled_weight_decay (bool, optional):")
    end = doc.index("\n    amsgrad", start)
    item = doc[start:end]
    proposals = propose_procedure_phrase_candidates(
        item, source_citation=citation(item))
    require(len(proposals) == 1,
            f"expected one parameter behavior candidate, got {proposals!r}")
    candidate = proposals[0]
    require(candidate.subject == "the algorithm"
            and candidate.predicate_phrase
                == "accumulate weight decay in the momentum nor variance"
            and candidate.polarity is False
            and candidate.scope_notes == ("before: condition: if True",)
            and candidate.status == "needs_review",
            f"wrong subject, polarity, condition, or review state: {candidate!r}")
    return doc


def check_boundaries() -> None:
    compound = "The input and the output will be checked."
    candidate = propose_procedure_phrase_candidates(
        compound, source_citation=citation(compound))
    require(len(candidate) == 1 and candidate[0].subject == "The input and the output",
            f"compound subject was split incorrectly: {candidate!r}")

    coordinated = (
        "If enabled, the optimizer is equivalent to AdamW and the algorithm "
        "will not accumulate weight decay.")
    candidate = propose_procedure_phrase_candidates(
        coordinated, source_citation=citation(coordinated))
    require(len(candidate) == 1 and candidate[0].subject == "the algorithm"
            and candidate[0].scope_notes == ("before: condition: If enabled",),
            f"coordinated clause/condition was not recovered: {candidate!r}")

    contrast = (
        "It must have the same shape and buffer length as the expected "
        "output, but the type (of the output) will be cast if necessary.")
    candidate = propose_procedure_phrase_candidates(
        contrast, source_citation=citation(contrast))
    require(len(candidate) == 1
            and candidate[0].subject == "the type (of the output)"
            and candidate[0].predicate_phrase == "be cast",
            f"compound object before a contrast was mis-split: {candidate!r}")


def check_fresh_chat(doc: str) -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-484-") as tmp:
        root = Path(tmp)
        index = CRMSResearchIndex()
        index.add_document(
            "torch.optim.adam.Adam", "PyTorch Adam API", doc,
            "https://pytorch.org/docs/stable/generated/torch.optim.Adam.html")
        index.save(root / "index.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSMath().save(root / "math.json")
        CRMSModel(max_workers=1).save(root / "rules.json")
        CRMSTranslation().save(root / "translations.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--math", str(root / "math.json"),
            "--rules", str(root / "rules.json"),
            "--translations", str(root / "translations.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rule-session.json"),
        ]
        process = subprocess.run(
            command, cwd=root,
            input="/suggest-procedure-phrases Adam decoupled weight decay momentum\n"
                  "/rules\n/quit\n",
            text=True, capture_output=True, timeout=60, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        require("the algorithm — 'accumulate weight decay in the momentum nor variance'"
                in process.stdout,
                f"chat omitted the recovered candidate:\n{process.stdout}")
        require("negative claim" in process.stdout
                and "Scope: before: condition: if True" in process.stdout
                and "decoupled_weight_decay (bool, optional)" in process.stdout
                and "will not accumulate weight" in process.stdout
                and "nor variance" in process.stdout,
                f"chat omitted polarity, condition, or source evidence:\n{process.stdout}")
        require("No transformation rules are committed yet." in process.stdout,
                "candidate was promoted without review")


def main() -> None:
    doc = check_real_source()
    check_boundaries()
    check_fresh_chat(doc)
    print("PASS: explicit subject recovered after a coordinated finite clause")
    print("PASS: negative polarity and the parameter condition remain attached")
    print("PASS: compound subjects remain intact")
    print("PASS: fresh chat shows the cited review-only candidate")
    print("LIMIT: this does not yet resolve 'the algorithm' to Adam for yes/no chat")


if __name__ == "__main__":
    main()
