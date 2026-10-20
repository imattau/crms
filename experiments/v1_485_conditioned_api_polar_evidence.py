"""Answer a bounded source-only yes/no question with an explicit API condition.

Run with:
    python3 experiments/v1_485_conditioned_api_polar_evidence.py

The match remains quoted source evidence, never an accepted fact. It only
binds a generic statement subject to a unique API title when the user states
the same explicit true/enabled parameter condition.
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

from crms_chat import _natural_polar_claim, _natural_polar_evidence
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


QUESTION = (
    "Does Adam accumulate weight decay in the momentum with "
    "decoupled weight decay enabled?")
NO_CONDITION_QUESTION = "Does Adam accumulate weight decay in the momentum?"
WRONG_CONDITION_QUESTION = (
    "Does Adam accumulate weight decay in the momentum with AdamW enabled?")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def adam_doc() -> str:
    try:
        module = importlib.import_module("torch.optim.adam")
    except ImportError as exc:
        raise SystemExit("PyTorch is required for this source replay") from exc
    doc = inspect.getdoc(module.Adam)
    require(bool(doc), "installed Adam API docstring is missing")
    return doc


def add_adam(index: CRMSResearchIndex, document_id: str, title: str,
             text: str) -> None:
    index.add_document(
        document_id, title, text,
        "https://pytorch.org/docs/stable/generated/torch.optim.Adam.html")


def check_source_matching(doc: str) -> None:
    index = CRMSResearchIndex()
    add_adam(index, "torch.optim.adam.Adam", "PyTorch Adam API", doc)
    knowledge = CRMSKnowledgeBase()

    claim = _natural_polar_claim(QUESTION)
    require(claim is not None, "yes/no question did not parse")
    matches = _natural_polar_evidence(
        knowledge, index, claim, question=QUESTION)
    require(len(matches) == 1 and matches[0].polarity is False,
            f"explicit true condition should produce one negative source claim: {matches!r}")
    candidate = matches[0]
    require(candidate.subject == "Adam"
            and candidate.relation == "accumulate"
            and candidate.source.startswith("torch.optim.adam.Adam#sha256=")
            and index.resolve_citation(candidate.source) == candidate.sentence
            and "if True" in candidate.sentence
            and candidate.language_evidence[0]["kind"]
                == "conditioned_api_source_claim",
            f"source binding, condition, or provenance missing: {candidate!r}")

    for question in (NO_CONDITION_QUESTION, WRONG_CONDITION_QUESTION):
        parsed = _natural_polar_claim(question)
        require(parsed is not None, f"control question did not parse: {question}")
        require(not _natural_polar_evidence(
            knowledge, index, parsed, question=question),
            f"source answered without the matching explicit condition: {question}")

    for question in (
            "Does Adam accumulate weight decay in the momentum when "
            "decoupled weight decay is enabled?",
            "Does Adam accumulate weight decay in the momentum if "
            "decoupled_weight_decay is True?"):
        parsed = _natural_polar_claim(question)
        require(parsed is not None and _natural_polar_evidence(
            knowledge, index, parsed, question=question),
            f"equivalent explicit condition wording was not recognized: {question}")

    conflict_index = CRMSResearchIndex()
    add_adam(conflict_index, "adam-negative", "PyTorch Adam API", doc)
    positive_doc = doc.replace(
        "will not accumulate weight", "will accumulate weight", 1)
    add_adam(conflict_index, "adam-positive", "PyTorch Adam API", positive_doc)
    require(not _natural_polar_evidence(
        knowledge, conflict_index, claim, question=QUESTION),
        "ambiguous duplicate API titles must not resolve to one polarity")


def check_fresh_chat(doc: str) -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-485-") as tmp:
        root = Path(tmp)
        index = CRMSResearchIndex()
        add_adam(index, "torch.optim.adam.Adam", "PyTorch Adam API", doc)
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
            input=QUESTION + "\n" + NO_CONDITION_QUESTION + "\n/quit\n",
            text=True, capture_output=True, timeout=60, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        require("The source states no:" in process.stdout
                and "quoted evidence, not an accepted fact" in process.stdout
                and "will not accumulate weight" in process.stdout
                and "if True" in process.stdout,
                f"chat did not give conditional, cited source answer:\n{process.stdout}")
        require("I don't have a direct source statement for this exact proposition"
                in process.stdout,
                "unqualified question should still abstain")
        require("No transformation rules are committed yet." not in process.stdout,
                "polar source answer unexpectedly entered a procedure rule")


def main() -> None:
    doc = adam_doc()
    check_source_matching(doc)
    check_fresh_chat(doc)
    print("PASS: unique API title binds the generic source subject")
    print("PASS: answer requires the same explicit true/enabled parameter condition")
    print("PASS: duplicate API-title conflict and missing/wrong conditions abstain")
    print("PASS: fresh chat answers no with the source quotation and provenance label")
    print("LIMIT: source-only evidence remains unaccepted and scope-specific")


if __name__ == "__main__":
    main()
