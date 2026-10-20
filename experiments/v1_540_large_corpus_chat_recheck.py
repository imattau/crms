"""Re-run the large-corpus chat audit into a new, isolated report.

The original audit path may be user-edited, so this wrapper never writes to
that report. Run with: python3 experiments/v1_540_large_corpus_chat_recheck.py
"""

from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "experiments"))

import v1_251_large_corpus_chat_stress as audit  # noqa: E402


def main() -> None:
    audit.REPORT_PATH = (
        PROJECT / "experiments" / "reports"
        / "v1_540_large_corpus_chat_recheck.json")
    audit.main()


if __name__ == "__main__":
    main()
