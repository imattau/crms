"""Teach a list operation in chat, then reuse it in a reasoned request.

Unlike the API-level procedure experiments, this runs the real `/teach-rule`
interaction, including contrastive probes requested by CRMS. The teacher is
explicitly identified; labels are supervision, not independent validation.
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

from v1_500_learned_and_reasoned_composition import learn_components
from v1_502_reasoned_numeric_aggregation import build_knowledge, sum_training_data
from v1_503_sum_first_reasoned_composition import teach_sum_phrase
from v1_497_composition_derived_practice import require, run_chat
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


PHRASE = "add up the ones she reaches"
LABELER = "codex:interactive-pronoun-sum-teacher"
REQUEST = (
    "Mira reaches some of 23, 5, 23, and 8. Add up the ones she reaches."
)
UNKNOWN = (
    "Mira reaches some of 23, 5, 11, and 8. Add up the ones she reaches."
)
EXAMPLES = (
    ([2, 3], [5]),
    ([5, 6, 7, 1, 2, 3, 4], [28]),
    ([-1, -1, 1], [-1]),
    ([], [0]),
)


def chat_command(root: Path, knowledge_path: Path, rules_path: Path,
                 index_path: Path) -> list[str]:
    return [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path), "--rules", str(rules_path),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--index", str(index_path),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--candidate-session", str(root / "candidates.json"),
    ]


def teach_command(values: list[int], outputs: list[int]) -> str:
    return (f"/teach-rule {PHRASE}|{','.join(map(str, values))}|"
            f"{','.join(map(str, outputs))}||{LABELER}")


def main() -> None:
    knowledge = build_knowledge()
    procedures = learn_components()
    sum_training_data(procedures)
    teach_sum_phrase(procedures)
    require(compose_verified_filter(REQUEST, knowledge, procedures) is None,
            "the two-clause request worked before its operation phrase was taught")

    with tempfile.TemporaryDirectory(prefix="crms-interactive-rule-learning-") as folder:
        root = Path(folder)
        knowledge_path = root / "model.sqlite3"
        rules_path = root / "rules.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(rules_path)
        CRMSResearchIndex().save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        input_lines = [teach_command(values, outputs)
                       for values, outputs in EXAMPLES]
        input_lines.extend((REQUEST, "why?", "/quit"))
        learned = subprocess.run(
            chat_command(root, knowledge_path, rules_path, index_path),
            input="\n".join(input_lines) + "\n", text=True,
            capture_output=True, cwd=root, timeout=60, check=False)
        learned_output = learned.stdout + learned.stderr
        require(learned.returncode == 0 and "Traceback" not in learned_output
                and learned_output.count("Rule learning status: learned.") == 1
                and "behaviorally distinct procedures still fit" in learned_output
                and "Their total is 51." in learned_output
                and "mira:record-23" in learned_output
                and "mira:record-5" in learned_output
                and "mira:record-8-negative" in learned_output
                and LABELER in learned_output
                and "Because Mira" in learned_output,
                f"chat teaching did not learn and explain the composition:\n"
                f"{learned_output}")

        # The learned procedure must transfer after restart, while incomplete
        # input remains blocked by the proof gate.
        fresh = root / "fresh"
        fresh.mkdir()
        for path in (knowledge_path, rules_path, index_path,
                     root / "math.json", root / "translations.json"):
            shutil.copy2(path, fresh / path.name)
        restored = run_chat(
            fresh, fresh / knowledge_path.name, fresh / rules_path.name,
            fresh / index_path.name, (REQUEST, "why?"))
        require("Their total is 51." in restored
                and "codex:interactive-pronoun-sum-teacher" in restored
                and "Because Mira" in restored
                and "Traceback" not in restored,
                f"fresh process lost the learned phrase or its lineage:\n{restored}")

        unknown_root = root / "unknown"
        unknown_root.mkdir()
        for path in (knowledge_path, rules_path, index_path,
                     root / "math.json", root / "translations.json"):
            shutil.copy2(path, unknown_root / path.name)
        unknown = run_chat(
            unknown_root, unknown_root / knowledge_path.name,
            unknown_root / rules_path.name, unknown_root / index_path.name,
            (UNKNOWN,))
        require("I can't determine whether 11 satisfy Mira reaches" in unknown
                and "Their total is" not in unknown,
                f"unknown value entered the learned aggregate:\n{unknown}")

    checked = CRMSMath().ask("What is 23 + 5 + 23?")
    require(checked is not None and checked.status == "answered"
            and str(checked.value) == "51",
            f"independent arithmetic disagreed with the result: {checked}")

    print("unlearned two-clause operation abstains before chat teaching: PASS")
    print("real chat requests contrastive examples and accepts teacher outputs: PASS")
    print("learned phrase composes with verified relation facts and explains its proof: PASS")
    print("copied model retains the learned phrase and labeler lineage: PASS")
    print("unknown list members block the aggregate; independent arithmetic agrees: PASS")
    print("scope: teacher-supervised phrase learning, not autonomous intent resolution")


if __name__ == "__main__":
    main()
