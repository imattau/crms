"""Measure grounded question-frame learning and cross-surface transfer.

The benchmark uses only invented entities, public fact/question teaching APIs,
and exact answer plus source checks. It measures frame-slot transfer, derives
endpoint questions from source-backed sentence patterns, and separates
article/case normalization, paraphrase transfer, synonym transfer, and
near-miss safety. It is diagnostic: weak transfer is reported, not treated as
a reason to loosen CRMS's evidence gates.

Run with: python3 experiments/v1_315_cross_surface_question_transfer.py
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


RELATIONS: dict[str, dict[str, object]] = {
    "created": {
        "answer_field": "subject",
        "entities": [(f"Mara Vell {i}", f"Orrin Engine {i}") for i in range(12)],
        "train": ("Who created {object}?",
                  "Who was the creator of {object}?",
                  "{object} was created by whom?"),
        "surface": ("who created {object}?", "Who created the {object}?"),
        "paraphrase": ("Who designed {object}?", "Who invented {object}?"),
        "synonym": ("Who made {object}?",),
        "negative": ("Who destroyed {object}?", "What created {object}?"),
    },
    "capital of": {
        "answer_field": "subject",
        "entities": [(f"Veyra City {i}", f"Nolune Country {i}") for i in range(12)],
        "train": ("What is the capital of {object}?",
                  "Which city is the capital of {object}?",
                  "What city serves as the capital of {object}?"),
        "surface": ("what is the capital of {object}?",
                    "What is the capital of the {object}?"),
        "paraphrase": ("Which city is the seat of government of {object}?",
                       "What city is {object}'s capital?"),
        "synonym": ("What is the chief city of {object}?",),
        "negative": ("What is the largest city of {object}?",
                     "What is the capital of {object} and its neighbor?"),
    },
    "located in": {
        "answer_field": "subject",
        "entities": [(f"Ilyan Archive {i}", f"Sereva Region {i}") for i in range(12)],
        "train": ("What is located in {object}?",
                  "What can be found in {object}?",
                  "Which place is located within {object}?"),
        "surface": ("what is located in {object}?", "What is located in the {object}?"),
        "paraphrase": ("Which thing is situated in {object}?",
                       "What can be found within {object}?"),
        "synonym": ("What lies in {object}?",),
        "negative": ("What is near {object}?", "Where is {object} located?"),
    },
    "discovered": {
        "answer_field": "subject",
        "entities": [(f"Tarin Sol {i}", f"Eshar Particle {i}") for i in range(12)],
        "train": ("Who discovered {object}?",
                  "Who was the discoverer of {object}?",
                  "{object} was discovered by whom?"),
        "surface": ("who discovered {object}?", "Who has discovered {object}?"),
        "paraphrase": ("Which person first identified {object}?",
                       "Who made the discovery of {object}?"),
        "synonym": ("Who found {object}?",),
        "negative": ("Who studied {object}?", "What did {object} discover?"),
    },
    "parent of": {
        "answer_field": "subject",
        "entities": [(f"Neris Vale {i}", f"Omi Vale {i}") for i in range(12)],
        "train": ("Who is a parent of {object}?",
                  "Who is the parent of {object}?",
                  "{object} is the child of whom?"),
        "surface": ("who is a parent of {object}?", "Who is a parent of the {object}?"),
        "paraphrase": ("Which person has {object} as their child?",
                       "Who is {object}'s parent?"),
        "synonym": ("Who raised {object}?",),
        "negative": ("Who is a sibling of {object}?", "Who is a parent?"),
    },
    "flows through": {
        "answer_field": "subject",
        "entities": [(f"Aven River {i}", f"Mireth Valley {i}") for i in range(12)],
        "train": ("What flows through {object}?",
                  "Which river flows through {object}?",
                  "What passes through {object}?"),
        "surface": ("what flows through {object}?", "What flows through the {object}?"),
        "paraphrase": ("Which river runs through {object}?",
                       "What waterway crosses {object}?"),
        "synonym": ("What streams across {object}?",),
        "negative": ("What flows beside {object}?", "Where does {object} flow?"),
    },
}

K_VALUES = (0, 1, 2, 3)
TRAINING_ENTITIES = 2


def _template_signature(template: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\{[^}]+\}|[\w]+", template.casefold()))


def _licensed_explicit_templates(kb: CRMSKnowledgeBase) -> set[tuple[str, ...]]:
    """Return frame templates licensed by distinct fact-backed examples."""
    templates = set()
    for key, examples in kb._question_examples.items():
        if not kb._question_frame_is_licensed(key, examples):
            continue
        _relation, answer_field, prefix, suffix = key
        slot = "{object}" if answer_field == "subject" else "{subject}"
        templates.add(_template_signature(" ".join((*prefix, slot, *suffix))))
    return templates


def ask_signature(kb: CRMSKnowledgeBase, question: str,
                  expected: str, source: str) -> tuple[str, str]:
    result = kb.ask(question)
    if result.status != "answered":
        return "abstained", "none"
    if (result.answer == expected
            and any(source in fact.get("sources", ())
                    for fact in (result.evidence or []))):
        matched = {_template_signature(template)
                   for template in result.matched_templates or []}
        if matched & _licensed_explicit_templates(kb):
            return "correct", "licensed_question_frame"
        if result.language_evidence:
            return "correct", "derived_language_frame"
        return "correct", "direct_or_builtin"
    return "wrong", "none"


def evaluate_surface(kb: CRMSKnowledgeBase, relation: str,
                     question_template: str, entities: list[tuple[str, str]],
                     answer_field: str) -> dict[str, int]:
    counts = {"correct": 0, "wrong": 0, "abstained": 0,
              "licensed_transfer": 0, "derived_transfer": 0,
              "direct_or_builtin": 0}
    for subject, obj in entities[TRAINING_ENTITIES:]:
        answer = subject if answer_field == "subject" else obj
        source = f"fixture:{relation}:{subject.casefold().replace(' ', '-')}"
        question = question_template.format(subject=subject, object=obj)
        outcome, route = ask_signature(kb, question, answer, source)
        counts[outcome] += 1
        if outcome == "correct":
            if route == "licensed_question_frame":
                counts["licensed_transfer"] += 1
            elif route == "derived_language_frame":
                counts["derived_transfer"] += 1
            else:
                counts["direct_or_builtin"] += 1
    return counts


def run_benchmark() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for relation, spec in RELATIONS.items():
        entities = spec["entities"]
        answer_field = str(spec["answer_field"])
        train_templates = spec["train"]
        for k in K_VALUES:
            kb = CRMSKnowledgeBase()
            for subject, obj in entities:
                source = f"fixture:{relation}:{subject.casefold().replace(' ', '-')}"
                kb.add_fact(subject, relation, obj, source)
            for template in train_templates[:k]:
                for subject, obj in entities[:TRAINING_ENTITIES]:
                    answer = subject if answer_field == "subject" else obj
                    bound = obj if answer_field == "subject" else subject
                    kb.teach_question(
                        template.format(subject=subject, object=obj),
                        relation=relation, answer_field=answer_field,
                        bound_entity=bound, answer=answer)

            canonical_class = "B" if k == 0 else "T"
            classes = {
                canonical_class: (train_templates[:1],),
                "S": (spec["surface"],),
                "P": (spec["paraphrase"],),
                "L": (spec["synonym"],),
                "N": (spec["negative"],),
                # Additional explicit frames taught in this regime are tested
                # on held-out entities separately from untaught paraphrases.
                "G": (train_templates[1:k],),
            }
            # Keep exact taught templates out of the held-out transfer metric.
            # The T control measures entity-slot generalization for the first frame.
            for category, (templates,) in classes.items():
                for template in templates:
                    counts = evaluate_surface(
                        kb, relation, template, entities, answer_field)
                    rows.append({
                        "relation": relation, "k": k, "class": category,
                        "template": template, "n": len(entities) - TRAINING_ENTITIES,
                        **counts,
                        "template_was_taught": template in train_templates[:k],
                    })

    summaries = []
    for k in K_VALUES:
        selected = [row for row in rows if row["k"] == k]
        totals = {name: {key: sum(int(row[key]) for row in selected
                                  if row["class"] == name)
                         for key in ("n", "correct", "wrong", "abstained",
                                     "licensed_transfer", "derived_transfer",
                                     "direct_or_builtin")}
                  for name in ("B", "T", "S", "P", "L", "N", "G")}
        transfer_rows = [row for row in selected
                         if row["class"] in {"S", "P", "L"}
                         and not row["template_was_taught"]]
        transfer_correct = sum(
            int(row["licensed_transfer"] + row["derived_transfer"])
            for row in transfer_rows)
        transfer_n = sum(int(row["n"]) for row in transfer_rows)
        canonical_name = "B" if k == 0 else "T"
        canonical_accuracy = (
            totals[canonical_name]["correct"] / totals[canonical_name]["n"]
            if totals[canonical_name]["n"] else 0.0)
        transfer_ratio = ((transfer_correct / transfer_n) / canonical_accuracy
                          if transfer_n and canonical_accuracy else 0.0)
        summaries.append({
            "k": k, "canonical_class": canonical_name, "classes": totals,
            "canonical_accuracy": canonical_accuracy,
            "heldout_transfer_correct": transfer_correct,
            "heldout_transfer_n": transfer_n,
            "heldout_answer_correct": sum(int(row["correct"])
                                           for row in transfer_rows),
            "direct_or_builtin_on_transfer_set": sum(
                int(row["direct_or_builtin"]) for row in transfer_rows),
            "heldout_transfer_ratio": transfer_ratio,
            "near_miss_wrong": totals["N"]["wrong"],
        })

    rule_transfer = nominal_to_verb_transfer_check()
    aspect_transfer = grounded_perfect_aspect_transfer_check()
    declarative_question_transfer = fact_pattern_to_question_transfer_check()
    predicate_transfer = grounded_predicate_transfer_check()
    chat_transfer = grounded_chat_do_support_transfer_check()
    passive_chat_transfer = grounded_chat_passive_voice_transfer_check()
    return {
        "benchmark": "crms-cross-surface-question-transfer-v1",
        "entities_per_relation": len(next(iter(RELATIONS.values()))["entities"]),
        "training_entities_per_relation": TRAINING_ENTITIES,
        "k_values": list(K_VALUES),
        "rows": rows,
        "summaries": summaries,
        "grounded_rule_transfer": rule_transfer,
        "grounded_perfect_aspect_transfer": aspect_transfer,
        "fact_pattern_to_question_transfer": declarative_question_transfer,
        "grounded_predicate_transfer": predicate_transfer,
        "grounded_chat_do_support_transfer": chat_transfer,
        "grounded_chat_passive_voice_transfer": passive_chat_transfer,
    }


def nominal_to_verb_transfer_check() -> dict[str, object]:
    """Check a generated question frame and its inspectable rule lineage."""
    kb = CRMSKnowledgeBase()
    examples = (
        ("Mara Vell", "Orrin Engine", "fixture:nominal:orrin"),
        ("Nema Tor", "Vesk Engine", "fixture:nominal:vesk"),
        ("Rila Sen", "Tavor Engine", "fixture:nominal:tavor"),
    )
    for subject, obj, source in examples:
        kb.add_fact(subject, "created", obj, source)
    for subject, obj, _source in examples[:2]:
        kb.teach_question(
            f"Who is the creator of {obj}?", relation="created",
            answer_field="subject", bound_entity=obj, answer=subject)
    result = kb.ask("Who created Tavor Engine?")
    trace = next((item for item in result.language_evidence or []
                  if item.get("kind")
                  == "regular_agent_noun_to_verb_question_frame"), None)
    expected_sources = [examples[0][2], examples[1][2]]
    if (result.status != "answered" or result.answer != "Rila Sen"
            or not any(examples[2][2] in fact.get("sources", ())
                       for fact in result.evidence or [])
            or trace is None
            or trace.get("licensed_frame") != "who is the creator of"
            or trace.get("derived_frame") != "who created"
            or sorted(source for example in trace["supporting_examples"]
                      for source in example["sources"]) != expected_sources):
        raise SystemExit(f"grounded nominal-to-verb frame transfer failed: {result}")
    unsupported = kb.ask("Who crafted Tavor Engine?")
    if unsupported.status == "answered":
        raise SystemExit("an unlicensed predicate synonym was answered")
    return {
        "status": "passed",
        "licensed_frame": trace["licensed_frame"],
        "derived_frame": trace["derived_frame"],
        "licensing_sources": expected_sources,
        "answer_source": examples[2][2],
        "unlicensed_synonym_status": unsupported.status,
    }


def grounded_perfect_aspect_transfer_check() -> dict[str, object]:
    """Apply the bounded ``has + regular -ed`` frame to a held-out fact."""
    kb = CRMSKnowledgeBase()
    examples = (
        ("Mara Vell", "Eshar Particle", "fixture:aspect:es",),
        ("Nema Tor", "Veyra Particle", "fixture:aspect:ve",),
        ("Rila Sen", "Tavor Particle", "fixture:aspect:ta",),
    )
    for subject, obj, source in examples:
        kb.add_fact(subject, "discovered", obj, source)
    for subject, obj, _source in examples[:2]:
        kb.teach_question(
            f"Who discovered {obj}?", relation="discovered",
            answer_field="subject", bound_entity=obj, answer=subject)
    question = "Who has discovered Tavor Particle?"
    result = kb.ask(question)
    trace = next((item for item in result.language_evidence or []
                  if item.get("kind") == "regular_perfect_aspect_question_frame"),
                 None)
    if (result.status != "answered" or result.answer != "Rila Sen"
            or not any(examples[2][2] in fact.get("sources", ())
                       for fact in result.evidence or [])
            or trace is None
            or trace.get("licensed_frame") != "who discovered"
            or trace.get("derived_frame") != "who has discovered"
            or len(trace.get("supporting_examples", [])) != 2):
        raise SystemExit(f"regular perfect-aspect transfer failed: {result}")
    if kb.ask("Who has destroyed Tavor Particle?").status == "answered":
        raise SystemExit("perfect-aspect frame answered an unlicensed predicate")
    return {"status": "passed", "question": question,
            "answer": result.answer, "answer_source": examples[2][2],
            "trace": trace}


def fact_pattern_to_question_transfer_check() -> dict[str, object]:
    """Derive endpoint questions and retain them in an indexed fact store."""
    kb = CRMSKnowledgeBase()
    for number in range(2_000):
        kb.add_fact(f"Archive Person {number}", "mentions",
                    f"Archive Item {number}", f"fixture:noise:{number}")
    examples = (
        ("Mara Vell", "Orrin Engine", "fixture:decl:orrin",
         "Mara Vell made Orrin Engine."),
        ("Nema Tor", "Vesk Engine", "fixture:decl:vesk",
         "Nema Tor made Vesk Engine."),
        ("Rila Sen", "Tavor Engine", "fixture:decl:tavor",
         "Rila Sen made Tavor Engine."),
    )
    for subject, obj, source, _sentence in examples:
        kb.add_fact(subject, "created", obj, source)
    for subject, obj, source, sentence in examples[:2]:
        kb.teach_fact_pattern(
            sentence, subject=subject, relation="created", obj=obj,
            source=source, predicate_phrase="made")

    one_example = CRMSKnowledgeBase()
    for subject, obj, source, _sentence in examples:
        one_example.add_fact(subject, "created", obj, source)
    subject, obj, source, sentence = examples[0]
    one_example.teach_fact_pattern(
        sentence, subject=subject, relation="created", obj=obj,
        source=source, predicate_phrase="made")
    if one_example.ask("What did Rila Sen make?").status == "answered":
        raise SystemExit("one sentence pattern licensed a derived question frame")

    subject_question = "Who made Tavor Engine?"
    object_question = "What did Rila Sen make?"
    active_to_passive_subject = "Who was Tavor Engine made by?"
    active_to_passive_object = "What was made by Rila Sen?"
    subject_result = kb.ask(subject_question)
    object_result = kb.ask(object_question)
    active_to_passive_results = (
        kb.ask(active_to_passive_subject), kb.ask(active_to_passive_object))
    expected_source = examples[2][2]
    for result, answer in ((subject_result, "Rila Sen"),
                           (object_result, "Tavor Engine")):
        trace = next((item for item in result.language_evidence or []
                      if item.get("kind")
                      == "fact_pattern_derived_question_frame"), None)
        if (result.status != "answered" or result.answer != answer
                or not any(expected_source in fact.get("sources", ())
                           for fact in result.evidence or [])
                or trace is None):
            raise SystemExit(
                f"declarative-to-question transfer was not held out: {result}")
        training_sources = trace.get("lineage", {}).get("training_sources", [])
        if expected_source in training_sources:
            raise SystemExit("held-out source leaked into derived question frame")
    for result, answer, kind in (
            (active_to_passive_results[0], "Rila Sen",
             "active_to_passive_subject_question"),
            (active_to_passive_results[1], "Tavor Engine",
             "active_to_passive_object_question")):
        trace = next((item for item in result.language_evidence or []
                      if item.get("kind")
                      == "fact_pattern_derived_question_frame"), None)
        if (result.status != "answered"
                or result.answer != answer
                or trace is None
                or trace.get("derivation", {}).get("kind") != kind
                or not any(expected_source in fact.get("sources", ())
                           for fact in result.evidence or [])
                or expected_source in trace.get("lineage", {}).get(
                    "training_sources", [])):
            raise SystemExit(f"active-to-passive question transfer failed: {result}")
    if one_example.ask(active_to_passive_subject).status == "answered":
        raise SystemExit("one active pattern licensed passive question transfer")
    if kb.ask("Who crafted Tavor Engine?").status == "answered":
        raise SystemExit("fact-pattern question derivation guessed a synonym")
    if kb.ask("What did Tavor Engine make?").status == "answered":
        raise SystemExit("fact-pattern question derivation swapped endpoint roles")

    # The generated frame is reconstructed from persisted pattern evidence and
    # disappears when its licensing source examples are retracted.
    with tempfile.TemporaryDirectory(prefix="crms-declarative-frame-") as folder:
        saved_path = Path(folder) / "knowledge.sqlite"
        kb.save(saved_path)
        restored = CRMSKnowledgeBase.load(saved_path)
        if restored.ask(object_question).answer != "Tavor Engine":
            raise SystemExit("derived question frame did not survive reload")
        for subject, obj, source, _sentence in examples[:2]:
            if not restored.remove_fact(subject, "created", obj, source):
                raise SystemExit("could not retract question-frame training source")
        if restored.ask(object_question).status == "answered":
            raise SystemExit("retracted examples left a derived question frame active")

    passive = CRMSKnowledgeBase()
    passive_examples = (
        ("Mara Vell", "Orrin Engine", "fixture:passive:orrin",
         "Orrin Engine was made by Mara Vell."),
        ("Nema Tor", "Vesk Engine", "fixture:passive:vesk",
         "Vesk Engine was made by Nema Tor."),
        ("Rila Sen", "Tavor Engine", "fixture:passive:tavor",
         "Tavor Engine was made by Rila Sen."),
    )
    for subject, obj, source, _sentence in passive_examples:
        passive.add_fact(subject, "created", obj, source)
    for subject, obj, source, sentence in passive_examples[:2]:
        passive.teach_fact_pattern(
            sentence, subject=subject, relation="created", obj=obj,
            source=source, predicate_phrase="made")
    passive_subject_question = "Who was Tavor Engine made by?"
    passive_object_question = "What was made by Rila Sen?"
    passive_results = (passive.ask(passive_subject_question),
                       passive.ask(passive_object_question))
    for result, expected_answer, expected_kind in (
            (passive_results[0], "Rila Sen",
             "fact_pattern_passive_subject_question"),
            (passive_results[1], "Tavor Engine",
             "fact_pattern_passive_object_question")):
        trace = next((item for item in result.language_evidence or []
                      if item.get("kind")
                      == "fact_pattern_derived_question_frame"), None)
        if (result.status != "answered" or result.answer != expected_answer
                or not any(passive_examples[2][2] in fact.get("sources", ())
                           for fact in result.evidence or [])
                or trace is None
                or trace.get("derivation", {}).get("kind") != expected_kind
                or passive_examples[2][2] in trace.get("lineage", {}).get(
                    "training_sources", [])):
            raise SystemExit(f"passive question-frame induction failed: {result}")
    passive_to_active_questions = ("Who made Tavor Engine?",
                                   "What did Rila Sen make?")
    passive_to_active_results = tuple(
        passive.ask(question) for question in passive_to_active_questions)
    for result, answer, kind in (
            (passive_to_active_results[0], "Rila Sen",
             "passive_to_active_subject_question"),
            (passive_to_active_results[1], "Tavor Engine",
             "passive_to_active_object_question")):
        trace = next((item for item in result.language_evidence or []
                      if item.get("kind")
                      == "fact_pattern_derived_question_frame"), None)
        if (result.status != "answered" or result.answer != answer
                or trace is None
                or trace.get("derivation", {}).get("kind") != kind
                or not any(passive_examples[2][2] in fact.get("sources", ())
                           for fact in result.evidence or [])):
            raise SystemExit(f"passive-to-active transfer failed: {result}")
    if passive.ask("Who was Rila Sen made by?").status == "answered":
        raise SystemExit("passive question-frame derivation swapped fact roles")
    if passive.ask("What was crafted by Rila Sen?").status == "answered":
        raise SystemExit("passive question-frame derivation guessed a synonym")

    malformed_passive = CRMSKnowledgeBase()
    malformed_examples = (
        ("Mara Vell", "Orrin Instrument", "fixture:bad-passive:orrin",
         "Orrin Instrument was saw by Mara Vell."),
        ("Nema Tor", "Vesk Instrument", "fixture:bad-passive:vesk",
         "Vesk Instrument was saw by Nema Tor."),
        ("Rila Sen", "Tavor Instrument", "fixture:bad-passive:tavor",
         "Tavor Instrument was saw by Rila Sen."),
    )
    for subject, obj, source, _sentence in malformed_examples:
        malformed_passive.add_fact(subject, "noticed", obj, source)
    for subject, obj, source, sentence in malformed_examples[:2]:
        malformed_passive.teach_fact_pattern(
            sentence, subject=subject, relation="noticed", obj=obj,
            source=source, predicate_phrase="saw")
    if malformed_passive.ask(
            "Who was Tavor Instrument seen by?").status == "answered":
        raise SystemExit("active past form was misread as a passive participle")

    irregular_voice = CRMSKnowledgeBase()
    irregular_examples = (
        ("Mara Vell", "Orrin Instrument", "fixture:saw:orrin",
         "Mara Vell saw Orrin Instrument."),
        ("Nema Tor", "Vesk Instrument", "fixture:saw:vesk",
         "Nema Tor saw Vesk Instrument."),
        ("Rila Sen", "Tavor Instrument", "fixture:saw:tavor",
         "Rila Sen saw Tavor Instrument."),
    )
    for subject, obj, source, _sentence in irregular_examples:
        irregular_voice.add_fact(subject, "noticed", obj, source)
    for subject, obj, source, sentence in irregular_examples[:2]:
        irregular_voice.teach_fact_pattern(
            sentence, subject=subject, relation="noticed", obj=obj,
            source=source, predicate_phrase="saw")
    irregular_passive = irregular_voice.ask(
        "Who was Tavor Instrument seen by?")
    irregular_trace = next((item for item in irregular_passive.language_evidence or []
                            if item.get("kind")
                            == "fact_pattern_derived_question_frame"), None)
    if (irregular_passive.status != "answered"
            or irregular_passive.answer != "Rila Sen"
            or not any(irregular_examples[2][2] in fact.get("sources", ())
                       for fact in irregular_passive.evidence or [])
            or irregular_trace is None
            or irregular_trace.get("derivation", {}).get("derived_question_frame")
            != "who was {object} seen by"):
        raise SystemExit(
            f"irregular active-to-passive transfer failed: {irregular_passive}")
    irregular_passive_voice = CRMSKnowledgeBase()
    irregular_passive_examples = (
        ("Mara Vell", "Orrin Instrument", "fixture:seen:orrin",
         "Orrin Instrument was seen by Mara Vell."),
        ("Nema Tor", "Vesk Instrument", "fixture:seen:vesk",
         "Vesk Instrument was seen by Nema Tor."),
        ("Rila Sen", "Tavor Instrument", "fixture:seen:tavor",
         "Tavor Instrument was seen by Rila Sen."),
    )
    for subject, obj, source, _sentence in irregular_passive_examples:
        irregular_passive_voice.add_fact(subject, "noticed", obj, source)
    for subject, obj, source, sentence in irregular_passive_examples[:2]:
        irregular_passive_voice.teach_fact_pattern(
            sentence, subject=subject, relation="noticed", obj=obj,
            source=source, predicate_phrase="seen")
    irregular_active = irregular_passive_voice.ask("Who saw Tavor Instrument?")
    irregular_active_object = irregular_passive_voice.ask(
        "What did Rila Sen see?")
    for result, answer, kind in (
            (irregular_active, "Rila Sen",
             "passive_to_active_subject_question"),
            (irregular_active_object, "Tavor Instrument",
             "passive_to_active_object_question")):
        trace = next((item for item in result.language_evidence or []
                      if item.get("kind")
                      == "fact_pattern_derived_question_frame"), None)
        if (result.status != "answered" or result.answer != answer
                or trace is None
                or trace.get("derivation", {}).get("kind") != kind):
            raise SystemExit(f"irregular passive-to-active transfer failed: {result}")
    return {"status": "passed", "subject_question": subject_question,
            "subject_answer": subject_result.answer,
            "object_question": object_question,
            "object_answer": object_result.answer,
            "active_to_passive_subject_question": active_to_passive_subject,
            "active_to_passive_subject_answer": active_to_passive_results[0].answer,
            "active_to_passive_object_question": active_to_passive_object,
            "active_to_passive_object_answer": active_to_passive_results[1].answer,
            "passive_subject_question": passive_subject_question,
            "passive_subject_answer": passive_results[0].answer,
            "passive_object_question": passive_object_question,
            "passive_object_answer": passive_results[1].answer,
            "passive_to_active_subject_question": passive_to_active_questions[0],
            "passive_to_active_subject_answer": passive_to_active_results[0].answer,
            "passive_to_active_object_question": passive_to_active_questions[1],
            "passive_to_active_object_answer": passive_to_active_results[1].answer,
            "irregular_passive_question": "Who was Tavor Instrument seen by?",
            "irregular_passive_answer": irregular_passive.answer,
            "malformed_passive_status": malformed_passive.ask(
                "Who was Tavor Instrument seen by?").status,
            "held_out_source": expected_source,
            "licensing_sources": [examples[0][2], examples[1][2]],
            "one_example_status": one_example.ask(
                "What did Rila Sen make?").status,
            "unsupported_synonym_status": kb.ask(
                "Who crafted Tavor Engine?").status,
            "role_swap_status": kb.ask(
                "What did Tavor Engine make?").status}


def grounded_predicate_transfer_check() -> dict[str, object]:
    """Transfer a source-backed predicate through both question argument roles."""
    kb = CRMSKnowledgeBase()
    examples = (
        ("Mara Vell", "Orrin Engine", "fixture:made:orrin"),
        ("Nema Tor", "Vesk Engine", "fixture:made:vesk"),
        ("Rila Sen", "Tavor Engine", "fixture:made:tavor"),
    )
    for subject, obj, source in examples:
        kb.add_fact(subject, "created", obj, source)
    for subject, obj, _source in examples[:2]:
        kb.teach_question(
            f"Who created {obj}?", relation="created", answer_field="subject",
            bound_entity=obj, answer=subject)

    heldout_question = "Who made Tavor Engine?"
    if kb.ask(heldout_question).status == "answered":
        raise SystemExit("unlicensed predicate wording answered before learning")
    first_subject, first_object, first_source = examples[0]
    if kb.teach_fact_pattern(
            f"{first_subject} made {first_object}.", subject=first_subject,
            relation="created", obj=first_object, source=first_source,
            predicate_phrase="made"):
        raise SystemExit("one fact-pattern example licensed predicate transfer")
    if kb.ask(heldout_question).status == "answered":
        raise SystemExit("one fact-pattern example transferred predicate wording")

    second_subject, second_object, second_source = examples[1]
    if not kb.teach_fact_pattern(
            f"{second_subject} made {second_object}.", subject=second_subject,
            relation="created", obj=second_object, source=second_source,
            predicate_phrase="made"):
        raise SystemExit("two varied fact-pattern examples did not license transfer")
    result = kb.ask(heldout_question)
    trace = next((item for item in result.language_evidence or []
                  if item.get("kind") == "observed_predicate_form"
                  and item.get("surface_form") == "made"), None)
    if (result.status != "answered" or result.answer != "Rila Sen"
            or not any(examples[2][2] in fact.get("sources", ())
                       for fact in result.evidence or [])
            or trace is None
            or trace.get("canonical_form") != "created"
            or sorted(trace["support"][0]["sources"])
            != sorted((first_source, second_source))):
        raise SystemExit(f"grounded predicate transfer failed: {result}")
    if kb.ask("Who crafted Tavor Engine?").status == "answered":
        raise SystemExit("unsupported synonym was accepted by predicate transfer")

    # Do-support requires the infinitive: the learned past form ``made`` must
    # transfer to ``make`` in ``What did Y make?`` without licensing an
    # unrelated synonym or transferring after only one observed example.
    inverse = CRMSKnowledgeBase()
    for subject, obj, source in examples:
        inverse.add_fact(subject, "created", obj, source)
    for subject, obj, _source in examples[:2]:
        inverse.teach_question(
            f"What did {subject} create?", relation="created",
            answer_field="object", bound_entity=subject, answer=obj)
    inverse_license_states = []
    for subject, obj, source in examples[:2]:
        inverse_license_states.append(inverse.teach_fact_pattern(
                f"{subject} made {obj}.", subject=subject,
                relation="created", obj=obj, source=source,
                predicate_phrase="made"))
    if inverse_license_states != [False, True]:
        raise SystemExit("inverse predicate transfer licensing threshold changed")
    inverse_question = "What did Rila Sen make?"
    inverse_result = inverse.ask(inverse_question)
    inverse_trace = next((item for item in inverse_result.language_evidence or []
                          if item.get("kind")
                          == "irregular_do_support_question_transfer"), None)
    if (inverse_result.status != "answered"
            or inverse_result.answer != "Tavor Engine"
            or not any(examples[2][2] in fact.get("sources", ())
                       for fact in inverse_result.evidence or [])
            or inverse_trace is None
            or inverse_trace.get("observed_form") != "made"
            or inverse_trace.get("surface_form") != "make"
            or sorted(source for item in inverse_trace["support"]
                      for source in item.get("sources", []))
            != sorted((examples[0][2], examples[1][2]))):
        raise SystemExit(
            f"grounded irregular do-support transfer failed: {inverse_result}")

    one_example = CRMSKnowledgeBase()
    for subject, obj, source in examples:
        one_example.add_fact(subject, "created", obj, source)
    subject, obj, source = examples[0]
    one_example.teach_question(
        f"What did {subject} create?", relation="created",
        answer_field="object", bound_entity=subject, answer=obj)
    one_example.teach_fact_pattern(
        f"{subject} made {obj}.", subject=subject, relation="created",
        obj=obj, source=source, predicate_phrase="made")
    one_example_inverse_status = one_example.ask(
        "What did Rila Sen make?").status
    if one_example_inverse_status == "answered":
        raise SystemExit("one irregular predicate example licensed transfer")
    inverse_synonym_status = inverse.ask("What did Rila Sen craft?").status
    if inverse_synonym_status == "answered":
        raise SystemExit("unsupported inverse synonym was answered")
    inverse_role_swap_status = inverse.ask(
        "What did Tavor Engine make?").status
    if inverse_role_swap_status == "answered":
        raise SystemExit("inverse transfer answered a subject/object role swap")
    return {
        "status": "passed",
        "surface_form": "made",
        "canonical_relation": "created",
        "licensing_sources": sorted((first_source, second_source)),
        "answer": result.answer,
        "answer_source": examples[2][2],
        "unsupported_synonym_status": kb.ask(
            "Who crafted Tavor Engine?").status,
        "inverse_question": inverse_question,
        "inverse_answer": inverse_result.answer,
        "inverse_answer_source": examples[2][2],
        "inverse_transfer_trace": inverse_trace,
        "one_example_inverse_status": one_example_inverse_status,
        "unlicensed_inverse_synonym_status": inverse_synonym_status,
        "inverse_role_swap_status": inverse_role_swap_status,
    }


def grounded_chat_do_support_transfer_check() -> dict[str, object]:
    """Exercise predicate learning and inverse transfer through the real CLI."""
    examples = (
        ("mara", "Mara Vell", "Orrin Engine", "Mara Vell made Orrin Engine."),
        ("nema", "Nema Tor", "Vesk Engine", "Nema Tor made Vesk Engine."),
        ("rila", "Rila Sen", "Tavor Engine", "Rila Sen made Tavor Engine."),
    )
    with tempfile.TemporaryDirectory(prefix="crms-transfer-chat-") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        for document_id, _subject, _obj, sentence in examples:
            index.add_document(document_id, document_id, sentence,
                               f"research/{document_id}.txt")
        index_path = root / "index.json"
        index.save(index_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
        ]
        interactions = [
            f"/teach-fact {subject}|created|{obj}|{sentence}|made|positive"
            for _document_id, subject, obj, sentence in examples
        ]
        interactions.extend(("Who made Tavor Engine?",
                             "What did Rila Sen make?", "/quit"))
        completed = subprocess.run(
            command, input="\n".join(interactions) + "\n", text=True,
            capture_output=True, check=False, cwd=root, timeout=20)
        if completed.returncode != 0:
            raise SystemExit(
                f"CRMS chat process failed ({completed.returncode}):\n"
                f"{completed.stderr}\n{completed.stdout}")
        expected = "CRMS> Rila Sen made Tavor Engine. [Source: rila; accepted fact]"
        if completed.stdout.count(expected) < 2:
            raise SystemExit(
                "CLI did not answer with the held-out realized sentence and source:\n"
                f"{completed.stdout}")
    return {"status": "passed", "answer": "Rila Sen made Tavor Engine.",
            "answer_source": "rila"}


def grounded_chat_passive_voice_transfer_check() -> dict[str, object]:
    """Drive passive-pattern learning and active/passive questions through CLI."""
    examples = (
        ("mara", "Mara Vell", "Orrin Engine", "Orrin Engine was made by Mara Vell."),
        ("nema", "Nema Tor", "Vesk Engine", "Vesk Engine was made by Nema Tor."),
        ("rila", "Rila Sen", "Tavor Engine", "Tavor Engine was made by Rila Sen."),
    )
    with tempfile.TemporaryDirectory(prefix="crms-passive-chat-") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        for document_id, _subject, _obj, sentence in examples:
            index.add_document(document_id, document_id, sentence,
                               f"research/{document_id}.txt")
        index_path = root / "index.json"
        index.save(index_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
        ]
        interactions = [
            f"/teach-fact {subject}|created|{obj}|{sentence}|made|positive"
            for _document_id, subject, obj, sentence in examples
        ]
        interactions.extend((
            "Who made Tavor Engine?",
            "What did Rila Sen make?",
            "Who was Tavor Engine made by?",
            "What was made by Rila Sen?",
            "/quit",
        ))
        completed = subprocess.run(
            command, input="\n".join(interactions) + "\n", text=True,
            capture_output=True, check=False, cwd=root, timeout=20)
        if completed.returncode != 0:
            raise SystemExit(
                f"passive CRMS chat process failed ({completed.returncode}):\n"
                f"{completed.stderr}\n{completed.stdout}")
        expected = (
            "CRMS> Tavor Engine was made by Rila Sen. "
            "[Source: rila; accepted fact]")
        if completed.stdout.count(expected) != 4:
            raise SystemExit(
                "passive CLI did not answer all active/passive questions from the "
                f"held-out fact:\n{completed.stdout}")
    return {"status": "passed", "questions": 4,
            "answer": "Tavor Engine was made by Rila Sen.",
            "answer_source": "rila"}


def main() -> int:
    first = run_benchmark()
    second = run_benchmark()
    if first != second:
        raise SystemExit("cross-surface transfer benchmark is not deterministic")
    if any(item["k"] > 0
           and item["classes"]["T"]["correct"] != item["classes"]["T"]["n"]
           for item in first["summaries"]):
        raise SystemExit("trained wording failed entity-slot generalization")
    if any(item["near_miss_wrong"] for item in first["summaries"]):
        raise SystemExit("a near-miss question produced an unsupported answer")
    if any(row["n"] and row["correct"] != row["n"]
           for row in first["rows"] if row["class"] == "G"):
        raise SystemExit(
            "an explicitly taught fact-backed frame failed to transfer to held-out entities")
    if first["grounded_rule_transfer"]["status"] != "passed":
        raise SystemExit("grounded nominal-to-verb transfer failed")
    if first["grounded_perfect_aspect_transfer"]["status"] != "passed":
        raise SystemExit("grounded regular perfect-aspect transfer failed")
    if first["fact_pattern_to_question_transfer"]["status"] != "passed":
        raise SystemExit("fact-pattern question-frame induction failed")
    if first["grounded_predicate_transfer"]["status"] != "passed":
        raise SystemExit("source-backed predicate transfer failed")
    if first["grounded_chat_do_support_transfer"]["status"] != "passed":
        raise SystemExit("grounded chat do-support transfer failed")
    if first["grounded_chat_passive_voice_transfer"]["status"] != "passed":
        raise SystemExit("grounded chat passive voice transfer failed")

    print("Cross-surface question transfer (invented entities; held-out entities)")
    print("relation | k | class | n | correct | wrong | abstained | frame | derived | direct")
    for row in first["rows"]:
        print(f"{row['relation']} | {row['k']} | {row['class']} | {row['n']} | "
              f"{row['correct']} | {row['wrong']} | {row['abstained']} | "
              f"{row['licensed_transfer']} | {row['derived_transfer']} | "
              f"{row['direct_or_builtin']}")
    print("\nCoverage summary")
    for item in first["summaries"]:
        canonical = item["canonical_class"]
        print(f"k={item['k']}: canonical {canonical}="
              f"{item['classes'][canonical]['correct']}/"
              f"{item['classes'][canonical]['n']}; additional taught G="
              f"{item['classes']['G']['correct']}/{item['classes']['G']['n']}; "
              f"untaught S/P/L verified transfer="
              f"{item['heldout_transfer_correct']}/{item['heldout_transfer_n']} "
              f"(ratio={item['heldout_transfer_ratio']:.3f}; "
              f"all correct={item['heldout_answer_correct']}; "
              f"direct/built-in={item['direct_or_builtin_on_transfer_set']}); "
              f"near-miss wrong={item['near_miss_wrong']}")
    transfer = first["grounded_rule_transfer"]
    print("grounded morphology transfer: "
          f"{transfer['licensed_frame']} -> {transfer['derived_frame']}; "
          f"support={len(transfer['licensing_sources'])} sources; "
          f"unlicensed synonym={transfer['unlicensed_synonym_status']}")
    aspect = first["grounded_perfect_aspect_transfer"]
    print("regular perfect-aspect transfer: "
          f"{aspect['question']} -> {aspect['answer']}; "
          f"held-out source={aspect['answer_source']}")
    derived_questions = first["fact_pattern_to_question_transfer"]
    print("declarative-to-question induction: "
          f"{derived_questions['subject_question']} -> "
          f"{derived_questions['subject_answer']}; "
          f"{derived_questions['object_question']} -> "
          f"{derived_questions['object_answer']}; one-example="
          f"{derived_questions['one_example_status']}; licensing sources="
          f"{len(derived_questions['licensing_sources'])}")
    print("active-to-passive question transfer: "
          f"{derived_questions['active_to_passive_subject_question']} -> "
          f"{derived_questions['active_to_passive_subject_answer']}; "
          f"{derived_questions['active_to_passive_object_question']} -> "
          f"{derived_questions['active_to_passive_object_answer']}")
    print("passive-to-question induction: "
          f"{derived_questions['passive_subject_question']} -> "
          f"{derived_questions['passive_subject_answer']}; "
          f"{derived_questions['passive_object_question']} -> "
          f"{derived_questions['passive_object_answer']}")
    print("passive-to-active question transfer: "
          f"{derived_questions['passive_to_active_subject_question']} -> "
          f"{derived_questions['passive_to_active_subject_answer']}; "
          f"{derived_questions['passive_to_active_object_question']} -> "
          f"{derived_questions['passive_to_active_object_answer']}")
    print("irregular participle transfer: "
          f"{derived_questions['irregular_passive_question']} -> "
          f"{derived_questions['irregular_passive_answer']}")
    predicate = first["grounded_predicate_transfer"]
    print("source-backed predicate transfer: "
          f"{predicate['surface_form']} -> {predicate['canonical_relation']}; "
          f"support={len(predicate['licensing_sources'])} examples; "
          f"held-out source={predicate['answer_source']}; "
          f"unlicensed synonym={predicate['unsupported_synonym_status']}")
    print("irregular do-support transfer: "
          f"{predicate['inverse_question']} -> {predicate['inverse_answer']}; "
          f"held-out source={predicate['inverse_answer_source']}; "
          f"one-example={predicate['one_example_inverse_status']}; "
          f"unlicensed synonym={predicate['unlicensed_inverse_synonym_status']}; "
          f"role swap={predicate['inverse_role_swap_status']}")
    chat_transfer = first["grounded_chat_do_support_transfer"]
    print("CLI question-frame-free interaction: "
          f"{chat_transfer['answer']} [Source: {chat_transfer['answer_source']}]")
    passive_chat = first["grounded_chat_passive_voice_transfer"]
    print("CLI passive-pattern active/passive questions: "
          f"{passive_chat['questions']} answered from the held-out source")
    print("deterministic repeat: PASS; answer/source checks: PASS; near-miss safety: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
