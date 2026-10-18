"""Check conservative, cited transfer of regular plural entity aliases."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def make_kb() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for subject, entity, source in (
            ("Ada", "Engine", "source:engine-facts"),
            ("Bea", "Compiler", "source:compiler-facts"),
            ("Sage", "Sculpture", "source:sculpture-facts")):
        kb.add_fact(subject, "designed", entity, source)
        kb.teach_fact_pattern(
            f"{subject} designed {entity}.", subject=subject,
            relation="designed", obj=entity, source=source,
            predicate_phrase="designed")
    kb.add_fact("Sculpture", "located in", "Rome", "source:location")
    kb.teach_question("Who designed Engine?", relation="designed",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who designed Compiler?", relation="designed",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")
    kb.teach_entity_alias("Engines", "Engine", source="engine-plural#1")
    kb.teach_entity_alias("Compilers", "Compiler", source="compiler-plural#1")
    return kb


def check_pattern(donors: tuple[tuple[str, str, str], ...],
                  target: str, plural: str, context: str) -> None:
    kb = CRMSKnowledgeBase()
    for subject, entity in (("Ada", donors[0][0]),
                            ("Bea", donors[1][0]),
                            ("Sage", target)):
        kb.add_fact(subject, "designed", entity, f"facts:{entity}")
    kb.teach_question(f"Who designed {donors[0][0]}?", relation="designed",
                      answer_field="subject", bound_entity=donors[0][0], answer="Ada")
    kb.teach_question(f"Who designed {donors[1][0]}?", relation="designed",
                      answer_field="subject", bound_entity=donors[1][0], answer="Bea")
    for singular, surface, source in donors:
        kb.teach_entity_alias(surface, singular, source=source)
    result = kb.ask(f"Who designed {plural}?")
    evidence = next((item for item in result.language_evidence or []
                     if item.get("kind") == "induced_entity_plural"), None)
    if (result.status != "answered" or result.answer != "Sage"
            or evidence is None or evidence.get("context") != context):
        raise SystemExit(f"{context} plural did not transfer: {result}")


def main() -> None:
    kb = make_kb()
    before_facts = kb.facts()
    result = kb.ask("Who designed Sculptures?")
    if result.status != "answered" or result.answer != "Sage":
        raise SystemExit(f"licensed regular plural did not transfer: {result}")
    evidence = next((item for item in result.language_evidence or []
                     if item.get("kind") == "induced_entity_plural"), None)
    if (evidence is None or evidence.get("context") != "regular-s"
            or evidence.get("sources") != ["compiler-plural#1", "engine-plural#1"]
            or evidence.get("shared_roles") != [
                {"relation": "designed", "role": "object"}]
            or {item["entity"] for item in evidence.get("support", [])}
            != {"Compiler", "Engine"}):
        raise SystemExit("answer omitted complete plural-rule lineage")
    records = kb._entity_alias_records()
    if records.get(("adas",)) or records.get(("sages",)):
        raise SystemExit("object-role plural evidence transferred to agent entities")
    rules = kb.entity_plural_rules()
    if (len(rules) != 1 or rules[0]["context"] != "regular-s"
            or rules[0]["shared_roles"] != [
                {"relation": "designed", "role": "object"}]
            or rules[0]["forms"] != [
                {"entity": "Sculpture", "plural": "sculptures",
                 "role_sources": ["source:sculpture-facts"]}]):
        raise SystemExit(f"inspectable plural rule inventory is incomplete: {rules}")
    rendered = kb.render(result)
    if "Plural form: sculptures → Sculpture" not in rendered:
        raise SystemExit("controlled answer rendering omitted plural provenance")
    if kb.facts() != before_facts:
        raise SystemExit("query-time plural transfer changed stored facts")
    direct = kb.infer_relation("Sage", "designed", "Sculptures")
    if (direct.status != "answered"
            or not any(item.get("kind") == "induced_entity_plural"
                       for item in direct.language_evidence)):
        raise SystemExit("direct inference API did not resolve a licensed plural")
    if "Plural form: Sculptures → Sculpture" not in kb.render_inference(direct):
        raise SystemExit("inference rendering omitted plural-rule provenance")
    path = kb.ask_path("Sculptures", ["located in"])
    if path.status != "answered" or path.answer != "Rome":
        raise SystemExit("path API did not resolve a licensed plural start entity")
    if not any(item.get("kind") == "induced_entity_plural"
               for item in path.language_evidence or []):
        raise SystemExit("path API omitted the plural rule lineage")
    path_check = kb.ask_path_between("Sculptures", "Rome", ["located in"])
    if path_check.status != "answered":
        raise SystemExit("bounded path check did not resolve a licensed plural")
    if not any(item.get("kind") == "induced_entity_plural"
               for item in path_check.language_evidence or []):
        raise SystemExit("bounded path check omitted the plural rule lineage")
    proposal = next((item for item in kb.propose_facts(
        "Sage designed Sculptures.", source="review:plural")
        if item.subject == "Sage" and item.relation == "designed"), None)
    if (proposal is None or proposal.object != "Sculpture"
            or not any(item.get("kind") == "induced_entity_plural"
                       for item in proposal.language_evidence)):
        raise SystemExit("fact review did not canonicalize and cite the plural form")
    if any("review:plural" in fact.sources for fact in kb.facts()):
        raise SystemExit("plural fact proposal was committed without review")

    check_pattern((("Bus", "Buses", "bus-plural#1"),
                   ("Glass", "Glasses", "glass-plural#1")),
                  "Class", "Classes", "sibilant-es")
    check_pattern((("City", "Cities", "city-plural#1"),
                   ("Country", "Countries", "country-plural#1")),
                  "Library", "Libraries", "consonant-y-ies")
    index = CRMSResearchIndex()
    index.add_document("sculptures", "Sculptures",
                       "Mira designed sculptures.",
                       "sources/sculptures.txt")
    index.add_document("sculpture-singular", "Sculpture",
                       "A sculpture was displayed beside the river.",
                       "sources/sculpture-singular.txt")
    research = kb.research("Who designed Sculptures?", index)
    if not any(item["citation"].startswith("sculptures#")
               for item in research.passages or []):
        raise SystemExit("licensed plural did not expand research retrieval")
    candidate = next((item for item in research.candidates or []
                      if item.subject == "Mira" and item.relation == "designed"), None)
    if (candidate is None or candidate.object != "Sculpture"
            or not candidate.source.startswith("sculptures#")
            or not any(item.get("kind") == "induced_entity_plural"
                       for item in candidate.language_evidence)):
        raise SystemExit("research did not return a cited, canonicalized plural candidate")
    rendered_research = kb.render_research(research)
    if ("induced entity plural: sculptures → Sculpture" not in rendered_research
            or "shared roles: designed object" not in rendered_research
            or "target role evidence: source:sculpture-facts" not in rendered_research
            or "engine-plural#1" not in rendered_research):
        raise SystemExit("research renderer omitted plural rule lineage")
    if any(fact.subject == "Mira" and fact.relation == "designed"
           for fact in kb.facts()):
        raise SystemExit("research promoted a plural candidate without review")
    singular_retrieval = next((item for item in research.passages or []
                               if item["citation"].startswith("sculpture-singular#")), None)
    if (singular_retrieval is None
            or not any(license_record["kind"] == "induced_entity_plural"
                       and "sculpture" in license_record["matched_terms"]
                       for license_record in singular_retrieval[
                           "matched_expansion_licenses"])):
        raise SystemExit("research did not expose canonical expansion from plural query")

    # A single aligned alias, an irregular pair, and a plural that collides
    # with another explicitly stored entity must not license a transfer.
    one = make_kb()
    one.forget_entity_alias("Compilers")
    if one._entity_alias_records().get(("sculptures",)):
        raise SystemExit("one alias licensed productive plural transfer")

    partial = make_kb()
    partial.teach_entity_alias("Engines", "Engine", source="engine-plural#2")
    if not partial.remove_entity_alias_source("Engines", "engine-plural#2"):
        raise SystemExit("could not retract one citation for an alias")
    if partial.ask("Who designed Sculptures?").status != "answered":
        raise SystemExit("retracting one alias citation removed surviving support")
    if not partial.remove_entity_alias_source("Engines", "engine-plural#1"):
        raise SystemExit("could not retract the final citation for an alias")
    if partial.ask("Who designed Sculptures?").status == "answered":
        raise SystemExit("retracted alias donor continued licensing plural transfer")

    cli = make_kb()
    cli.teach_entity_alias("Engines", "Engine", source="engine-plural#2")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path, index_path = root / "knowledge.json", root / "index.json"
        cli.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path)],
            input=("/alias-rules\n"
                   "/forget-alias Engines|engine-plural#2\n"
                   "/forget-alias Engines|engine-plural#1\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if ("Plural rule [regular-s; role designed object]" not in process.stdout
                or "Compiler → compilers" not in process.stdout
                or "Sculpture → sculptures [role sources: source:sculpture-facts]"
                not in process.stdout
                or "Forgot source engine-plural#2 from alias Engines." not in process.stdout
                or "Forgot source engine-plural#1 from alias Engines." not in process.stdout):
            raise SystemExit(f"CLI source-level alias retraction failed:\n{process.stdout}")
        restored_partial = CRMSKnowledgeBase.load(knowledge_path)
        if (restored_partial.entity_aliases()
                != [{"alias": "compilers", "entity": "Compiler",
                     "sources": ["compiler-plural#1"]}]):
            raise SystemExit("CLI source retraction was not persisted accurately")

    same_source = make_kb()
    same_source.forget_entity_alias("Engines")
    same_source.forget_entity_alias("Compilers")
    same_source.teach_entity_alias("Engines", "Engine", source="one-paper#1")
    same_source.teach_entity_alias("Compilers", "Compiler", source="one-paper#2")
    if same_source._entity_alias_records().get(("sculptures",)):
        raise SystemExit("fragments from one document licensed plural transfer")

    check_pattern((("Analytical Engine", "Analytical Engines", "analytical#1"),
                   ("Steam Engine", "Steam Engines", "steam#1")),
                  "Electric Motor", "Electric Motors", "regular-s")
    mismatched_prefix = CRMSKnowledgeBase()
    for subject, entity in (("Ada", "Analytical Engine"),
                            ("Bea", "Steam Engine"),
                            ("Sage", "Electric Motor")):
        mismatched_prefix.add_fact(subject, "designed", entity,
                                   f"facts:{subject}")
    mismatched_prefix.teach_entity_alias(
        "Other Engines", "Analytical Engine", source="analytical#1")
    mismatched_prefix.teach_entity_alias(
        "False Engines", "Steam Engine", source="steam#1")
    if mismatched_prefix._entity_alias_records().get(("electric", "motors")):
        raise SystemExit("changed name prefixes licensed head-noun morphology")

    final_o = make_kb()
    final_o.add_fact("Mira", "designed", "Echo", "source:echo")
    if final_o._entity_alias_records().get(("echoes",)):
        raise SystemExit("regular -s evidence guessed the final-o plural")

    irregular = make_kb()
    irregular.add_fact("Mira", "designed", "Person", "source:person")
    irregular.teach_entity_alias("People", "Person", source="person-plural#1")
    if irregular._entity_alias_records().get(("peoples",)):
        raise SystemExit("irregular plural evidence licensed a regular form")

    collision = make_kb()
    collision.add_fact("Mira", "designed", "Sculptures", "source:plural-entity")
    if collision._entity_alias_records().get(("sculptures",)):
        raise SystemExit("plural alias overrode an independently stored entity")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        again = restored.ask("Who designed Sculptures?")
        if (again.status != "answered" or again.answer != "Sage"
                or not any(item.get("kind") == "induced_entity_plural"
                           for item in again.language_evidence or [])):
            raise SystemExit("plural transfer or lineage failed after persistence")

    print("grounded entity plural transfer diagnostic: PASS")
    print("independent alias support, QA transfer, lineage, no fact promotion, collision/irregular abstention, persistence: PASS")


if __name__ == "__main__":
    main()
