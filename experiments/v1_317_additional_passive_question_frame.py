"""Check that a fact-backed passive example extends a licensed active frame."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-317-") as folder:
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
        for subject, obj in examples[:2]:
            kb.teach_question(
                f"Who created {obj}?", relation="created",
                answer_field="subject", bound_entity=obj, answer=subject)
        kb.save(knowledge_path)

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
        transcript = subprocess.run(
            command,
            input=(
                'Teach an additional question example: '
                '"Tavel Compass was created by whom?" => "Rila Sen"\n'
                "Savel Compass was created by whom?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = transcript.stdout + transcript.stderr
        if transcript.returncode or "Traceback" in output:
            raise SystemExit(f"chat failed during passive-frame teaching:\n{output}")
        if "Additional question example added to the licensed frame" not in output:
            raise SystemExit(f"passive example was not accepted:\n{output}")
        if "Miri Sol created Savel Compass." not in output:
            raise SystemExit(f"new passive frame did not answer from its example:\n{output}")

        restored = CRMSKnowledgeBase.load(knowledge_path)
        result = restored.ask("Savel Compass was created by whom?")
        if result.status != "answered" or result.answer != "Miri Sol":
            raise SystemExit(f"saved passive frame did not survive reload: {result}")
        print("PASS: a source-supported passive question example extends the licensed created relation")
        print("PASS: the passive question frame survives save/load")


if __name__ == "__main__":
    main()
