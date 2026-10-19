"""Check grounded standalone demonstrative references in dialogue."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Maker", "built", "Engine", "source:build")
    kb.add_fact("Foundry", "built", "Gearbox", "source:build:second")
    kb.teach_question("Who built the Engine?", relation="built",
                      answer_field="subject", bound_entity="Engine",
                      answer="Maker")
    kb.teach_question("Who built the Gearbox?", relation="built",
                      answer_field="subject", bound_entity="Gearbox",
                      answer="Foundry")
    kb.add_fact("Engine", "powers", "Vehicle", "source:power")
    kb.add_fact("Motor", "powers", "Machine", "source:power:second")
    kb.teach_question("What does Engine power?", relation="powers",
                      answer_field="object", bound_entity="Engine",
                      answer="Vehicle")
    kb.teach_question("What does Motor power?", relation="powers",
                      answer_field="object", bound_entity="Motor",
                      answer="Machine")

    dialogue = CRMSDialogue(kb)
    first = dialogue.turn("Who built the Engine?")
    with_that = dialogue.turn("What does that power?")
    if (first.response is None or first.response.answer != "Maker"
            or with_that.response is None or with_that.response.answer != "Vehicle"
            or with_that.resolved_question != "What does Engine power?"):
        raise SystemExit(f"grounded 'that' reference failed: {first}, {with_that}")

    ellipsis_dialogue = CRMSDialogue(kb)
    ellipsis_dialogue.turn("Who built the Engine?")
    elliptical = ellipsis_dialogue.turn("What about that?")
    if (elliptical.response is None or elliptical.response.answer != "Maker"
            or elliptical.resolved_question != "Who built the Engine?"):
        raise SystemExit(f"elliptical 'what about that' follow-up failed: {elliptical}")

    with_this = dialogue.turn("Who built this?")
    if (with_this.response is None or with_this.response.answer != "Maker"
            or with_this.resolved_question.casefold() not in {
                "Who built the Engine?".casefold(),
                "Who built Engine?".casefold()}):
        raise SystemExit(f"grounded 'this' reference failed: {with_this}")

    # A demonstrative followed by an entity surface is a determiner and must
    # not be replaced as though it were an entity pronoun.
    determiner = dialogue.turn("Who built that Engine?")
    if determiner.resolved_question != "Who built that Engine?":
        raise SystemExit(f"determiner 'that' was rewritten as a pronoun: {determiner}")

    no_context = CRMSDialogue(kb).turn("Who built that?")
    if no_context.status != "unknown" or "name the entity" not in no_context.text:
        raise SystemExit(f"unbound demonstrative did not request clarification: {no_context}")

    ambiguous_kb = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Maker", "Engine", "source:engine"),
            ("Foundry", "Gearbox", "source:gearbox"),
            ("Founder", "Maker", "source:maker")):
        ambiguous_kb.add_fact(subject, "built", obj, source)
        ambiguous_kb.teach_question(
            f"Who built {obj}?", relation="built", answer_field="subject",
            bound_entity=obj, answer=subject)
    ambiguous_dialogue = CRMSDialogue(ambiguous_kb)
    ambiguous_dialogue.turn("Who built Engine?")
    ambiguous_followup = ambiguous_dialogue.turn("What about that?")
    if (ambiguous_followup.status != "unknown"
            or "multiple grounded entity substitutions" not in ambiguous_followup.text):
        raise SystemExit(f"ambiguous ellipsis did not request clarification: "
                         f"{ambiguous_followup}")

    research_index = CRMSResearchIndex()
    research_kb = CRMSKnowledgeBase()
    for subject, obj, document_id in (
            ("Ada", "Engine", "ada-design"),
            ("Grace", "Compiler", "grace-design")):
        sentence = f"{subject} designed the {obj}."
        research_index.add_document(document_id, document_id, sentence,
                                   f"sources/{document_id}.txt")
        hit = next(candidate for candidate in research_index.search(sentence, limit=5)
                   if candidate.document_id == document_id)
        research_kb.add_fact_from_hit(subject, "designed", obj,
                                      research_index, hit)
        research_kb.teach_question(
            f"Who designed the {obj}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject)
    research_dialogue = CRMSDialogue(research_kb)
    research_first = research_dialogue.turn(
        "Who designed the Engine?", research_index=research_index)
    research_pronoun = research_dialogue.turn(
        "Who designed this?", research_index=research_index)
    research_ellipsis = research_dialogue.turn(
        "What about that?", research_index=research_index)
    for result in (research_first, research_pronoun, research_ellipsis):
        if (result.status != "answered" or result.response is None
                or result.response.answer != "Ada"
                or result.research is None or not result.research.passages
                or not result.response.evidence):
            raise SystemExit(f"research-backed reference lost its citations: {result}")
    repair_dialogue = CRMSDialogue(research_kb)
    repair_dialogue.turn("Who designed the Engine?", research_index=research_index)
    corrected = repair_dialogue.turn("I meant the Compiler",
                                     research_index=research_index)
    if (corrected.status != "answered" or corrected.response is None
            or corrected.response.answer != "Grace" or corrected.research is None
            or not corrected.research.passages or not corrected.response.evidence):
        raise SystemExit(f"research-backed correction lost its source result: {corrected}")

    # A common elliptical entity switch should reuse only the prior question
    # frame, then prove the replacement entity's answer from its own fact.
    capital_kb = CRMSKnowledgeBase()
    for country, city in (("France", "Paris"), ("Italy", "Rome")):
        capital_kb.add_fact(country, "capital of", city,
                            f"source:capital:{country.casefold()}")
        capital_kb.teach_question(
            f"What is the capital of {country}?", relation="capital of",
            answer_field="object", bound_entity=country, answer=city)
    capital_dialogue = CRMSDialogue(capital_kb)
    first_capital = capital_dialogue.turn("What is the capital of France?")
    second_capital = capital_dialogue.turn("And Italy?")
    if (first_capital.response is None
            or first_capital.response.answer != "Paris"
            or second_capital.status != "answered"
            or second_capital.resolved_question != "What is the capital of Italy?"
            or second_capital.response is None
            or second_capital.response.answer != "Rome"
            or not second_capital.response.evidence):
        raise SystemExit(
            f"elliptical country switch failed to use the new entity's fact: "
            f"{first_capital}, {second_capital}")

    unsupported = CRMSDialogue(capital_kb)
    unsupported.turn("What is the capital of France?")
    unsupported_turn = unsupported.turn("And Atlantis?")
    if (unsupported_turn.status != "unknown"
            or "entity already present" not in unsupported_turn.text):
        raise SystemExit(
            f"unsupported entity follow-up did not request clarification: "
            f"{unsupported_turn}")

    with tempfile.TemporaryDirectory(prefix="crms-ellipsis-chat-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        capital_kb.save(knowledge_path)
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1]
                                / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        terminal = subprocess.run(
            command,
            input="What is the capital of France?\nAnd Italy?\n/quit\n",
            text=True, capture_output=True, cwd=root, check=False, timeout=30)
        if (terminal.returncode != 0
                or "CRMS> Paris." not in terminal.stdout
                or "CRMS> Rome." not in terminal.stdout):
            raise SystemExit(
                f"terminal elliptical entity switch failed:\n"
                f"{terminal.stdout}\n{terminal.stderr}")

    print("dialogue demonstrative diagnostic: PASS")
    print("grounded this/that, elliptical follow-up, unique/ambiguous binding, "
          "determiner guard, no-context clarification, source-backed "
          "follow-up/correction, And Italy? entity switch and chat route: PASS")


if __name__ == "__main__":
    main()
