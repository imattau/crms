"""Keep conditional ``when`` questions distinct from calendar-date questions.

Run with:
    python3 experiments/v1_483_when_condition_evidence_gate.py

This reproduces a real PyTorch source-chat failure, checks the deterministic
evidence gate directly, and verifies the repaired route in a clean process.
"""
from __future__ import annotations

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
from crms_nl_gate import gate_quoted_evidence
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def check_gate() -> None:
    cases = (
        ("When does an LSTM use projections?",
         "If ``proj_size > 0`` is specified, LSTM with projections will be used.",
         True),
        ("When was Marie Curie born?",
         "Marie Curie was born in 1867.", True),
        ("When does the server retry?",
         "The server retries after receiving a timeout.", True),
        ("When does an LSTM use projections?",
         "LSTM supports projections and uses them in sequence processing.",
         False),
        ("When does the server retry?",
         "The server monitors requests and records failures.", False),
    )
    for question, sentence, expected in cases:
        result = gate_quoted_evidence(
            question, [{"text": sentence, "citation": "fixture"}])
        accepted = result["status"] == "accepted"
        require(accepted is expected,
                f"wrong evidence-gate result for {question!r}: {result!r}")


def check_fresh_chat() -> None:
    try:
        import torch
    except ImportError as exc:
        raise SystemExit("PyTorch is required for this real-source replay") from exc
    document = inspect.getdoc(torch.nn.LSTM)
    require(bool(document), "installed torch.nn.LSTM docstring is missing")

    with tempfile.TemporaryDirectory(prefix="crms-v1-483-") as tmp:
        root = Path(tmp)
        index = CRMSResearchIndex()
        index.add_document(
            "torch.nn.LSTM", "PyTorch LSTM API", document,
            "https://pytorch.org/docs/stable/generated/torch.nn.LSTM.html")
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
            input="When does an LSTM use projections?\n/quit\n",
            text=True, capture_output=True, timeout=60, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        require("quoted evidence, not an accepted fact" in process.stdout
                and "If ``> 0``, will use LSTM with projections" in process.stdout,
                f"fresh chat did not quote the conditional evidence:\n{process.stdout}")
        require("no year stated" not in process.stdout,
                "conditional when question was still treated as a date request")


def main() -> None:
    check_gate()
    check_fresh_chat()
    print("PASS: conditional, temporal, and year-specific when evidence routes")
    print("PASS: unrelated or non-temporal evidence is rejected")
    print("PASS: clean-process PyTorch chat returns cited conditional evidence")
    print("LIMIT: source-only response remains quoted evidence, not an accepted fact")


if __name__ == "__main__":
    main()
