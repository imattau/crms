"""Check lexeme-specific irregular predicate forms learned from evidence.

Run from the project root with:
    python3 experiments/v1_130_grounded_irregular_predicate_forms.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase, ResearchResult
from crms_research import CRMSResearchIndex


def ground(kb: CRMSKnowledgeBase, relation: str, subject: str, obj: str,
           predicate: str, source: str) -> None:
    kb.add_fact(subject, relation, obj, source)
    kb.teach_fact_pattern(
        f"{subject} {predicate} {obj}.", subject=subject,
        relation=relation, obj=obj, source=source,
        predicate_phrase=predicate)


def main() -> None:
    kb = CRMSKnowledgeBase()
    # Establish a varied canonical frame, then ground an irregular surface
    # form to a third fact of that same relation. The mapping is lexical and
    # case-backed; it must not become a productive suffix rule.
    ground(kb, "go", "Ada", "Engine", "go", "source:go-1")
    ground(kb, "go", "Bea", "Compiler", "go", "source:go-2")
    ground(kb, "go", "Sage", "Sculpture", "went", "source:go-past")

    kb.add_fact("Mira", "go", "Tower", "source:mira-go")
    kb.teach_question("Who go the Engine?", relation="go",
                      answer_field="subject", bound_entity="Engine",
                      answer="Ada")
    kb.teach_question("Who go the Compiler?", relation="go",
                      answer_field="subject", bound_entity="Compiler",
                      answer="Bea")
    answer = kb.ask("Who went the Tower?")
    if answer.status != "answered" or answer.answer != "Mira":
        raise SystemExit(f"grounded irregular form did not transfer to QA: {answer}")
    if not any(item.get("surface_form") == "went"
               and item.get("kind") == "observed_predicate_form"
               and "source:go-past" in item["support"][0]["sources"]
               for item in answer.language_evidence or []):
        raise SystemExit("QA omitted the grounded irregular-form evidence")
    rendered_answer = kb.render(answer)
    if ("Observed predicate form: go → went" not in rendered_answer
            or "source:go-past" not in rendered_answer):
        raise SystemExit("answer rendering omitted irregular-form provenance")
    dialogue_turn = CRMSDialogue(kb).turn("Who went the Tower?")
    if (dialogue_turn.status != "answered"
            or "Observed predicate form: go → went" not in dialogue_turn.text):
        raise SystemExit("dialogue failed to render the grounded irregular answer")

    proposal = next((item for item in kb.propose_facts(
        "Rae went Bridge.", source="review:irregular-transfer")
        if item.relation == "go" and item.subject == "Rae"
        and item.object == "Bridge"), None)
    if (proposal is None or not any(
            item.get("kind") == "observed_predicate_form"
            and item.get("surface_form") == "went"
            and "source:go-past" in item["support"][0]["sources"]
            for item in proposal.language_evidence)):
        raise SystemExit("irregular form did not support an attributed review proposal")
    rendered = kb.render_research(
        ResearchResult("needs_review", candidates=[proposal]))
    if ("observed predicate form: go → went" not in rendered
            or "source:go-past" not in rendered):
        raise SystemExit("review output omitted readable irregular-form provenance")
    if any(fact.subject == "Rae" and fact.relation == "go"
           for fact in kb.facts()):
        raise SystemExit("irregular-form proposal was committed automatically")

    index = CRMSResearchIndex()
    index.add_document("went-hit", "Went", "The rover went to the Tower.",
                       "sources/went.txt")
    research = kb.research("go", index, limit=10)
    if not any(item["citation"].startswith("went-hit#")
               for item in research.passages or []):
        raise SystemExit("grounded irregular form did not expand research retrieval")

    # An observed lexeme-specific form must block a conflicting generic past
    # suffix while leaving other independently supported endings available.
    guarded = CRMSKnowledgeBase()
    for relation, subject, obj, base, past, progressive, source in (
            ("walk", "Ada", "Engine", "walk", "walked", "walking", "walk"),
            ("paint", "Bea", "Canvas", "paint", "painted", "painting", "paint")):
        ground(guarded, relation, subject, obj, past, f"{source}-past")
        ground(guarded, relation, subject + "2", obj + "2", progressive,
               f"{source}-progressive")
    for subject, obj, surface, source in (
            ("Dee", "Compiler", "go", "go-base-1"),
            ("Eli", "Brush", "go", "go-base-2"),
            ("Sage", "Sculpture", "went", "go-irregular")):
        ground(guarded, "go", subject, obj, surface, source)
    observed_go = guarded._observed_predicates_by_relation().get(("go",), set())
    go_forms, _ = guarded._predicate_forms_for_relation(
        ("go",), observed_go)
    if not {("went",), ("going",)}.issubset(go_forms) or ("goed",) in go_forms:
        raise SystemExit(f"irregular past did not suppress generic -ed safely: {go_forms}")
    talk_forms, _ = guarded._predicate_forms_for_relation(("talk",), set())
    if ("talked",) not in talk_forms:
        raise SystemExit("irregular go evidence suppressed regular -ed elsewhere")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_answer = restored.ask("Who went the Tower?")
        if (restored_answer.status != "answered"
                or restored_answer.answer != "Mira"):
            raise SystemExit("grounded irregular form did not survive persistence")
        legacy_path = Path(directory) / "legacy-knowledge.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("fact_pattern_predicate_sources", None)
        payload.pop("fact_pattern_surface_sources", None)
        legacy_path.write_text(json.dumps(payload), encoding="utf-8")
        legacy = CRMSKnowledgeBase.load(legacy_path)
        legacy_answer = legacy.ask("Who went the Tower?")
        if legacy_answer.status != "answered" or legacy_answer.answer != "Mira":
            raise SystemExit("legacy frame provenance did not migrate")

    # Retracting one of two citations for the observed irregular example keeps
    # the form licensed by its remaining source; retracting the last one removes
    # that form while preserving the independently taught base frame.
    ground(kb, "go", "Sage", "Sculpture", "went", "source:go-past-backup")
    if not kb.remove_fact("Sage", "go", "Sculpture", "source:go-past"):
        raise SystemExit("could not retract the first irregular-form citation")
    retained = kb.ask("Who went the Tower?")
    if retained.status != "answered" or retained.answer != "Mira":
        raise SystemExit("one remaining citation did not preserve the form")
    evidence = next(item for item in retained.language_evidence or []
                    if item.get("surface_form") == "went")
    if evidence["support"][0]["sources"] != ["source:go-past-backup"]:
        raise SystemExit(f"retracted citation remained in language evidence: {evidence}")
    if not kb.remove_fact("Sage", "go", "Sculpture", "source:go-past-backup"):
        raise SystemExit("could not retract the last irregular-form citation")
    if kb.ask("Who went the Tower?").status != "unknown":
        raise SystemExit("retracted irregular form remained usable in QA")
    if any(item.relation == "go" for item in kb.propose_facts(
            "Rae went Bridge.", source="review:retracted-irregular")):
        raise SystemExit("retracted irregular form remained usable in parsing")
    retracted_research = kb.research("go", index, limit=10)
    if any(item["citation"].startswith("went-hit#")
           for item in retracted_research.passages or []):
        raise SystemExit("retracted irregular form remained a research expansion")

    # Generated writing requires a varied frame, not two citations for each
    # spelling. One remaining grounded example must preserve the irregular
    # form; removing its final distinct example must withdraw it.
    writer = CRMSKnowledgeBase()
    ground(writer, "go", "Ada", "Engine", "go", "source:writer-go-1")
    ground(writer, "go", "Bea", "Compiler", "go", "source:writer-go-2")
    ground(writer, "go", "Sage", "Sculpture", "went", "source:writer-went-1")
    ground(writer, "go", "Tia", "Museum", "went", "source:writer-went-2")
    writer.add_fact("Mira", "go", "Tower", "source:writer-target")
    if "Mira went Tower." not in writer.write_fact("Mira", "go", "Tower"):
        raise SystemExit("varied grounded irregular examples did not license writing")
    writer.remove_fact("Sage", "go", "Sculpture", "source:writer-went-1")
    if "Mira went Tower." not in writer.write_fact("Mira", "go", "Tower"):
        raise SystemExit("remaining irregular example lost its grounded form")
    writer.remove_fact("Tia", "go", "Museum", "source:writer-went-2")
    if any("went" in sentence for sentence in writer.write_fact(
            "Mira", "go", "Tower")):
        raise SystemExit("retracted irregular examples remained in generated writing")

    # An irregular spelling is not abstracted into a rule for unrelated verbs.
    ground(kb, "walk", "Ada", "Engine", "walk", "source:walk-1")
    ground(kb, "walk", "Bea", "Compiler", "walk", "source:walk-2")
    kb.add_fact("Mira", "walk", "Tower", "source:mira-walk")
    kb.teach_question("Who walk the Engine?", relation="walk",
                      answer_field="subject", bound_entity="Engine",
                      answer="Ada")
    kb.teach_question("Who walk the Compiler?", relation="walk",
                      answer_field="subject", bound_entity="Compiler",
                      answer="Bea")
    if any(item.relation == "walk" for item in kb.propose_facts(
            "Mira went the Tower?", source="review:irregular-control")):
        raise SystemExit("the go/went exception leaked to an unrelated relation")

    negative = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Ada", "Engine", "negative:1"),
            ("Bea", "Compiler", "negative:2")):
        negative.add_negative_fact(subject, "admire", obj, source)
        negative.teach_fact_pattern(
            f"{subject} did not admire {obj}.", subject=subject,
            relation="admire", obj=obj, source=source,
            predicate_phrase="admire", polarity=False)
    if not any(not candidate.polarity and candidate.relation == "admire"
               for candidate in negative.propose_facts(
                   "Sage did not admire Sculpture.", source="review:negative")):
        raise SystemExit("grounded negative frame did not transfer")
    negative.remove_negative_fact("Ada", "admire", "Engine", "negative:1")
    if any(not candidate.polarity and candidate.relation == "admire"
           for candidate in negative.propose_facts(
               "Sage did not admire Sculpture.", source="review:negative")):
        raise SystemExit("retracted negative-frame evidence remained licensed")

    # A single irregular observation cannot license itself without a grounded
    # base frame and factual support; unobserved forms remain unavailable.
    isolated = CRMSKnowledgeBase()
    isolated.add_fact("Sage", "see", "Sculpture", "source:see")
    isolated.teach_fact_pattern(
        "Sage saw Sculpture.", subject="Sage", relation="see",
        obj="Sculpture", source="source:see", predicate_phrase="saw")
    if isolated._observed_predicates_by_relation().get(("see",)):
        raise SystemExit("one example licensed an unvaried irregular frame")

    print("grounded irregular predicate form diagnostic: PASS")
    print("lexeme-specific QA, review-only proposal, research retrieval, writing threshold, source retraction, evidence, persistence: PASS")


if __name__ == "__main__":
    main()
