"""Check evidence-backed conversational explanation follow-ups.

Run from the project root with:
    python3 experiments/v1_131_grounded_explanation_followup.py
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    knowledge = CRMSKnowledgeBase()
    knowledge.add_fact("Ada", "designed", "Engine", "source:engine-design")
    knowledge.add_fact("Grace", "designed", "Compiler", "source:compiler-design")
    knowledge.teach_question("Who designed the Engine?", relation="designed",
                             answer_field="subject", bound_entity="Engine",
                             answer="Ada")
    knowledge.teach_question("Who designed the Compiler?", relation="designed",
                             answer_field="subject", bound_entity="Compiler",
                             answer="Grace")

    dialogue = CRMSDialogue(knowledge)
    no_context = dialogue.turn("Why?")
    if no_context.status != "unknown" or "no previous" not in no_context.text:
        raise SystemExit("why without a grounded answer did not abstain")

    answer = dialogue.turn("Who designed the Engine?")
    explanation = dialogue.turn("Why?")
    if (answer.status != "answered" or explanation.status != "answered"
            or explanation.resolved_question != "Who designed the Engine?"
            or "source:engine-design" not in explanation.text):
        raise SystemExit(f"grounded why follow-up omitted its support: {explanation}")
    how_known = dialogue.turn("How do you know that?")
    if (how_known.status != "answered"
            or "source:engine-design" not in how_known.text):
        raise SystemExit(f"evidence follow-up failed: {how_known}")
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory) / "dialogue.json"
        dialogue.save(str(state))
        restored = CRMSDialogue.load(knowledge, str(state))
        persisted = restored.turn("What supports that?")
        if (persisted.status != "answered"
                or "source:engine-design" not in persisted.text):
            raise SystemExit("explanation context did not survive dialogue persistence")

    # Changing from Q&A to a composed about-summary changes what a following
    # evidence request refers to; it must not replay the earlier answer.
    writing_kb = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Ada", "Engine", "source:engine-design"),
            ("Grace", "Compiler", "source:compiler-design")):
        writing_kb.add_fact(subject, "designed", obj, source)
        writing_kb.teach_fact_pattern(
            f"{subject} designed the {obj}.", subject=subject,
            relation="designed", obj=obj, source=source,
            predicate_phrase="designed")
        writing_kb.teach_question(
            f"Who designed the {obj}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject)
        writing_kb.teach_about_frame(f"Tell me about {subject}", entity=subject)
    writing_dialogue = CRMSDialogue(writing_kb)
    writing_dialogue.turn("Who designed the Engine?")
    about = writing_dialogue.turn("Tell me about Ada")
    if about.writing is None or not about.writing.statements:
        raise SystemExit("grounded about-request did not create a summary")
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory) / "writing-dialogue.json"
        writing_dialogue.save(str(state))
        restored_writing = CRMSDialogue.load(writing_kb, str(state))
        writing_explanation = restored_writing.turn("Why?")
        if (writing_explanation.writing is None
                or "source:engine-design" not in writing_explanation.text):
            raise SystemExit("why after a summary did not show its fact support")
        about_followup = CRMSDialogue.load(writing_kb, str(state))
        grace_about = about_followup.turn("What about Grace?")
        if (grace_about.writing is None
                or "Grace designed the Compiler." not in grace_about.text):
            raise SystemExit("about-summary follow-up did not reuse its learned frame")
        grace_explanation = about_followup.turn("Why?")
        if (grace_explanation.writing is None
                or "source:compiler-design" not in grace_explanation.text):
            raise SystemExit("about-summary follow-up lost its source support")
        writing_kb.remove_fact(
            "Grace", "designed", "Compiler", "source:compiler-design")
        stale_summary = about_followup.turn("Why?")
        if (stale_summary.status == "answered"
                or "source:compiler-design" in stale_summary.text):
            raise SystemExit("summary explanation reused retracted fact support")

    # Explanation is recalculated rather than replaying stale answer state.
    if not knowledge.remove_fact("Ada", "designed", "Engine", "source:engine-design"):
        raise SystemExit("could not retract the answer's supporting evidence")
    stale = dialogue.turn("Why is that?")
    if stale.status == "answered" or "source:engine-design" in stale.text:
        raise SystemExit("explanation reused retracted evidence")
    if dialogue.last_question is not None:
        raise SystemExit("stale explanation left a prior question active")

    # Negative answers require explicit negative evidence, and an explanation
    # must lose its support when that evidence is retracted.
    negative_kb = CRMSKnowledgeBase()
    negative_kb.add_fact("Ada", "designed", "Engine", "source:positive")
    negative_kb.add_negative_fact(
        "Grace", "designed", "Compiler", "source:negative")
    negative_kb.teach_polar_question(
        "Did Ada design the Engine?", subject="Ada", relation="designed",
        obj="Engine", answer=True)
    if not negative_kb.teach_polar_question(
            "Did Grace design the Compiler?", subject="Grace",
            relation="designed", obj="Compiler", answer=False):
        raise SystemExit("positive/negative examples did not license a polar frame")
    negative_dialogue = CRMSDialogue(negative_kb)
    negative_answer = negative_dialogue.turn("Did Grace design the Compiler?")
    negative_explanation = negative_dialogue.turn("Why?")
    if (negative_answer.status != "answered"
            or negative_answer.response is None
            or negative_answer.response.truth is not False
            or "Answer: No." not in negative_explanation.text
            or "source:negative" not in negative_explanation.text
            or "source:positive" in negative_explanation.text):
        raise SystemExit("negative explanation omitted its explicit support")
    negative_kb.remove_negative_fact(
        "Grace", "designed", "Compiler", "source:negative")
    stale_negative_explanation = negative_dialogue.turn("Why?")
    if (stale_negative_explanation.status == "answered"
            or "source:negative" in stale_negative_explanation.text):
        raise SystemExit("negative explanation reused retracted evidence")

    # Research mode uses the same query and includes current indexed passages.
    research_kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    for subject, obj in (("Ada", "Engine"), ("Grace", "Compiler")):
        sentence = f"{subject} designed the {obj}."
        doc_id = f"{obj.casefold()}-source"
        index.add_document(doc_id, doc_id, sentence, f"sources/{doc_id}.txt")
        hit = next(item for item in index.search(sentence, limit=5)
                   if item.document_id == doc_id)
        research_kb.add_fact_from_hit(subject, "designed", obj, index, hit)
        research_kb.teach_question(
            f"Who designed the {obj}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject)
    research_dialogue = CRMSDialogue(research_kb)
    research_dialogue.turn("Who designed the Engine?", research_index=index)
    research_explanation = research_dialogue.turn("Why?", research_index=index)
    if (research_explanation.status != "answered"
            or "engine-source#" not in research_explanation.text):
        raise SystemExit("research explanation omitted the indexed citation")

    # Verified rule chaining must expose both its premises and rule id.
    inference_kb = CRMSKnowledgeBase()
    for subject, relation, obj, source in (
            ("Ada", "parent", "Bob", "source:ada-bob"),
            ("Bob", "parent", "Chaz", "source:bob-chaz"),
            ("Grace", "parent", "Finn", "source:grace-finn"),
            ("Finn", "parent", "Gia", "source:finn-gia")):
        inference_kb.add_fact(subject, relation, obj, source)
    inference_kb.add_inference_rule(
        "grandparent-rule", "parent", "parent", "grandparent")
    for obj, answer in (("Chaz", "Ada"), ("Gia", "Grace")):
        inference_kb.teach_question(
            f"Who is the grandparent of {obj}?", relation="grandparent",
            answer_field="subject", bound_entity=obj, answer=answer)
    for subject, obj, source in (
            ("Ruth", "Zoe", "source:ruth-zoe"),
            ("Leo", "Uma", "source:leo-uma")):
        inference_kb.add_fact(subject, "grandparent", obj, source)
        inference_kb.teach_fact_pattern(
            f"{subject} is the grandparent of {obj}.", subject=subject,
            relation="grandparent", obj=obj, source=source,
            predicate_phrase="grandparent")
    inference_kb.teach_about_frame("Tell me about Ada", entity="Ada")
    inference_kb.teach_about_frame("Tell me about Grace", entity="Grace")
    inference_dialogue = CRMSDialogue(inference_kb)
    inference_dialogue.turn("Who is the grandparent of Chaz?")
    inference_explanation = inference_dialogue.turn("How do you know?")
    if (inference_explanation.status != "answered"
            or "grandparent-rule" not in inference_explanation.text
            or "source:ada-bob" not in inference_explanation.text
            or "source:bob-chaz" not in inference_explanation.text):
        raise SystemExit("inference explanation omitted rule or premise lineage")
    derived_about = inference_dialogue.turn("Tell me about Ada")
    if (derived_about.writing is None
            or not any(item.get("inferred") for item in
                       derived_about.writing.statements)
            or "grandparent-rule" not in derived_about.text):
        raise SystemExit("about-summary did not include its verified derived statement")
    derived_about_explanation = inference_dialogue.turn("Why?")
    if (derived_about_explanation.writing is None
            or "grandparent-rule" not in derived_about_explanation.text
            or "source:ada-bob" not in derived_about_explanation.text
            or "source:bob-chaz" not in derived_about_explanation.text):
        raise SystemExit("derived digest explanation omitted proof lineage")
    inference_kb.remove_fact("Bob", "parent", "Chaz", "source:bob-chaz")
    stale_derived_about = inference_dialogue.turn("Why?")
    if (stale_derived_about.status == "written"
            or "grandparent-rule" in stale_derived_about.text
            or "source:bob-chaz" in stale_derived_about.text):
        raise SystemExit("derived digest explanation retained a retracted premise")

    # An unresolved answer keeps its pending choice open when asked to explain.
    ambiguous_kb = CRMSKnowledgeBase()
    for entity in ("Ada", "Grace"):
        ambiguous_kb.add_fact(entity, "designed", "Engine", f"source:{entity}")
    ambiguous_kb.add_fact("Ada", "designed", "Compiler", "source:compiler")
    ambiguous_kb.teach_question("Who designed the Engine?", relation="designed",
                                answer_field="subject", bound_entity="Engine",
                                answer="Ada")
    ambiguous_kb.teach_question("Who designed the Compiler?", relation="designed",
                                answer_field="subject", bound_entity="Compiler",
                                answer="Ada")
    pending = CRMSDialogue(ambiguous_kb)
    ambiguous = pending.turn("Who designed the Engine?")
    if ambiguous.status != "ambiguous" or pending.pending_result is None:
        raise SystemExit("ambiguous question did not establish a pending choice")
    explain_pending = pending.turn("Why?")
    if (explain_pending.status != "ambiguous"
            or pending.pending_result is None
            or "choose a supported answer" not in explain_pending.text):
        raise SystemExit("why follow-up discarded an unresolved answer choice")
    selected = pending.turn("the second one")
    if selected.status != "answered" or selected.response.answer != "Grace":
        raise SystemExit("answer selection failed after explanation clarification")
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory) / "selected-dialogue.json"
        pending.save(str(state))
        restored_pending = CRMSDialogue.load(ambiguous_kb, str(state))
        selected_explanation = restored_pending.turn("Why?")
        if (selected_explanation.status != "answered"
                or "source:Grace" not in selected_explanation.text
                or "source:Ada" in selected_explanation.text):
            raise SystemExit("selected answer explanation lost its filtered evidence")
        stale_selected = CRMSDialogue.load(ambiguous_kb, str(state))
        ambiguous_kb.remove_fact("Grace", "designed", "Engine", "source:Grace")
        stale_selection_explanation = stale_selected.turn("Why?")
        if (stale_selection_explanation.status == "answered"
                or "source:Ada" in stale_selection_explanation.text):
            raise SystemExit("retracted selected answer was replaced by another candidate")

    # Selecting an answer supported by rule chaining must retain its proof,
    # even when another answer has only direct fact support.
    inferred_ambiguity_kb = CRMSKnowledgeBase()
    for subject, relation, obj, source in (
            ("Ada", "parent", "Bob", "source:ada-bob"),
            ("Bob", "parent", "Chaz", "source:bob-chaz"),
            ("Leo", "grandparent", "Chaz", "source:leo-chaz"),
            ("Grace", "parent", "Finn", "source:grace-finn"),
            ("Finn", "parent", "Gia", "source:finn-gia")):
        inferred_ambiguity_kb.add_fact(subject, relation, obj, source)
    inferred_ambiguity_kb.add_inference_rule(
        "grandparent-rule", "parent", "parent", "grandparent")
    inferred_ambiguity_kb.teach_question(
        "Who is grandparent of Chaz?", relation="grandparent",
        answer_field="subject", bound_entity="Chaz", answer="Ada")
    inferred_ambiguity_kb.teach_question(
        "Who is grandparent of Gia?", relation="grandparent",
        answer_field="subject", bound_entity="Gia", answer="Grace")
    inferred_dialogue = CRMSDialogue(inferred_ambiguity_kb)
    inferred_question = inferred_dialogue.turn("Who is grandparent of Chaz?")
    if (inferred_question.status != "ambiguous"
            or not inferred_question.response.inference_proofs):
        raise SystemExit("mixed direct/inferred answers did not create proof ambiguity")
    inferred_selection = inferred_dialogue.turn("the first one")
    if (inferred_selection.status != "answered"
            or inferred_selection.response.answer != "Ada"
            or not inferred_selection.response.inference_proofs
            or "grandparent-rule" in inferred_selection.text
            or "source:ada-bob" in inferred_selection.text
            or "source:bob-chaz" in inferred_selection.text):
        raise SystemExit("selecting an inferred answer lost or mixed its proof lineage")
    inferred_explanation = inferred_dialogue.turn("Why?")
    if (inferred_explanation.status != "answered"
            or "grandparent-rule" not in inferred_explanation.text
            or "source:ada-bob" not in inferred_explanation.text
            or "source:bob-chaz" not in inferred_explanation.text
            or "source:leo-chaz" in inferred_explanation.text):
        raise SystemExit("inferred answer explanation lost candidate-specific proof")

    # Path answers need the complete selected path, not only the terminal edge.
    path_kb = CRMSKnowledgeBase()
    for subject, relation, obj, source in (
            ("Ada", "based in", "Paris", "source:ada-paris"),
            ("Paris", "located in", "France", "source:paris-france"),
            ("Bea", "based in", "Madrid", "source:bea-madrid"),
            ("Madrid", "located in", "Spain", "source:madrid-spain"),
            ("Origin", "based in", "Paris", "source:origin-paris"),
            ("Origin", "based in", "Madrid", "source:origin-madrid")):
        path_kb.add_fact(subject, relation, obj, source)
    path_kb.teach_path_question(
        "Where is Ada based?", relations=["based in", "located in"],
        bound_entity="Ada", answer="France")
    path_kb.teach_path_question(
        "Where is Bea based?", relations=["based in", "located in"],
        bound_entity="Bea", answer="Spain")
    path_dialogue = CRMSDialogue(path_kb)
    path_ambiguous = path_dialogue.turn("Where is Origin based?")
    path_selected = path_dialogue.turn("the first one")
    if (path_ambiguous.status != "ambiguous"
            or path_selected.status != "answered"
            or path_selected.response.answer != "France"
            or len(path_selected.response.proofs or []) != 1
            or [fact["object"] for fact in path_selected.response.proofs[0]]
            != ["Paris", "France"]
            or "source:origin-paris" in path_selected.text
            or "source:paris-france" in path_selected.text
            or "source:origin-madrid" in path_selected.text
            or "source:madrid-spain" in path_selected.text):
        raise SystemExit("path answer selection lost or mixed the selected path proof")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        dialogue_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        session_path = root / "rule-session.json"
        cli_knowledge = CRMSKnowledgeBase()
        for subject, obj, source in (
                ("Ada", "Engine", "source:engine-design"),
                ("Grace", "Compiler", "source:compiler-design")):
            cli_knowledge.add_fact(subject, "designed", obj, source)
            cli_knowledge.teach_fact_pattern(
                f"{subject} designed the {obj}.", subject=subject,
                relation="designed", obj=obj, source=source,
                predicate_phrase="designed")
            cli_knowledge.teach_question(
                f"Who designed the {obj}?", relation="designed",
                answer_field="subject", bound_entity=obj, answer=subject)
            cli_knowledge.teach_about_frame(
                f"Tell me about {subject}", entity=subject)
        cli_knowledge.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(dialogue_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input=("Who designed the Engine?\nWhy?\nTell me about Ada\n"
                   "What about Grace?\nWhy?\n/quit\n"), text=True,
            capture_output=True, check=True, timeout=20)
        if ("Answer: Ada." not in process.stdout
                or "source:engine-design" not in process.stdout
                or "Grace designed the Compiler." not in process.stdout
                or "source:compiler-design" not in process.stdout):
            raise SystemExit(f"terminal evidence follow-up failed:\n{process.stdout}")

    print("grounded explanation follow-up diagnostic: PASS")
    print("fact/rule proofs, positive/negative citations, research, terminal chat, persistence, stale-evidence abstention, pending ambiguity: PASS")


if __name__ == "__main__":
    main()
