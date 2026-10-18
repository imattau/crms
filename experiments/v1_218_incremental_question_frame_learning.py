"""Check grounded conversational extension of an existing question frame."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


PROJECT = Path(__file__).resolve().parents[1]


def run_chat(root: Path, turns: tuple[str, ...]) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / "knowledge.json"),
        "--index", str(root / "index.json"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rules", str(root / "rules.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--math", str(root / "math.json"),
        "--math-session", str(root / "math-session.json"),
        "--translations", str(root / "translations.json"),
        "--translation-session", str(root / "translation-session.json"),
        "--candidate-session", str(root / "candidates.json"),
    ]
    result = subprocess.run(
        command, input="\n".join((*turns, "/quit")) + "\n",
        text=True, capture_output=True, check=False, timeout=30)
    if result.returncode:
        raise SystemExit(
            f"chat exited {result.returncode}: {result.stderr}\n{result.stdout}")
    return result.stdout


def seed(root: Path) -> None:
    knowledge = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Ada Lovelace", "the Analytical Engine", "ada"),
            ("Grace Hopper", "the Compiler", "grace"),
            ("Katherine Johnson", "the trajectory table", "katherine")):
        knowledge.add_fact(subject, "designed", obj, source)
    knowledge.save(root / "knowledge.json")


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        seed(root)
        taught = run_chat(root, (
            'Teach a question frame from examples: '
            '"Who designed the Analytical Engine?" => "Ada Lovelace"; '
            '"Who designed the Compiler?" => "Grace Hopper"',
            'Teach an additional question example: '
            '"Who designed the trajectory table?" => "Katherine Johnson"',
            "Who designed the trajectory table?",
        ))
        if ("Question frame licensed from 2 fact-backed examples" not in taught
                or "Additional question example added to the licensed frame" not in taught
                or not ("Answer: Katherine Johnson" in taught
                        or "Katherine Johnson designed the trajectory table."
                        in taught)):
            raise SystemExit(f"incremental question example did not transfer: {taught}")
        restored = CRMSKnowledgeBase.load(root / "knowledge.json")
        answer = restored.ask("Who designed the trajectory table?")
        if answer.status != "answered" or answer.answer != "Katherine Johnson":
            raise SystemExit(f"incremental frame did not persist: {answer}")

        rejected_root = Path(folder) / "rejected"
        rejected_root.mkdir()
        seed(rejected_root)
        rejected = run_chat(rejected_root, (
            'Teach an additional question example: '
            '"Who designed the trajectory table?" => "Katherine Johnson"',
        ))
        if "No already licensed exact question frame" not in rejected:
            raise SystemExit(f"a new frame was learned from one example: {rejected}")
        unchanged = CRMSKnowledgeBase.load(rejected_root / "knowledge.json")
        if unchanged._question_examples:
            raise SystemExit("rejected incremental example changed question memory")

        invalid_root = Path(folder) / "invalid"
        invalid_root.mkdir()
        seed(invalid_root)
        invalid = run_chat(invalid_root, (
            'Teach a question frame from examples: '
            '"Who designed the Analytical Engine?" => "Ada Lovelace"; '
            '"Who designed the Compiler?" => "Grace Hopper"',
            'Teach one more question example: '
            '"Who designed the imaginary device?" => "Katherine Johnson"',
        ))
        if "does not identify one directly supported fact" not in invalid:
            raise SystemExit(f"an unsupported example was accepted: {invalid}")
        still_licensed = CRMSKnowledgeBase.load(invalid_root / "knowledge.json")
        if still_licensed.ask("Who designed the Analytical Engine?").answer != "Ada Lovelace":
            raise SystemExit("rejected example damaged the existing licensed frame")

        derived_root = Path(folder) / "derived"
        derived_root.mkdir()
        derived = CRMSKnowledgeBase()
        derived.add_fact("A", "ancestor", "C", "base-ac")
        derived.add_fact("D", "ancestor", "F", "base-df")
        for parent, child, source in (
                ("A", "B", "parent-ab"), ("B", "C", "parent-bc"),
                ("D", "E", "parent-de"), ("E", "F", "parent-ef"),
                ("G", "H", "parent-gh"), ("H", "I", "parent-hi")):
            derived.add_fact(parent, "parent", child, source)
        derived.add_inference_rule("transitive", "parent", "parent", "ancestor")
        derived.save(derived_root / "knowledge.json")
        proof_backed = run_chat(derived_root, (
            "/teach-question Who is an ancestor of C?|ancestor|subject|C|A",
            "/teach-question Who is an ancestor of F?|ancestor|subject|F|D",
            'Teach an additional question example: '
            '"Who is an ancestor of I?" => "G"',
            "Who is an ancestor of I?",
        ))
        if ("Additional question example added to the licensed frame" not in proof_backed
                or not ("Answer: G" in proof_backed
                        or "G is an ancestor of I." in proof_backed)):
            raise SystemExit(f"proof-backed incremental example failed: {proof_backed}")
        derived_restored = CRMSKnowledgeBase.load(derived_root / "knowledge.json")
        derived_answer = derived_restored.ask("Who is an ancestor of I?")
        if (derived_answer.status != "answered" or derived_answer.answer != "G"
                or not derived_answer.inference_proofs):
            raise SystemExit(f"proof-backed example did not persist: {derived_answer}")

    print("incremental question-frame learning diagnostic: PASS")
    print("existing-frame requirement, direct fact grounding, held-out entity transfer, "
          "proof-backed transfer, transactional rejection, and persistence: PASS")


if __name__ == "__main__":
    main()
