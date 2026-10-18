"""Check translation clarification survives restart and rejects stale memory."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_translation import CRMSTranslation


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-translation-session-") as folder:
        root = Path(folder)
        translations = root / "translations.json"
        session = root / "translation-session.json"
        model = CRMSTranslation()
        for register, greeting in (("formal", "Bonjour"), ("informal", "Salut")):
            model.teach(
                "English", "French", register,
                "Hello, {name}.", f"{greeting}, {{name}}.",
                [("Hello, Ada.", f"{greeting}, Ada."),
                 ("Hello, Malik.", f"{greeting}, Malik.")])
        model.save(translations)

        command = [sys.executable, str(ROOT / "crms_chat.py"),
                   "--knowledge", str(root / "knowledge.json"),
                   "--math", str(root / "math.json"),
                   "--math-session", str(root / "math-session.json"),
                   "--translations", str(translations),
                   "--translation-session", str(session),
                   "--index", str(root / "index.json"),
                   "--dialogue-state", str(root / "dialogue.json"),
                   "--rules", str(root / "rules.json"),
                   "--rule-session", str(root / "rule-session.json"),
                   "--candidate-session", str(root / "candidate-session.json")]
        first = subprocess.run(
            command, input="Translate 'Hello, Rowan.' into French.\n/quit\n",
            text=True, capture_output=True, timeout=30)
        if (first.returncode != 0
                or "Which register should I use?" not in first.stdout
                or "Candidates: formal: Bonjour, Rowan.; informal: Salut, Rowan." 
                    not in first.stdout
                or not session.exists()):
            raise SystemExit(
                f"translation ambiguity was not persisted:\n{first.stdout}\n{first.stderr}")
        saved = json.loads(session.read_text(encoding="utf-8"))
        if (saved.get("kind") != "register"
                or saved.get("choices") != ["formal", "informal"]
                or saved.get("source_text") != "Hello, Rowan."):
            raise SystemExit(f"pending translation state is malformed: {saved}")

        resumed = subprocess.run(
            command, input="formal register\n/quit\n", text=True,
            capture_output=True, timeout=30)
        if (resumed.returncode != 0
                or "Restored a pending translation clarification" not in resumed.stdout
                or "Bonjour, Rowan." not in resumed.stdout):
            raise SystemExit(
                f"translation choice did not resume after restart:\n"
                f"{resumed.stdout}\n{resumed.stderr}")

        # Any edit to the translation memory invalidates saved choices, even if
        # the original frames still happen to exist.
        model.teach_additional_example(
            "English", "French", "formal", "Hello, Zoe.", "Bonjour, Zoe.")
        model.save(translations)
        stale = subprocess.run(
            command, input="/quit\n", text=True, capture_output=True, timeout=30)
        if (stale.returncode != 0
                or "Restored a pending translation clarification" in stale.stdout):
            raise SystemExit(
                f"stale translation choice survived a memory edit:\n"
                f"{stale.stdout}\n{stale.stderr}")

        # Source-language ambiguity uses a different clarification branch;
        # verify that its offered languages also survive restart.
        bilingual_memory = root / "bilingual-translations.json"
        bilingual_session = root / "bilingual-session.json"
        bilingual = CRMSTranslation()
        bilingual.teach(
            "English", "French", "formal", "No, {name}.",
            "Pas vraiment, {name}.",
            [("No, Ada.", "Pas vraiment, Ada."),
             ("No, Malik.", "Pas vraiment, Malik.")])
        bilingual.teach(
            "Spanish", "French", "formal", "No, {name}.",
            "Non, {name}.",
            [("No, Ada.", "Non, Ada."),
             ("No, Malik.", "Non, Malik.")])
        bilingual.save(bilingual_memory)
        bilingual_command = list(command)
        bilingual_command[bilingual_command.index(str(translations))] = str(bilingual_memory)
        bilingual_command[bilingual_command.index(str(session))] = str(bilingual_session)
        source_first = subprocess.run(
            bilingual_command,
            input="Translate 'No, Rowan.' into French.\n/quit\n",
            text=True, capture_output=True, timeout=30)
        if (source_first.returncode != 0
                or "Which source language should I use?" not in source_first.stdout
                or "Candidates: english: Pas vraiment, Rowan.; "
                    "spanish: Non, Rowan." not in source_first.stdout
                or not bilingual_session.exists()):
            raise SystemExit(
                f"source-language ambiguity was not persisted:\n"
                f"{source_first.stdout}\n{source_first.stderr}")
        source_resumed = subprocess.run(
            bilingual_command, input="Spanish\n/quit\n", text=True,
            capture_output=True, timeout=30)
        if (source_resumed.returncode != 0
                or "Restored a pending translation clarification" not in source_resumed.stdout
                or "Non, Rowan." not in source_resumed.stdout):
            raise SystemExit(
                f"source-language choice did not resume:\n"
                f"{source_resumed.stdout}\n{source_resumed.stderr}")

        selective = CRMSTranslation()
        selective.teach(
            "English", "French", "formal", "Hello, {name}.",
            "Bonjour, {name}.",
            [("Hello, Ada.", "Bonjour, Ada."),
             ("Hello, Malik.", "Bonjour, Malik.")])
        selective.teach(
            "Spanish", "French", "formal", "Hello, {name}.",
            "Hola, {name}.",
            [("Hello, Ada.", "Hola, Adela."),
             ("Hello, Malik.", "Hola, Maliko.")])
        only_viable = selective.translate("Translate 'Hello, Rowan.' into French.")
        if (only_viable is None or only_viable.status != "translated"
                or only_viable.output != "Bonjour, Rowan."):
            raise SystemExit(
                "a source frame with an unresolved translated slot caused a "
                f"false source-language ambiguity: {only_viable}")

        overlapping = CRMSTranslation()
        overlapping.teach(
            "English", "French", "formal", "Hello, {name}.",
            "Bonjour, {name}.",
            [("Hello, Ada.", "Bonjour, Ada."),
             ("Hello, Malik.", "Bonjour, Malik.")])
        overlapping.teach(
            "Spanish", "French", "formal", "Hello, {name}.",
            "Hola, {name}.",
            [("Hello, Ada.", "Hola, Ada."),
             ("Hello, Malik.", "Hola, Malik.")])
        overlapping.teach(
            "Spanish", "French", "formal", "Hello, {person}.",
            "Saludos, {person}.",
            [("Hello, Ada.", "Saludos, Adela."),
             ("Hello, Malik.", "Saludos, Maliko.")])
        only_consistent = overlapping.translate(
            "Translate 'Hello, Rowan.' into French.")
        if (only_consistent is None or only_consistent.status != "translated"
                or only_consistent.output != "Bonjour, Rowan."):
            raise SystemExit(
                "an overlapping unresolved frame was offered as a source choice: "
                f"{only_consistent}")

    print("translation register clarification persistence: PASS")
    print("translation source-language clarification persistence: PASS")
    print("source-language candidates require translatable slot values: PASS")
    print("overlapping unresolved frame blocks false source choice: PASS")
    print("translation-memory fingerprint invalidates stale clarification: PASS")


if __name__ == "__main__":
    main()
