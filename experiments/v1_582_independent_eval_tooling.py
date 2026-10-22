"""Phase 12: checks of the independent-evaluation tooling on synthetic ratings."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_independent_eval import judge_report, kappa, oracle_label, rating_sheet, summarise  # noqa: E402


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(message)


def main() -> None:
    items = [
        {"id": "A1", "corpus": "A", "question": "Who wrote X?", "answerable": True, "gold": "Ann Lee", "support": "Ann Lee wrote X."},
        {"id": "A2", "corpus": "A", "question": "When was Y built?", "answerable": True, "gold": "1901", "support": "Y was built in 1901."},
        {"id": "B1", "corpus": "B", "question": "Who funded Z?", "answerable": False, "gold": "", "support": ""},
        {"id": "B2", "corpus": "B", "question": "What is W?", "answerable": True, "gold": "a method", "support": "W is a method."},
    ]
    answers = ["Ann Lee wrote X.", "Y was built in 1850.", "I don't know this from the sources.", "Bob funded it."]
    labels = [oracle_label(i, a) for i, a in zip(items, answers)]
    require(labels == ["correct", "wrong", "abstain", "wrong"], labels)
    require(oracle_label(items[2], "A fund paid for it.") == "wrong", "answer to unanswerable must be wrong")
    s = summarise(items, labels)
    require(s["overall"]["correct"] == 1 and s["overall"]["wrong"] == 2 and s["overall"]["abstain"] == 1, s)
    require(s["B"]["unsafe_on_unanswerable"] == 0 and s["overall"]["unanswerable"] == 1, s)
    require(kappa(["a", "a", "b", "b"], ["a", "a", "b", "b"])["kappa"] == 1.0, "perfect agreement")
    require(kappa(["a", "b", "a", "b"], ["b", "a", "b", "a"])["kappa"] == -1.0, "perfect disagreement")
    sheet = rating_sheet(items, answers, ["s"] * 4, [0, 2])
    require("gold" not in sheet[0] and "oracle" not in str(sheet[0]), "sheet must not leak the oracle label")
    report = judge_report(items, answers, dict(enumerate(labels)), dict(enumerate(labels)))
    require(report["judge_vs_judge"]["kappa"] == 1.0 and report["model_validated"], report)
    print("Phase 12 independent-evaluation tooling passed")


if __name__ == "__main__":
    main()
