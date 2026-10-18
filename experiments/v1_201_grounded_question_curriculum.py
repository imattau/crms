"""Generate fact-grounded questions from licensed frames and audit ask().

This is a read-only curriculum diagnostic: generated queries never become
training examples, facts, or persistent memory.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def generated_queries(kb: CRMSKnowledgeBase) -> list[dict[str, object]]:
    """Instantiate licensed one-slot frames over unqualified stored facts."""
    queries: dict[str, dict[str, object]] = {}
    for (relation_json, answer_field, prefix, suffix), examples in sorted(
            kb._question_examples.items()):
        if not kb._question_frame_is_licensed(
                (relation_json, answer_field, prefix, suffix), examples):
            continue
        relation = tuple(json.loads(relation_json))
        bound_field = "object" if answer_field == "subject" else "subject"
        for fact in kb.facts():
            if (tuple(fact.relation.casefold().split()) != relation
                    or fact.qualifiers):
                continue
            bound = fact.object if bound_field == "object" else fact.subject
            words = prefix + tuple(bound.casefold().split()) + suffix
            question = " ".join(words)
            query = queries.setdefault(question, {
                "question": question,
                "answers": set(),
                "sources": set(),
                "frame": " ".join(prefix + ("{" + bound_field + "}",) + suffix),
                "relation": " ".join(relation),
            })
            answer = fact.subject if answer_field == "subject" else fact.object
            query["answers"].add(answer)
            query["sources"].update(fact.sources)

    result = []
    for query in queries.values():
        answers = sorted(query["answers"], key=str.casefold)
        query["expected_status"] = "unknown" if not answers else (
            "answered" if len(answers) == 1 else "ambiguous")
        query["answers"] = answers
        query["sources"] = sorted(query["sources"])
        result.append(query)
    return sorted(result, key=lambda item: str(item["question"]).casefold())


def generated_qualified_queries(
        kb: CRMSKnowledgeBase) -> list[dict[str, object]]:
    """Instantiate licensed single-qualifier frames over matching facts."""
    queries: dict[str, dict[str, object]] = {}
    for (relation, answer_field, qualifier_name, entity_first,
         prefix, middle, suffix), examples in sorted(
             kb._qualified_question_examples.items()):
        entities = {entity for entity, _value in examples}
        values = {value for _entity, value in examples}
        if len(examples) < 2 or len(entities) < 2 or len(values) < 2:
            continue
        bound_field = "object" if answer_field == "subject" else "subject"
        for fact in kb.facts():
            if tuple(fact.relation.casefold().split()) != relation:
                continue
            context = {tuple(name.casefold().split()): value
                       for name, value in fact.qualifiers}
            if set(context) != {qualifier_name}:
                continue
            qualifier_value = tuple(context[qualifier_name].casefold().split())
            bound = fact.object if bound_field == "object" else fact.subject
            entity_tokens = tuple(bound.casefold().split())
            words = (prefix + entity_tokens + middle + qualifier_value + suffix
                     if entity_first else
                     prefix + qualifier_value + middle + entity_tokens + suffix)
            question = " ".join(words)
            query = queries.setdefault(question, {
                "question": question,
                "answers": set(),
                "sources": set(),
                "frame": "qualified:" + " ".join(relation),
                "relation": " ".join(relation),
                "qualifiers": {" ".join(qualifier_name):
                               " ".join(qualifier_value)},
            })
            answer = fact.subject if answer_field == "subject" else fact.object
            query["answers"].add(answer)
            query["sources"].update(fact.sources)

    result = []
    for query in queries.values():
        answers = sorted(query["answers"], key=str.casefold)
        query["expected_status"] = "answered" if len(answers) == 1 else "ambiguous"
        query["answers"] = answers
        query["sources"] = sorted(query["sources"])
        result.append(query)
    return sorted(result, key=lambda item: str(item["question"]).casefold())


def generated_multi_qualified_queries(
        kb: CRMSKnowledgeBase) -> list[dict[str, object]]:
    """Instantiate licensed multi-slot frames at their exact qualifier scope."""
    queries: dict[str, dict[str, object]] = {}
    for (relation, answer_field, qualifier_names, pattern), examples in sorted(
            kb._multi_qualified_question_examples.items()):
        entity_values = {entity for entity, _values in examples}
        varying = [{values[index] for _entity, values in examples}
                   for index in range(len(qualifier_names))]
        if (len(examples) < 2 or len(entity_values) < 2
                or any(len(values) < 2 for values in varying)):
            continue
        relation_values = tuple(relation)
        for fact in kb.facts():
            if tuple(fact.relation.casefold().split()) != relation_values:
                continue
            context = {tuple(name.casefold().split()):
                       tuple(value.casefold().split())
                       for name, value in fact.qualifiers}
            if set(context) != set(qualifier_names):
                continue
            bound_field = "object" if answer_field == "subject" else "subject"
            bound = fact.object if bound_field == "object" else fact.subject
            bindings = {"\x00entity": tuple(bound.casefold().split())}
            bindings.update({f"\x00q{index}": context[name]
                             for index, name in enumerate(qualifier_names)})
            # Expand each slot marker in-place; ordinary tokens remain literal.
            expanded = []
            for token in pattern:
                expanded.extend(bindings[token] if token in bindings else (token,))
            question = " ".join(expanded)
            query = queries.setdefault(question, {
                "question": question,
                "answers": set(),
                "sources": set(),
                "frame": "multi-qualified:" + " ".join(relation_values),
                "relation": " ".join(relation_values),
                "qualifiers": {" ".join(name): " ".join(context[name])
                               for name in qualifier_names},
            })
            answer = fact.subject if answer_field == "subject" else fact.object
            query["answers"].add(answer)
            query["sources"].update(fact.sources)

    result = []
    for query in queries.values():
        answers = sorted(query["answers"], key=str.casefold)
        query["expected_status"] = "answered" if len(answers) == 1 else "ambiguous"
        query["answers"] = answers
        query["sources"] = sorted(query["sources"])
        result.append(query)
    return sorted(result, key=lambda item: str(item["question"]).casefold())


def main() -> None:
    kb = CRMSKnowledgeBase()
    rows = [
        ("Ada", "designed", "Engine", "doc-a"),
        ("Bea", "designed", "Compiler", "doc-b"),
        ("Cal", "designed", "Device", "doc-c"),
        ("Dee", "designed", "Device", "doc-d"),
        ("Eli", "reviewed", "Engine", "doc-e"),
        ("Fay", "reviewed", "Report", "doc-f"),
        ("Gus", "reviewed", "Report", "doc-g"),
    ]
    for subject, relation, obj, source in rows:
        kb.add_fact(subject, relation, obj, source)

    for relation, examples in (
            ("designed", (("Who designed Engine?", "Engine", "Ada"),
                          ("Who designed Compiler?", "Compiler", "Bea"))),
            ("reviewed", (("What did Eli review?", "Eli", "Engine"),
                          ("What did Fay review?", "Fay", "Report")))):
        # The natural-language frames bind the object when asking for subject,
        # or bind the subject when asking for object.
        for question, bound, answer in examples:
            answer_field = "subject" if question.startswith("Who") else "object"
            kb.teach_question(question, relation=relation,
                              answer_field=answer_field,
                              bound_entity=bound, answer=answer)

    before_facts = [(fact.subject, fact.relation, fact.object, fact.sources,
                     fact.qualifiers) for fact in kb.facts()]
    before_frames = len(kb._question_examples)
    tasks = generated_queries(kb)
    if not tasks:
        raise SystemExit("no licensed frame generated a grounded question")

    for task in tasks:
        result = kb.ask(str(task["question"]))
        expected = task["answers"]
        actual = ([result.answer] if result.status == "answered" else
                  sorted(result.candidates, key=str.casefold)
                  if result.status == "ambiguous" else [])
        if result.status != task["expected_status"] or actual != expected:
            raise SystemExit(f"generated question mismatch: {task}; got {result}")
        actual_sources = sorted({source for item in result.evidence
                                 for source in item.get("sources", [])})
        if actual_sources != task["sources"]:
            raise SystemExit(f"evidence mismatch for {task['question']}: "
                             f"{actual_sources} != {task['sources']}")

    qualified = CRMSKnowledgeBase()
    scoped_rows = [
        ("Ada", "designed", "Engine", "2024", "q-a"),
        ("Bea", "designed", "Compiler", "2025", "q-b"),
        ("Cal", "designed", "Device", "2024", "q-c"),
        ("Dee", "designed", "Machine", "2025", "q-d"),
        ("Eve", "designed", "Device", "2024", "q-e"),
    ]
    for subject, relation, obj, year, source in scoped_rows:
        qualified.add_fact(subject, relation, obj, source,
                           qualifiers={"year": year})
    for subject, _relation, obj, year, _source in scoped_rows[:2]:
        qualified.teach_qualified_question(
            f"Who designed {obj} in {year}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject,
            qualifier={"year": year})
    before_scoped_facts = [(fact.subject, fact.relation, fact.object,
                            fact.sources, fact.qualifiers)
                           for fact in qualified.facts()]
    qualified_tasks = generated_qualified_queries(qualified)
    if not qualified_tasks:
        raise SystemExit("licensed qualified frame generated no questions")
    for task in qualified_tasks:
        result = qualified.ask(str(task["question"]))
        actual = ([result.answer] if result.status == "answered" else
                  sorted(result.candidates, key=str.casefold)
                  if result.status == "ambiguous" else [])
        if result.status != task["expected_status"] or actual != task["answers"]:
            raise SystemExit(f"qualified question mismatch: {task}; got {result}")
        actual_sources = sorted({source for item in result.evidence
                                 for source in item.get("sources", [])})
        if actual_sources != task["sources"]:
            raise SystemExit(f"qualified evidence mismatch for {task['question']}: "
                             f"{actual_sources} != {task['sources']}")
    if qualified.ask("Who designed Device in 2025?").status != "unknown":
        raise SystemExit("qualified question ignored its exact scope")
    if before_scoped_facts != [(fact.subject, fact.relation, fact.object,
                                fact.sources, fact.qualifiers)
                               for fact in qualified.facts()]:
        raise SystemExit("qualified question generation mutated the fact store")

    # The frame is tied to direct fact evidence so expected answer labels are
    # mechanically recoverable without inference search.
    direct_multi = CRMSKnowledgeBase()
    direct_rows = [
        ("Ada", "managed", "Project A", "2024", "Europe", "d-a"),
        ("Bea", "managed", "Project B", "2025", "Asia", "d-b"),
        ("Cal", "managed", "Project C", "2024", "Asia", "d-c"),
        ("Dee", "managed", "Project D", "2025", "Europe", "d-d"),
        ("Eve", "managed", "Project D", "2025", "Europe", "d-e"),
    ]
    for person, relation, project, year, region, source in direct_rows:
        direct_multi.add_fact(person, relation, project, source,
                              qualifiers={"year": year, "region": region})
    for person, _relation, project, year, region, _source in direct_rows[:3]:
        direct_multi.teach_qualified_question(
            f"Who managed {project} in {year} across {region}?",
            relation="managed", answer_field="subject", bound_entity=project,
            answer=person, qualifier={"year": year, "region": region})
    before_multi_facts = [(fact.subject, fact.relation, fact.object,
                           fact.sources, fact.qualifiers)
                          for fact in direct_multi.facts()]
    multi_tasks = generated_multi_qualified_queries(direct_multi)
    if not multi_tasks:
        raise SystemExit("licensed multi-qualifier frame generated no questions")
    for task in multi_tasks:
        result = direct_multi.ask(str(task["question"]))
        actual = ([result.answer] if result.status == "answered" else
                  sorted(result.candidates, key=str.casefold)
                  if result.status == "ambiguous" else [])
        if result.status != task["expected_status"] or actual != task["answers"]:
            raise SystemExit(f"multi-qualified question mismatch: {task}; got {result}")
        actual_sources = sorted({source for item in result.evidence
                                 for source in item.get("sources", [])})
        if actual_sources != task["sources"]:
            raise SystemExit(f"multi-qualified evidence mismatch for "
                             f"{task['question']}: {actual_sources} != {task['sources']}")
    if direct_multi.ask(
            "Who managed Project D in 2025 across Europe?",
            qualifiers={"region": "Asia"}).status != "unknown":
        raise SystemExit("explicit conflict overrode a multi-slot frame value")
    if before_multi_facts != [(fact.subject, fact.relation, fact.object,
                               fact.sources, fact.qualifiers)
                              for fact in direct_multi.facts()]:
        raise SystemExit("multi-qualified question generation mutated facts")

    # Open-world guard: a licensed frame plus an unrecorded entity is unknown,
    # never a mechanically generated negative label.
    unknown = kb.ask("Who designed Unrecorded Widget?")
    if unknown.status != "unknown":
        raise SystemExit(f"missing fact was treated as a label: {unknown}")
    if before_facts != [(fact.subject, fact.relation, fact.object, fact.sources,
                         fact.qualifiers) for fact in kb.facts()]:
        raise SystemExit("question generation mutated the fact store")
    if before_frames != len(kb._question_examples):
        raise SystemExit("question generation mutated learned frames")

    print(f"grounded question curriculum: {len(tasks)} ordinary + "
          f"{len(qualified_tasks)} single-qualifier + "
          f"{len(multi_tasks)} multi-qualifier tasks; PASS")
    print("answers, ambiguity, source evidence, exact scope, open-world "
          "abstention, and read-only behavior: PASS")


if __name__ == "__main__":
    main()
