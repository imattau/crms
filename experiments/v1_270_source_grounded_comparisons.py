"""Require explicit source contrast for natural-language comparison answers."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _answer_contrast_from_sources, _natural_contrast_pair
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    question = "What is the difference between supervised and unsupervised learning?"
    require(_natural_contrast_pair(question) ==
            ("supervised", "unsupervised learning"),
            "explicit difference question was not parsed")
    require(_natural_contrast_pair("What is supervised learning?") is None,
            "definition question was captured as a comparison")

    contrast = CRMSResearchIndex()
    contrast.add_document(
        "contrast", "Learning Paradigms",
        "Abstract: Supervised learning uses labeled examples, whereas "
        "unsupervised learning discovers structure without labels.",
        "contrast.txt")
    direct = _answer_contrast_from_sources(
        contrast, "supervised learning", "unsupervised learning")
    require("whereas" in direct and "[Source:" in direct,
            f"explicit source contrast was not quoted and cited: {direct}")

    comention = CRMSResearchIndex()
    comention.add_document(
        "comention", "Learning Paradigms",
        "Abstract: Supervised learning and unsupervised learning are both "
        "machine learning methods.", "comention.txt")
    abstained = _answer_contrast_from_sources(
        comention, "supervised learning", "unsupervised learning")
    require("can't establish their difference" in abstained
            and "Source:" in abstained,
            f"co-mention was treated as a comparison: {abstained}")

    source_model = PROJECT / "data" / "crms_project_model_academic.sqlite"
    source_sidecar = source_model.with_name(source_model.name + ".memories")
    with tempfile.TemporaryDirectory(prefix="crms-source-comparison-") as folder:
        root = Path(folder)
        model = root / source_model.name
        shutil.copy2(source_model, model)
        shutil.copytree(source_sidecar, model.with_name(model.name + ".memories"))
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(model),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
            "--math-session", str(root / "math.json"),
            "--translation-session", str(root / "translations.json"),
        ]
        result = subprocess.run(
            command, input=question + "\n/quit\n", text=True,
            capture_output=True, check=False, timeout=45)
        require(result.returncode == 0,
                f"chat exited {result.returncode}: {result.stderr}")
        require("Semi-supervised Learning From Demonstration" in result.stdout
                and "can't establish their difference" in result.stdout,
                f"live co-mention was not labeled as insufficient comparison evidence: {result.stdout}")

    print("source-grounded comparison diagnostic: PASS")
    print("explicit contrast sentences are quoted; co-mentions are cited but do not become comparisons")


if __name__ == "__main__":
    main()
