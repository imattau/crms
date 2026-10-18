"""Compose learned shared-subject question frames by conjunction."""

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
    for subject, relation, obj in (
            ("Ada", "designed", "Engine"),
            ("Bea", "designed", "Airframe"),
            ("Mira", "designed", "Engine"),
            ("Ada", "built", "Compiler"),
            ("Ada", "built", "Engine"),
            ("Bea", "built", "Rotor"),
            ("Mira", "built", "Rotor"),
            ("Ada", "tested", "Prototype"),
            ("Bea", "tested", "Instrument"),
            ("Ada", "designed", "Research and Development")):
        kb.add_fact(subject, relation, obj, f"source:{subject}:{relation}:{obj}")
    for relation, examples in (
            ("designed", (("Engine", "Ada"), ("Airframe", "Bea"))),
            ("built", (("Compiler", "Ada"), ("Rotor", "Bea"))),
            ("tested", (("Prototype", "Ada"), ("Instrument", "Bea")))):
        for obj, answer in examples:
            kb.teach_question(
                f"Who {relation} {obj}?", relation=relation,
                answer_field="subject", bound_entity=obj, answer=answer)
    for relation, verb, examples in (
            ("designed", "design", (("Ada", "Engine"), ("Bea", "Airframe"))),
            ("built", "build", (("Ada", "Engine"), ("Bea", "Rotor")))):
        for subject, obj in examples:
            kb.teach_question(
                f"Which thing did {subject} {verb}?", relation=relation,
                answer_field="object", bound_entity=subject, answer=obj)
    return kb


