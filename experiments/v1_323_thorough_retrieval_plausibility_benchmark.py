"""Compare lexical retrieval with thorough relation-grounded count evidence."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-plausibility-50-") as folder:
        root = Path(folder)
        index = CRMSSQLiteResearchIndex(root / "research.sqlite")
        questions: list[tuple[str, str, bool]] = []
        for number in range(50):
            entity = f"Person {number}"
            if number < 25:
                sentence = f"{entity} won two awards."
                supports_query = True
            else:
                sentence = f"{entity} received two awards."
                supports_query = False
            index.add_document(f"person-{number}", entity, sentence,
                               f"person-{number}.txt")
            questions.append((
                f"How many awards did {entity} win?", sentence, supports_query))

        index.close()

        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        chat = Path(__file__).resolve().parents[1] / "crms_chat.py"
        inputs = ["/effort quick"]
        inputs.extend(question for question, _sentence, _supports in questions)
        inputs.append("/effort thorough")
        inputs.extend(question for question, _sentence, _supports in questions)
        inputs.append("/quit")
        run = subprocess.run(
            [sys.executable, str(chat), "--index", str(root / "research.sqlite"),
             "--knowledge", str(knowledge_path),
             "--rules", str(root / "rules.json"),
             "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rule-session", str(root / "rule-session.json")],
            input="\n".join(inputs) + "\n", text=True, capture_output=True,
            cwd=root, timeout=60)
        require(run.returncode == 0, f"chat runtime failed: {run.stderr}")
        answers = [line.split("you> CRMS> ", 1)[1]
                   for line in run.stdout.splitlines()
                   if "you> CRMS> " in line]
        require(len(answers) == 100,
                f"expected 100 chat answers, got {len(answers)}:\n{run.stdout}")
        quick_answers, thorough_answers = answers[:50], answers[50:]

        quick_wrong = quick_abstentions = quick_correct = 0
        thorough_wrong = thorough_abstentions = thorough_correct = 0
        for (question, expected_sentence, supports_query), quick, thorough in zip(
                questions, quick_answers, thorough_answers):
            if expected_sentence in quick and supports_query:
                quick_correct += 1
            elif ("couldn't answer" in quick.casefold()
                  or "couldn't find" in quick.casefold()):
                quick_abstentions += 1
            else:
                quick_wrong += 1
            if expected_sentence in thorough and supports_query:
                thorough_correct += 1
            elif ("couldn't find a source sentence" in thorough.casefold()
                  and not supports_query):
                thorough_abstentions += 1
            else:
                thorough_wrong += 1

    require(quick_wrong > thorough_wrong,
            f"thorough did not reduce wrong answers: quick={quick_wrong}, "
            f"thorough={thorough_wrong}")
    require(thorough_correct == 25 and thorough_abstentions == 25,
            f"thorough accuracy/abstention unexpected: correct={thorough_correct}, "
            f"abstentions={thorough_abstentions}")
    print("thorough retrieval plausibility benchmark: PASS")
    print(f"50 known-answer questions; quick wrong={quick_wrong}, "
          f"abstentions={quick_abstentions}; thorough wrong={thorough_wrong}, "
          f"correct={thorough_correct}, abstentions={thorough_abstentions}")
    print("scope: synthetic entity/relation lexical-confound set; "
          "not a general-knowledge benchmark")


if __name__ == "__main__":
    main()
