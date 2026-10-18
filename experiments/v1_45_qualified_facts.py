"""Check contextual fact storage and exact qualifier filters."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "managed", "Project Alpha", "train-a")
    kb.add_fact("Bob", "managed", "Project Beta", "train-b")
    kb.add_fact("Ada", "managed", "Project Alpha", "train-a-2020",
                qualifiers={"year": "2020"})
    kb.add_fact("Bob", "managed", "Project Beta", "train-b-2024",
                qualifiers={"year": "2024"})
    kb.teach_question("Who managed Project Alpha?", relation="managed",
                      answer_field="subject", bound_entity="Project Alpha",
                      answer="Ada")
    kb.teach_question("Who managed Project Beta?", relation="managed",
                      answer_field="subject", bound_entity="Project Beta",
                      answer="Bob")
    kb.teach_qualified_question(
        "Who managed Project Alpha in 2020?", relation="managed",
        answer_field="subject", bound_entity="Project Alpha", answer="Ada",
        qualifier={"year": "2020"})
    qualified_frame = kb.teach_qualified_question(
        "Who managed Project Beta in 2024?", relation="managed",
        answer_field="subject", bound_entity="Project Beta", answer="Bob",
        qualifier={"year": "2024"})
    if not qualified_frame:
        raise SystemExit("distinct entity and year examples did not license a frame")
    reversed_first = kb.teach_qualified_question(
        "In 2020, who managed Project Alpha?", relation="managed",
        answer_field="subject", bound_entity="Project Alpha", answer="Ada",
        qualifier={"year": "2020"})
    reversed_frame = kb.teach_qualified_question(
        "In 2024, who managed Project Beta?", relation="managed",
        answer_field="subject", bound_entity="Project Beta", answer="Bob",
        qualifier={"year": "2024"})
    if reversed_first or not reversed_frame:
        raise SystemExit("qualifier-first frame did not require and learn contrasting examples")
    kb.add_fact("Ada", "managed", "Project Gamma", "g-2020",
                qualifiers={"year": "2020", "region": "north"})
    kb.add_fact("Grace", "managed", "Project Gamma", "g-2024",
                qualifiers={"year": "2024", "region": "north"})
    kb.add_fact("Project Gamma", "uses", "Widget", "uses-2020",
                qualifiers={"year": "2020"})
    kb.add_fact("Project Gamma", "uses", "Engine", "uses-2024",
                qualifiers={"year": "2024"})
    kb.add_fact("Engine", "manufactured by", "Acme", "maker-2024",
                qualifiers={"year": "2024"})

    ambiguous = kb.ask("Who managed Project Gamma?")
    in_2020 = kb.ask("Who managed Project Gamma?", qualifiers={"year": "2020"})
    in_2024 = kb.ask("Who managed Project Gamma?", qualifiers={"YEAR": "2024"})
    if ambiguous.status != "ambiguous":
        raise SystemExit(f"unqualified query hid contextual alternatives: {ambiguous}")
    if in_2020.answer != "Ada" or in_2024.answer != "Grace":
        raise SystemExit(f"context filter returned wrong manager: {in_2020}, {in_2024}")
    natural_2024 = kb.ask("Who managed Project Gamma in 2024?")
    natural_2020 = kb.ask("Who managed Project Gamma in 2020?")
    natural_unknown = kb.ask("Who managed Project Gamma in 2028?")
    if natural_2024.answer != "Grace" or natural_2020.answer != "Ada":
        raise SystemExit(f"learned qualifier question frame failed: {natural_2024}, {natural_2020}")
    if "Recorded context: region=north, year=2024." not in kb.render(natural_2024):
        raise SystemExit("rendered answer hid the source fact's qualifier context")
    if natural_unknown.status != "unknown":
        raise SystemExit(f"missing contextual evidence was not left unknown: {natural_unknown}")
    reversed_query = kb.ask("In 2024, who managed Project Gamma?")
    if reversed_query.answer != "Grace":
        raise SystemExit(f"qualifier-first wording did not transfer: {reversed_query}")
    path = kb.ask_path("Project Gamma", ["uses", "manufactured by"],
                       qualifiers={"year": "2024"})
    if path.answer != "Acme" or path.proofs is None:
        raise SystemExit(f"qualified path did not resolve with proof: {path}")
    if kb.ask_path("Project Gamma", ["uses", "manufactured by"],
                   qualifiers={"year": "2020"}).status != "unknown":
        raise SystemExit("path query crossed into a different context")
    try:
        kb.add_fact("x", "r", "y", "bad", qualifiers={"Year": "1", "year": "2"})
    except ValueError:
        pass
    else:
        raise SystemExit("case-colliding qualifier names were accepted")

    with tempfile.TemporaryDirectory() as folder:
        path_file = Path(folder) / "knowledge.json"
        index_file = Path(folder) / "index.json"
        index = CRMSResearchIndex()
        index.add_document("cli-source", "Gamma report",
                           "Grace managed Project Gamma in 2024.",
                           "sources/gamma.txt")
        index.save(index_file)
        kb.save(path_file)
        restored = CRMSKnowledgeBase.load(path_file)
        restored_answer = restored.ask(
            "Who managed Project Gamma?", qualifiers={"year": "2024"})
        restored_path = restored.ask_path(
            "Project Gamma", ["uses", "manufactured by"],
            qualifiers={"year": "2024"})
        if restored_answer.answer != "Grace" or restored_path.answer != "Acme":
            raise SystemExit("qualified query or proof failed after save/load")
        evidence = next(fact for fact in restored.facts()
                        if fact.object == "Project Gamma" and fact.subject == "Grace")
        if evidence.qualifiers != (("region", "north"), ("year", "2024")):
            raise SystemExit(f"qualifiers were not persisted canonically: {evidence}")
        cli = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(path_file), "--index", str(index_file),
             "--dialogue-state", str(Path(folder) / "dialogue.json"),
             "--rules", str(Path(folder) / "rules.json")],
            input=("/teach-context-fact Grace|managed|Project Gamma|managed 2024|year=2024\n"
                   "/ask-context Who managed Project Gamma?|year=2024\n"
                   "Who managed Project Gamma in 2024?\n"
                   "In 2024, who managed Project Gamma?\n/facts\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if ("Answer: Grace." not in cli.stdout
                or "Stored cited fact: Grace — managed → Project Gamma [context: year=2024]."
                not in cli.stdout
                or "Recorded context:" not in cli.stdout):
            raise SystemExit(f"CLI did not apply the explicit context filter:\n{cli.stdout}")

    print("qualified fact diagnostic: PASS")
    print("context storage, entity-first/qualifier-first language, open-world ambiguity, QA/path filters, CLI, persistence: PASS")


if __name__ == "__main__":
    main()
