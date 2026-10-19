"""Check explicit, fact-backed synonym wording transfers by learned frame."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _suggest_fact_backed_question_example
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-319-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        kb = CRMSKnowledgeBase()
        examples = (
            ("Mara Vell", "Orrin Engine"),
            ("Nema Tor", "Vesk Engine"),
            ("Rila Sen", "Tavel Compass"),
            ("Miri Sol", "Savel Compass"),
        )
        for number, (subject, obj) in enumerate(examples):
            kb.add_fact(subject, "created", obj, f"fixture:created:{number}")
        for number in range(2_000):
            kb.add_fact(f"Archive Person {number}", "mentions",
                        f"Archive Item {number}", f"fixture:noise:{number}")
        for subject, obj in examples[:2]:
            kb.teach_question(
                f"Who created {obj}?", relation="created",
                answer_field="subject", bound_entity=obj, answer=subject)
        expected_prompt = _suggest_fact_backed_question_example(
            kb, "Who made Tavel Compass?")
        if (expected_prompt is None
                or '=> "Rila Sen"' not in expected_prompt
                or len(kb._facts_for_object("Tavel Compass")) != 1):
            raise SystemExit("memory object index did not find the grounded learning example")
        kb.save(knowledge_path)

        sqlite_kb = CRMSKnowledgeBase.load(
            knowledge_path, fact_db=root / "facts.sqlite")
        sqlite_prompt = _suggest_fact_backed_question_example(
            sqlite_kb, "Who made Tavel Compass?")
        if (sqlite_prompt != expected_prompt
                or len(sqlite_kb._facts_for_object("Tavel Compass")) != 1):
            raise SystemExit("SQLite object index diverged on the learning prompt")
        sqlite_kb.close()

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(root / "index.sqlite"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math", str(root / "math.json"),
            "--math-session", str(root / "math-session.json"),
            "--translations", str(root / "translations.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        run = subprocess.run(
            command,
            input=(
                "Who made Tavel Compass?\n"
                'Teach an additional question example: '
                '"Who made Tavel Compass?" => "Rila Sen"\n'
                "Who made Savel Compass?\n"
                "Who crafted Savel Compass?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = run.stdout + run.stderr
        if run.returncode or "Traceback" in output:
            raise SystemExit(f"chat failed while learning the added wording:\n{output}")
        for required in (
                "I know Rila Sen — created → Tavel Compass",
                'Teach an additional question example: "Who made Tavel Compass?" => "Rila Sen"',
                "Additional question example added to the licensed frame",
                "Miri Sol created Savel Compass.",
                "I haven't learned whether ‘crafted’ has that meaning."):
            if required not in output:
                raise SystemExit(f"chat omitted {required!r}:\n{output}")

        restored = CRMSKnowledgeBase.load(knowledge_path)
        learned = restored.ask("Who made Savel Compass?")
        unsupported = restored.ask("Who crafted Savel Compass?")
        if learned.status != "answered" or learned.answer != "Miri Sol":
            raise SystemExit(f"learned wording failed after save/load: {learned}")
        if unsupported.status == "answered":
            raise SystemExit("unlicensed lexical synonym was answered")
        print("PASS: one fact-backed additional example teaches 'made' for the licensed created relation")
        print("PASS: learned question frame transfers to a separate entity and survives reload")
        print("PASS: the unlicensed 'crafted' wording still abstains")


if __name__ == "__main__":
    main()
