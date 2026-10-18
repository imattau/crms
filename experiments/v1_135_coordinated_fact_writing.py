"""Coordinate grounded same-frame facts in an about-entity digest.

Run from the project root with:
    python3 experiments/v1_135_coordinated_fact_writing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    knowledge = CRMSKnowledgeBase()
    examples = (
        ("Ada Lovelace", "the Analytical Engine", "source:ada-engine"),
        ("Grace Hopper", "the Compiler", "source:grace-compiler"),
        ("Ada Lovelace", "the Compiler", "source:ada-compiler"),
        ("Ada Lovelace", "the Difference Engine", "source:ada-difference"),
    )
    for subject, obj, source in examples:
        sentence = f"{subject} designed {obj}."
        knowledge.add_fact(subject, "designed", obj, source)
        knowledge.teach_fact_pattern(
            sentence, subject=subject, relation="designed", obj=obj,
            source=source, predicate_phrase="designed")

    digest = knowledge.write_about("Ada Lovelace")
    combined = (
        "Ada Lovelace designed the Analytical Engine, the Compiler, and "
        "the Difference Engine.")
    if (digest.status != "written" or len(digest.statements) != 3
            or combined not in digest.text
            or "Ada Lovelace designed the Compiler. [" in digest.text
            or "Ada Lovelace designed the Analytical Engine. [" in digest.text):
        raise SystemExit(f"same-frame writing did not coordinate claims: {digest}")
    for source in ("source:ada-engine", "source:ada-compiler",
                   "source:ada-difference",
                   "source:grace-compiler"):
        if source not in digest.text:
            raise SystemExit(f"coordinated writing lost provenance {source}")
    if any("_line_index" in statement for statement in digest.statements):
        raise SystemExit("internal line bookkeeping leaked into the writing result")

    knowledge.teach_about_frame("Tell me about Ada Lovelace", entity="Ada Lovelace")
    knowledge.teach_about_frame("Tell me about Grace Hopper", entity="Grace Hopper")
    dialogue = CRMSDialogue(knowledge)
    written = dialogue.turn("Tell me about Ada Lovelace")
    why = dialogue.turn("Why?")
    if (written.writing is None or combined not in written.text
            or why.writing is None or combined not in why.text
            or "source:ada-engine" not in why.text
            or "source:ada-compiler" not in why.text):
        raise SystemExit("dialogue or explanation did not preserve coordinated writing")

    expanded = CRMSKnowledgeBase()
    expanded_examples = (
        ("Ada", "Engine", "source:ada-engine"),
        ("Grace", "Compiler", "source:grace-compiler"),
        ("Ada", "Difference Engine", "source:ada-difference"),
        ("Ada", "Analytical Engine", "source:ada-analytical"),
        ("Ada", "Calculator", "source:ada-calculator"),
    )
    for subject, obj, source in expanded_examples:
        sentence = f"{subject} designed the {obj}."
        expanded.add_fact(subject, "designed", f"the {obj}", source)
        expanded.teach_fact_pattern(
            sentence, subject=subject, relation="designed", obj=f"the {obj}",
            source=source, predicate_phrase="designed")
    expanded_digest = expanded.write_about("Ada")
    expanded_sentence = (
        "Ada designed the Analytical Engine, the Calculator, the Difference "
        "Engine, and the Engine.")
    if (len(expanded_digest.statements) != 4
            or expanded_sentence not in expanded_digest.text
            or any(source not in expanded_digest.text
                   for _subject, _obj, source in expanded_examples
                   if _subject == "Ada")):
        raise SystemExit(
            f"writer failed to coordinate four supported claims: {expanded_digest}")
    for index in range(5):
        obj = f"Device {index}"
        source = f"source:ada-device-{index}"
        expanded.add_fact("Ada", "designed", obj, source)
    over_limit = expanded.write_about("Ada")
    if (len(over_limit.statements) != 9
            or "Ada designed the Analytical Engine, the Calculator" in over_limit.text
            or any(f"source:ada-device-{index}" not in over_limit.text
                   for index in range(5))):
        raise SystemExit("writer coordinated an over-limit group or lost its claims")

    # Sharing a subject can coordinate distinct learned predicates when the
    # surface skeleton and exact context match.
    separate = CRMSKnowledgeBase()
    for subject, relation, obj, source in (
            ("Ada", "designed", "Engine", "s1"),
            ("Grace", "designed", "Compiler", "s2"),
            ("Ada", "built", "Table", "s3"),
        ("James", "built", "Tower", "s4"),
        ("Ada", "tested", "Prototype", "s5"),
        ("Eve", "tested", "Sample", "s6")):
        sentence = f"{subject} {relation} the {obj}."
        separate.add_fact(subject, relation, f"the {obj}", source)
        separate.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=f"the {obj}",
            source=source, predicate_phrase=relation)
    cross_relation = separate.write_about("Ada")
    coordinated_predicates = (
        "Ada built the Table, designed the Engine, and tested the Prototype.")
    if (coordinated_predicates not in cross_relation.text
            or len(cross_relation.statements) != 3
            or any("_line_index" in statement
                   for statement in cross_relation.statements)):
        raise SystemExit(
            f"writer failed to coordinate distinct predicates: {cross_relation}")
    for source in ("s1", "s3", "s2", "s4", "s5", "s6"):
        if source not in cross_relation.text:
            raise SystemExit(
                f"cross-predicate writing lost fact/frame source {source}")
    separate.teach_about_frame("Tell me about Ada", entity="Ada")
    separate.teach_about_frame("Tell me about Grace", entity="Grace")
    cross_dialogue = CRMSDialogue(separate)
    cross_written = cross_dialogue.turn("Tell me about Ada")
    cross_why = cross_dialogue.turn("Why?")
    if (coordinated_predicates not in cross_written.text
            or coordinated_predicates not in cross_why.text
            or "s1" not in cross_why.text or "s3" not in cross_why.text):
        raise SystemExit("dialogue explanation dropped shared-subject composition")

    # The same subject and shared frame do not permit coordination across
    # distinct qualifier scopes.
    scoped = CRMSKnowledgeBase()
    scoped.add_fact("Ada", "designed", "the Engine", "sd1",
                    qualifiers={"year": "2024"})
    scoped.add_fact("Ada", "built", "the Table", "sb1",
                    qualifiers={"year": "2025"})
    for subject, relation, obj, source in (
            ("Grace", "designed", "the Compiler", "sd2"),
            ("Eve", "designed", "the Device", "sd3"),
            ("James", "built", "the Tower", "sb2"),
            ("Kai", "built", "the Bridge", "sb3")):
        sentence = f"{subject} {relation} the {obj}."
        scoped.add_fact(subject, relation, obj, source)
        scoped.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj,
            source=source, predicate_phrase=relation)
    different_scope = scoped.write_about("Ada")
    if "Ada designed the Engine and built the Table." in different_scope.text:
        raise SystemExit("writer combined claims across qualifier scopes")

    print("coordinated fact-writing diagnostic: PASS")
    print("same-relation and shared-subject composition, scope separation, provenance, dialogue explanation: PASS")


if __name__ == "__main__":
    main()
