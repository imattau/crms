"""Expand source retrieval with verified inference without conflating evidence."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def setup() -> tuple[CRMSKnowledgeBase, CRMSResearchIndex]:
    kb = CRMSKnowledgeBase()
    for subject, middle, target, source in (
            ("Ada", "Bea", "Cal", "one"),
            ("Dee", "Eli", "Fay", "two"),
            ("Nia", "Oren", "Pia", "three")):
        kb.add_fact(subject, "parent", middle, f"{source}:first")
        kb.add_fact(middle, "parent", target, f"{source}:second")
    kb.add_inference_rule("parent-transitivity", "parent", "parent", "ancestor")
    for question, subject, target in (
            ("Who is an ancestor of Cal?", "Ada", "Cal"),
            ("Who is an ancestor of Fay?", "Dee", "Fay")):
        kb.teach_question(question, relation="ancestor", answer_field="subject",
                          bound_entity=target, answer=subject)
    index = CRMSResearchIndex()
    index.add_document("archive", "Port register",
                       "Nia appears in harbor records about coastal maps.",
                       "archives/port-register.txt")
    return kb, index


def main() -> None:
    kb, index = setup()
    question = "Who is an ancestor of Pia?"
    if index.search(question):
        raise SystemExit("fixture unexpectedly matches without inferred query expansion")
    result = kb.research(question, index)
    if not any(
            record["kind"] == "verified_inference"
            and record["text"].casefold() == "nia"
            and record["rules"] == ["parent-transitivity"]
            and {"three:first", "three:second"} <= set(record["sources"])
            for record in result.query_expansions or []):
        raise SystemExit("research result did not expose proof-licensed expansions independently")
    if result.status != "answered" or result.response.answer != "Nia":
        raise SystemExit(f"derived research question did not answer: {result}")
    if len(result.passages or []) != 1 or "Nia appears" not in result.passages[0]["excerpt"]:
        raise SystemExit(f"verified inference did not expand retrieval: {result.passages}")
    if "nia" not in result.passages[0]["matched_licensed_expansion_terms"]:
        raise SystemExit("retrieval did not label the proof-derived entity expansion")
    if not any(
            license_record["kind"] == "verified_inference"
            and license_record["text"].casefold() == "nia"
            and license_record["rules"] == ["parent-transitivity"]
            and {"three:first", "three:second"}
            <= set(license_record["sources"])
            for license_record in result.passages[0][
                "matched_expansion_licenses"]):
        raise SystemExit("proof-derived expansion omitted its rule and source lineage")
    if len(result.derived_context or []) != 1:
        raise SystemExit(f"derived retrieval context was not retained: {result.derived_context}")
    context = result.derived_context[0]
    if (context["conclusion"] != {"subject": "Nia", "relation": "ancestor", "object": "Pia"}
            or context["rules"] != ["parent-transitivity"]
            or not {"three:first", "three:second"}.issubset(context["sources"])):
        raise SystemExit(f"derived query context lost its proof provenance: {context}")
    rendered = kb.render_research(result)
    if ("not extracted from the retrieved passage" not in rendered
            or "Source: Port register" not in rendered
            or "Verified derived query context" not in rendered
            or "licensed expansion terms: nia" not in rendered):
        raise SystemExit(f"research renderer conflated retrieved and derived evidence:\n{rendered}")
    if result.candidates:
        raise SystemExit("retrieved passage was incorrectly promoted to a fact candidate")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json", "session.json")}
        kb.save(paths["knowledge.json"])
        index.save(paths["index.json"])
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(paths["knowledge.json"]),
               "--index", str(paths["index.json"]),
               "--dialogue-state", str(paths["dialogue.json"]),
               "--rules", str(paths["rules.json"]),
               "--rule-session", str(paths["session.json"])]
        output = subprocess.run(
            cli, input=question + "\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20).stdout
        if "Verified derived query context" not in output or "Port register" not in output:
            raise SystemExit(f"terminal research omitted the distinction:\n{output}")
    print("research with derived context diagnostic: PASS")
    print("proof-licensed query expansion, separate source claims, no auto-extraction, CLI: PASS")


if __name__ == "__main__":
    main()
