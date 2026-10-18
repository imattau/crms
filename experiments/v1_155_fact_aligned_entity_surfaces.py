"""Check source-backed entity surface alignment during fact-pattern learning."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    examples = (
        ("Ada", "Engine", "Engines", "Ada designed engines.", "engine-source"),
        ("Bea", "Compiler", "Compilers", "Bea designed compilers.", "compiler-source"),
        ("Sage", "Sculpture", "Sculpture", "Sage designed Sculpture.", "sculpture-source"),
    )
    for subject, entity, surface, sentence, document in examples:
        index.add_document(document, sentence, sentence, f"sources/{document}.txt")
        hit = index.search(sentence, limit=1)[0]
        fact = kb.add_fact_from_hit(subject, "designed", entity, index, hit)
        licensed = kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="designed", obj=entity,
            predicate_phrase="designed", research_index=index, hit=hit,
            object_phrase=surface)
        if not licensed:
            # The common frame is expected to license once the second example
            # contributes a distinct subject and object.
            continue
        if fact.object != entity:
            raise SystemExit("source-aligned teaching changed the canonical fact")
    kb.teach_question("Who designed Engine?", relation="designed",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who designed Compiler?", relation="designed",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")

    aliases = {item["alias"]: item for item in kb.entity_aliases()}
    for _, entity, surface, _, document in examples:
        if surface.casefold() == entity.casefold():
            continue
        expected = surface.casefold()
        record = aliases.get(expected)
        if (record is None or record["entity"] != entity
                or len(record["sources"]) != 1
                or not record["sources"][0].startswith(document + "#")):
            raise SystemExit(f"aligned surface {surface!r} lacks citation: {record}")

    # Two independent aligned aliases license the regular plural; the third
    # source's object-role evidence lets the rule answer an unseen plural.
    result = kb.ask("Who designed Sculptures?")
    if result.status != "answered" or result.answer != "Sage":
        raise SystemExit(f"aligned surface learning did not support plural QA: {result}")
    engine_alias = aliases["engines"]
    with tempfile.TemporaryDirectory() as directory:
        saved = Path(directory) / "aligned.json"
        kb.save(saved)
        restored = CRMSKnowledgeBase.load(saved)
        citation = engine_alias["sources"][0]
        if not restored.remove_fact("Ada", "designed", "Engine", citation):
            raise SystemExit("could not retract the aligned fact example")
        if any(item["alias"] == "engines" for item in restored.entity_aliases()):
            raise SystemExit("retracted fact-pattern left its aligned alias active")
        if restored._entity_alias_records().get(("sculptures",)):
            raise SystemExit("retracted aligned donor continued licensing plural transfer")
        if restored.ask("Who designed Sculptures?").status == "answered":
            raise SystemExit("plural QA remained available after retracting its donor")

    independently_taught = CRMSKnowledgeBase()
    index2 = CRMSResearchIndex()
    index2.add_document("ada", "Ada", "Ada designed engines.", "sources/ada.txt")
    hit2 = index2.search("designed engines", limit=1)[0]
    fact2 = independently_taught.add_fact_from_hit(
        "Ada", "designed", "Engine", index2, hit2)
    independently_taught.teach_fact_pattern_from_hit(
        "Ada designed engines.", subject="Ada", relation="designed",
        obj="Engine", predicate_phrase="designed", object_phrase="engines",
        research_index=index2, hit=hit2)
    independently_taught.teach_entity_alias(
        "Engines", "Engine", source=fact2.sources[0])
    independently_taught.remove_fact("Ada", "designed", "Engine", fact2.sources[0])
    if not any(item["alias"] == "engines"
               for item in independently_taught.entity_aliases()):
        raise SystemExit("fact retraction removed an independently taught alias support")

    # The same explicit phrase alignment and plural class must work for the
    # agent slot, with question answers still bound to the canonical entity.
    agents = CRMSKnowledgeBase()
    agent_index = CRMSResearchIndex()
    for agent, thing, surface, thing_surface, sentence, document in (
            ("Engineer", "Engine", "Engineers", "engines",
             "Engineers designed engines.", "engineers"),
            ("Artist", "Compiler", "Artists", "compilers",
             "Artists designed compilers.", "artists"),
            ("Sculptor", "Sculpture", "Sculptor", "sculpture",
             "Sculptor designed sculpture.", "sculptor")):
        agent_index.add_document(document, sentence, sentence,
                                 f"sources/{document}.txt")
        hit = agent_index.search(sentence, limit=1)[0]
        agents.add_fact_from_hit(agent, "designed", thing, agent_index, hit)
        agents.teach_fact_pattern_from_hit(
            sentence, subject=agent, relation="designed", obj=thing,
            predicate_phrase="designed", subject_phrase=surface,
            object_phrase=thing_surface,
            research_index=agent_index, hit=hit)
    agents.teach_question("What did Engineer design?", relation="designed",
                          answer_field="object", bound_entity="Engineer",
                          answer="Engine")
    agents.teach_question("What did Artist design?", relation="designed",
                          answer_field="object", bound_entity="Artist",
                          answer="Compiler")
    agent_answer = agents.ask("What did Sculptors design?")
    if agent_answer.status != "answered" or agent_answer.answer != "Sculpture":
        raise SystemExit(f"subject-role plural did not transfer through QA: {agent_answer}")
    agent_evidence = next((item for item in agent_answer.language_evidence or []
                           if item.get("kind") == "induced_entity_plural"), None)
    if (agent_evidence is None or agent_evidence.get("shared_roles") != [
            {"relation": "designed", "role": "subject"}]):
        raise SystemExit("subject-role plural answer lost its scoped rule evidence")

    # Multiword head nouns must preserve each name's distinct modifier prefix
    # while learning only the aligned final-token inflection.
    multiword = CRMSKnowledgeBase()
    multi_index = CRMSResearchIndex()
    for subject, entity, surface, sentence, document in (
            ("Ada", "Analytical Engine", "Analytical Engines",
             "Ada designed Analytical Engines.", "analytical"),
            ("Bea", "Steam Engine", "Steam Engines",
             "Bea designed Steam Engines.", "steam"),
            ("Sage", "Electric Motor", "Electric Motor",
             "Sage designed Electric Motor.", "electric")):
        multi_index.add_document(document, sentence, sentence,
                                 f"sources/{document}.txt")
        hit = multi_index.search(sentence, limit=1)[0]
        multiword.add_fact_from_hit(subject, "designed", entity, multi_index, hit)
        multiword.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="designed", obj=entity,
            predicate_phrase="designed", object_phrase=surface,
            research_index=multi_index, hit=hit)
    multiword.teach_question(
        "Who designed Analytical Engine?", relation="designed",
        answer_field="subject", bound_entity="Analytical Engine", answer="Ada")
    multiword.teach_question(
        "Who designed Steam Engine?", relation="designed",
        answer_field="subject", bound_entity="Steam Engine", answer="Bea")
    multiword_answer = multiword.ask("Who designed Electric Motors?")
    if (multiword_answer.status != "answered"
            or multiword_answer.answer != "Sage"
            or not any(item.get("kind") == "induced_entity_plural"
                       for item in multiword_answer.language_evidence or [])):
        raise SystemExit(f"aligned multiword plural did not transfer: {multiword_answer}")

    # Alignment remains explicit: a phrase absent from the cited hit is rejected.
    try:
        kb.teach_fact_pattern_from_hit(
            "Ada designed engines.", subject="Ada", relation="designed",
            obj="Engine", predicate_phrase="designed", object_phrase="motors",
            research_index=index, hit=index.search("engines", limit=1)[0])
    except ValueError:
        pass
    else:
        raise SystemExit("surface phrase absent from the source was accepted")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path, index_path = root / "knowledge.json", root / "index.json"
        cli_kb = CRMSKnowledgeBase()
        cli_index = CRMSResearchIndex()
        cli_index.add_document(
            "engine", "Engine", "Ada designed engines.", "sources/engine.txt")
        hit = cli_index.search("Ada designed engines", limit=1)[0]
        cli_kb.add_fact_from_hit("Ada", "designed", "Engine", cli_index, hit)
        cli_kb.save(knowledge_path)
        cli_index.save(index_path)
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path)],
            input=("/teach-fact Ada|designed|Engine|Ada designed engines|designed|positive|Ada|Engines\n"
                   "/quit\n"), text=True, capture_output=True, check=True, timeout=20)
        if "Stored cited positive fact and sentence example." not in process.stdout:
            raise SystemExit(f"CLI aligned surface teaching failed:\n{process.stdout}")
        restored = CRMSKnowledgeBase.load(knowledge_path)
        if not any(item["alias"] == "engines" and item["entity"] == "Engine"
                   for item in restored.entity_aliases()):
            raise SystemExit("CLI did not persist the source-aligned entity surface")

    print("fact-aligned entity surface diagnostic: PASS")
    print("explicit alignment, subject/object role transfer, citations, retraction, CLI and persistence: PASS")


if __name__ == "__main__":
    main()
