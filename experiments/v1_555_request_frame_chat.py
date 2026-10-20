"""End-to-end chat checks for learned request frames.

The chat process is run with the transitional regex fallback disabled. Seeded
frames answer, unknown wording does not, and a frame taught in one process
survives a fresh process.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_500_learned_and_reasoned_composition import learn_components  # noqa: E402
from v1_502_reasoned_numeric_aggregation import (  # noqa: E402
    build_knowledge, sum_training_data,
)
from v1_503_sum_first_reasoned_composition import teach_sum_phrase  # noqa: E402

from crms_math import CRMSMath  # noqa: E402
from crms_research import CRMSResearchIndex  # noqa: E402
from crms_translation import CRMSTranslation  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(root: Path, knowledge_path: Path, procedures_path: Path,
             index_path: Path, frames_path: Path,
             lines: tuple[str, ...]) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path),
        "--rules", str(procedures_path),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--index", str(index_path),
        "--request-frames", str(frames_path),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
    ]
    result = subprocess.run(
        command, input="\n".join((*lines, "/quit", "")), text=True,
        capture_output=True, cwd=root, timeout=60, check=False)
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"frame chat failed:\n{output}")
    return output


def main() -> None:
    knowledge = build_knowledge()
    procedures = learn_components()
    sum_training_data(procedures)
    teach_sum_phrase(procedures)
    index = CRMSResearchIndex()
    with tempfile.TemporaryDirectory(prefix="crms-frame-chat-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.sqlite3"
        procedures_path = root / "rules.json"
        index_path = root / "sources.json"
        frames_path = root / "frames.json"
        knowledge.save(knowledge_path)
        procedures.save(procedures_path)
        index.save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        seeded = run_chat(
            root, knowledge_path, procedures_path, index_path, frames_path,
            ("Which values in 23, 5, 23, and 8 does Mira reach, and what do "
             "they sum to?",))
        require("Their total is 51." in seeded,
                f"seeded frame did not answer in chat:\n{seeded}")

        unknown = run_chat(
            root, knowledge_path, procedures_path, index_path, frames_path,
            ("Which numbers in 23, 5, and 8 does Mira reach, and what do they "
             "sum to?",))
        require("Part 1 of 2: I don't know this" in unknown
                and "CRMS> Verified values satisfying" not in unknown
                and "CRMS> Their total is" not in unknown,
                f"unlicensed wording was answered without a frame:\n{unknown}")

        taught = run_chat(
            root, knowledge_path, procedures_path, index_path, frames_path,
            ("/teach-frame select-then-procedure|Send {values:integer-list:1, "
             "2} to {claim:claim:Mira reaches}.|lesson:frame:1|sum every value",
             "/teach-frame select-then-procedure|Send {values:integer-list:3, "
             "4} to {claim:claim:Nia reaches}.|lesson:frame:2|sum every value",
             "Send 23, 5 to Mira reaches.",
             "/frames"))
        require("Request-frame learning status: need_more_examples." in taught
                and "Request-frame learning status: licensed." in taught,
                f"frame teaching did not require and accept varied examples:\n{taught}")
        require("Their total is 28." in taught,
                f"taught frame did not answer:\n{taught}")
        require("send {values:integer-list} to {claim:claim}" in taught,
                f"taught frame is not inspectable:\n{taught}")
        require("Registry rule request-frame-" in taught
                and "Governed frames:" in taught
                and "state=active" in taught
                and "uses=1" in taught
                and "successes=1" in taught,
                f"taught frame did not enter the governed registry:\n{taught}")

        reloaded = run_chat(
            root, knowledge_path, procedures_path, index_path, frames_path,
            ("Send 23, 5 to Mira reaches.",))
        require("Their total is 28." in reloaded,
                f"taught frame did not survive a fresh process:\n{reloaded}")

    print("seeded frame answers in the frames-only chat path: PASS")
    print("unlicensed wording does not enter composition: PASS")
    print("taught frame requires variation, answers, lists, and reloads: PASS")


if __name__ == "__main__":
    main()