def main() -> None:
    kb = make_kb()
    result = kb.ask("Who designed Engine and built Compiler?")
    if (result.status != "answered" or result.answer != "Ada"
            or len(result.matched_templates or []) != 2
            or {item["subject"] for item in result.evidence or []} != {"Ada"}
            or {item["relation"] for item in result.evidence or []}
            != {"designed", "built"}):
        raise SystemExit(f"held-out conjunctive composition failed: {result}")

    three = kb.ask(
        "Who designed Engine, built Compiler, and tested Prototype?")
    if (three.status != "answered" or three.answer != "Ada"
            or {item["relation"] for item in three.evidence or []}
            != {"designed", "built", "tested"}):
        raise SystemExit(f"three-clause composition failed: {three}")

    shared_object = kb.ask("Which thing did Ada design and build?")
    if (shared_object.status != "answered" or shared_object.answer != "Engine"
            or {item["object"] for item in shared_object.evidence or []} != {"Engine"}
            or {item["relation"] for item in shared_object.evidence or []}
            != {"designed", "built"}):
        raise SystemExit(f"shared-object composition failed: {shared_object}")

    compound_entity = kb.ask("Who designed Research and Development?")
    if compound_entity.status != "answered" or compound_entity.answer != "Ada":
        raise SystemExit(f"known entity containing 'and' was split: {compound_entity}")

    disjoint = kb.ask("Who designed Airframe and built Compiler?")
    if disjoint.status != "unknown" or not disjoint.evidence:
        raise SystemExit(f"empty intersection did not abstain: {disjoint}")

    unsupported = kb.ask("Who designed Engine and taught Compiler?")
    if unsupported.status != "unknown":
        raise SystemExit(f"unsupported conjunct was ignored: {unsupported}")

    ambiguous = make_kb()
    ambiguous.add_fact("Cal", "designed", "Engine", "source:cal-design")
    ambiguous.add_fact("Cal", "built", "Compiler", "source:cal-build")
    candidates = ambiguous.ask("Who designed Engine and built Compiler?")
    if (candidates.status != "ambiguous"
            or set(candidates.candidates or []) != {"Ada", "Cal"}):
        raise SystemExit(f"ambiguous intersection was guessed: {candidates}")

    disjunction = kb.ask("Who designed Engine or built Compiler?")
    if (disjunction.status != "ambiguous"
            or set(disjunction.candidates or []) != {"Ada", "Mira"}):
        raise SystemExit(f"wh-question disjunction failed to union answers: {disjunction}")
    unknown_disjunction = kb.ask("Who designed Engine or built Unknown Device?")
    if unknown_disjunction.status != "unknown":
        raise SystemExit(
            f"disjunction silently ignored an open-world unknown: {unknown_disjunction}")
    mixed = kb.ask("Who designed Engine and built Compiler or tested Prototype?")
    if mixed.status != "unknown":
        raise SystemExit(f"mixed logical operators were given implicit precedence: {mixed}")
    too_long = kb.ask(
        "Who " + "very " * 32 + "designed Engine and built Compiler?")
    if too_long.status != "unknown" or "bounded" not in (too_long.request or ""):
        raise SystemExit(f"overlong composition bypassed the parser bound: {too_long}")

    before_research = kb.facts()
    research_index = CRMSResearchIndex()
    research_index.add_document("design-source", "Design source",
                                 "Ada designed Engine.",
                                 "https://research.test/design")
    research_index.add_document("build-source", "Build source",
                                 "Ada built Compiler.",
                                 "https://research.test/build")
    researched = kb.research("Who designed Engine and built Compiler?",
                             research_index)
    citations = {item["citation"].split("#", 1)[0]
                 for item in researched.passages or []}
    if (researched.status != "answered" or researched.response is None
            or researched.response.answer != "Ada"
            or citations != {"design-source", "build-source"}
            or kb.facts() != before_research):
        raise SystemExit(f"research failed to retrieve each conjunct safely: {researched}")

    inference = CRMSKnowledgeBase()
    inference.add_fact("Ada", "designed", "Engine", "source:ada-design")
    inference.add_fact("Engine", "located in", "Rome", "source:engine-location")
    inference.add_fact("Bea", "designed", "Compiler", "source:bea-design")
    inference.add_fact("Compiler", "located in", "Paris", "source:compiler-location")
    inference.add_inference_rule("design-location", "designed", "located in",
                                 "designed in")
    for obj, answer in (("Engine", "Ada"), ("Compiler", "Bea")):
        inference.teach_question(
            f"Who designed {obj}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=answer)
    for place, answer in (("Rome", "Ada"), ("Paris", "Bea")):
        inference.teach_question(
            f"Who designed in {place}?", relation="designed in",
            answer_field="subject", bound_entity=place, answer=answer)
    reasoned = inference.ask("Who designed Engine and designed in Rome?")
    if (reasoned.status != "answered" or reasoned.answer != "Ada"
            or not reasoned.inference_proofs
            or not any(proof.get("rule", {}).get("rule_id") == "design-location"
                       for proof in reasoned.inference_proofs)):
        raise SystemExit(f"composition lost a rule-derived conjunct: {reasoned}")

    polar = CRMSKnowledgeBase()
    polar.add_fact("Ada", "designed", "Engine", "source:design-yes")
    polar.add_fact("Bea", "designed", "Rotor", "source:design-frame")
    polar.add_fact("Ada", "built", "Engine", "source:build-yes")
    polar.add_fact("Bea", "built", "Rotor", "source:build-frame")
    polar.add_negative_fact("Ada", "built", "Compiler", "source:build-no")
    polar.add_negative_fact("Ada", "built", "Tower", "source:tower-no")
    for question, subject, relation, obj, truth in (
            ("Did Ada design Engine?", "Ada", "designed", "Engine", True),
            ("Did Bea design Rotor?", "Bea", "designed", "Rotor", True),
            ("Did Ada build Compiler?", "Ada", "built", "Compiler", False),
            ("Did Bea build Rotor?", "Bea", "built", "Rotor", True),
            ("Did Ada build Tower?", "Ada", "built", "Tower", False)):
        polar.teach_polar_question(question, subject=subject,
                                   relation=relation, obj=obj, answer=truth)
    all_true = polar.ask("Did Ada design Engine and build Engine?")
    one_false = polar.ask("Did Ada design Engine and build Compiler?")
    any_true = polar.ask("Did Ada build Compiler or design Engine?")
    all_false = polar.ask("Did Ada build Compiler or build Tower?")
    unknown_polar = polar.ask("Did Ada design Engine and build Unknown Device?")
    if (all_true.status != "answered" or all_true.truth is not True
            or all_true.answer != "Yes"
            or one_false.status != "answered" or one_false.truth is not False
            or one_false.answer != "No"
            or any_true.status != "answered" or any_true.truth is not True
            or any_true.answer != "Yes"
            or all_false.status != "answered" or all_false.truth is not False
            or all_false.answer != "No"
            or unknown_polar.status != "unknown"):
        raise SystemExit(
            "polar composition mishandled AND/OR/open-world truth: "
            f"{all_true}, {one_false}, {any_true}, {all_false}, {unknown_polar}")
    polar.add_fact("Ada", "built", "Compiler", "source:build-conflict")
    conflict = polar.ask("Did Ada design Engine and build Compiler?")
    disjunctive_conflict = polar.ask(
        "Did Ada build Compiler or design Engine?")
    if conflict.status != "ambiguous" or disjunctive_conflict.status != "ambiguous":
        raise SystemExit(
            "polar conflict was hidden by logical composition: "
            f"{conflict}, {disjunctive_conflict}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        after_load = restored.ask("Who designed Engine and built Compiler?")
        if after_load.status != "answered" or after_load.answer != "Ada":
            raise SystemExit("compositional question failed after persistence")
        index_path = Path(directory) / "index.json"
        research_index.save(index_path)
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--knowledge", str(path), "--index", str(index_path),
             "--dialogue-state", str(Path(directory) / "dialogue.json"),
             "--rules", str(Path(directory) / "rules.json")],
            input="Who designed Engine and built Compiler?\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20)
        if ("Ada" not in process.stdout
                or "source:Ada:designed:Engine" not in process.stdout
                or "source:Ada:built:Compiler" not in process.stdout):
            raise SystemExit(f"terminal chat lost composed answer/provenance:\n{process.stdout}")

    print("compositional question logic diagnostic: PASS")
    print("subject/object AND and OR, two/three-clause transfer, polar logic/conflict, proof-derived conjunct, research per clause, open-world abstention, ambiguity, persistence, terminal chat: PASS")


if __name__ == "__main__":
    main()
