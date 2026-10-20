"""Measure learned procedure recombination through proof-filter chat.

The target sequence is composed from primitives and other sequence examples,
not taught directly. Request frames and an explicit ``and then`` connective
vary; unsupported paraphrases and incomplete/conflicting facts remain controls.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_451_reasoned_procedure_composition import add_chain, discover_and_accept
from v1_491_one_turn_reasoning_filter_recombination import build_case
from crms_math import CRMSMath
from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def learn_connective_procedures() -> CRMSModel:
    """Learn primitives and `then` separately from the held-out sequence."""
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    input_lists = ([3, 1, 2], [4, -1, 7], [0, 5, -2, 8], [-5, 9], [12], [])
    contrast = [0, 0]

    def apply(values: list[int], operation: str) -> list[int]:
        if operation == "sort":
            return sorted(values)
        if operation == "reverse":
            return list(reversed(values))
        if operation == "unique":
            return list(dict.fromkeys(values))
        raise ValueError(f"unknown operation in fixture: {operation}")

    base_phrases = (
        ("sort the list", "sort"),
        ("reverse the list", "reverse"),
        ("sort the values", "sort"),
        ("reverse the values", "reverse"),
        ("remove duplicate values", "unique"),
    )
    for phrase, operation in base_phrases:
        examples = [(list(values), apply(list(values), operation))
                    for values in (*input_lists, contrast)]
        taught = model.teach(
            phrase, examples,
            source_ids=[f"fixture:primitive:{phrase}"] * len(examples),
            labeler_ids=["codex:sequence-component-teacher"] * len(examples),
            instruction_source_ids=[f"fixture:phrase:{phrase}"] * len(examples))
        require(taught.status == "learned",
                f"base procedure was not uniquely learned: {phrase}: {taught}")

    # Neither connective example is the target pair used by the composition
    # task: sequence evidence must transfer from both observed orderings.
    for phrase, first, second in (
            ("sort the list then reverse the values", "sort", "reverse"),
            ("reverse the list then sort the values", "reverse", "sort")):
        def combined(values: list[int]) -> list[int]:
            return apply(apply(list(values), first), second)

        examples = [(list(values), combined(list(values)))
                    for values in input_lists]
        initial = model.teach(
            phrase, examples,
            source_ids=[f"fixture:sequence:{phrase}"] * len(examples),
            labeler_ids=["codex:sequence-connective-teacher"] * len(examples),
            instruction_source_ids=["fixture:sequence-connective:then"]
            * len(examples))
        require(initial.status == "need_more_examples"
                and initial.contrastive_input == contrast,
                f"expected a contrastive connective example: {phrase}: {initial}")
        resolved = model.teach(
            phrase, [(contrast, combined(contrast))],
            source_ids=[f"fixture:contrast:{phrase}"],
            labeler_ids=["codex:sequence-connective-teacher"],
            instruction_source_ids=["fixture:sequence-connective:then"])
        require(resolved.status == "learned",
                f"connective example did not resolve: {phrase}: {resolved}")

    return model


def teach_relation_surface(knowledge: CRMSKnowledgeBase,
                           research_index: CRMSResearchIndex) -> list[str]:
    """Teach a source-grounded predicate form without hard-coding its alias."""
    citations = []
    for document_id, subject, obj in (
            ("surface-ada", "Ada", "21"),
            ("surface-bea", "Bea", "34"),
            ("surface-cy", "Cy", "55")):
        sentence = f"{subject} can reach {obj}."
        research_index.add_document(
            document_id, "Reviewed reach wording", sentence,
            f"{document_id}.txt")
        hit = next(item for item in research_index.search(sentence, limit=10)
                   if item.document_id == document_id)
        citation = research_index.citation(hit)
        knowledge.add_fact_from_hit(
            subject, "reaches", obj, research_index, hit)
        licensed = knowledge.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="reaches", obj=obj,
            predicate_phrase="can reach", research_index=research_index,
            hit=hit)
        citations.append(citation)
    require(licensed,
            "varied cited predicate examples did not license the surface form")
    return citations


def check_relation_surface_source_independence() -> None:
    index = CRMSResearchIndex()
    index.add_document(
        "single-source", "Single source", "Dee can reach 8. Eli can reach 9.",
        "single-source.txt")
    knowledge = CRMSKnowledgeBase()
    licensed = False
    for subject, obj, sentence in (
            ("Dee", "8", "Dee can reach 8."),
            ("Eli", "9", "Eli can reach 9.")):
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == "single-source")
        knowledge.add_fact_from_hit(subject, "reaches", obj, index, hit)
        licensed = knowledge.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="reaches", obj=obj,
            predicate_phrase="can reach", research_index=index, hit=hit)
    require(licensed
            and knowledge.match_fact_pattern_relation_claim("Nia can reach")
                is None,
            "one source document licensed a reusable relation wording")


def main() -> None:
    knowledge, _direct_composite_control = build_case()
    procedures = learn_connective_procedures()
    alias_index = CRMSResearchIndex()
    alias_sources = teach_relation_surface(knowledge, alias_index)
    check_relation_surface_source_independence()
    cases = (
        ("Filter 12, 4, 4, 9, and 7 to values Nia reaches; then remove duplicate "
         "values then reverse the list.", (9, 4, 12)),
        ("Given 9, 12, 4, 4, and 7, keep the values Nia reaches, and then remove "
         "duplicate values then reverse the list.", (4, 12, 9)),
        ("From [4, 12, 9, 4, 7], return the values Nia reaches, then remove "
         "duplicate values then reverse the list.", (9, 12, 4)),
        ("From [12, 9, 4, 12, 7], return the values Nia reaches, then remove "
         "duplicate values and then reverse the list.", (4, 9, 12)),
        # This input distinguishes operation order: reversing first yields
        # [9, 12, 4, 12], then first-occurrence deduplication yields
        # [9, 12, 4]. Deduplicating first would instead yield [9, 4, 12].
        ("Filter 12, 4, 12, 9, and 7 to values Nia reaches; then reverse the "
         "list then remove duplicate values.", (9, 12, 4)),
        ("Filter 12, 4, 4, 9, and 7 to values Nia can reach; then remove "
         "duplicate values then reverse the list.", (9, 4, 12)),
    )
    for request, expected in cases:
        result = compose_verified_filter(request, knowledge, procedures)
        require(result is not None and result.status == "answered"
                and result.output_values == expected
                and result.excluded_negative == (7,)
                and len(result.inference_proofs) == 3
                and result.procedure_records
                and {record.get("phrase") for record in result.procedure_records}
                    >= {"remove duplicate values", "reverse the list",
                        "sort the list then reverse the values",
                        "reverse the list then sort the values"}
                and "remove duplicate values then reverse the list"
                    not in {record.get("phrase")
                            for record in result.procedure_records},
                f"ordinary request frame did not preserve verified composition: "
                f"{request!r}: {result}")
        if "can reach" in request:
            require(result.subject == "Nia"
                    and len(result.language_evidence) == 1
                    and result.language_evidence[0]["document_count"] >= 2
                    and result.language_evidence[0]["surface_phrase"] == "can reach"
                    and result.language_evidence[0]["relation"] == "reaches"
                    and set(result.language_evidence[0]["sources"]) == set(alias_sources)
                    and all(alias_index.resolve_citation(source)
                            for source in alias_sources)
                    and "Taught relation wording: 'can reach' → 'reaches'"
                        in result.text,
                    f"learned relation wording lost its evidence: {result}")

    # The parser may normalize an explicit connective, but it must not invent
    # operation synonyms or broaden relation vocabulary without supervision.
    unlicensed_operation = compose_verified_filter(
        "From [12, 4, 4, 9, 7], return the values Nia reaches, then deduplicate "
        "and reverse the result.", knowledge, procedures)
    require(unlicensed_operation is not None
            and unlicensed_operation.status == "unsupported_procedure"
            and not unlicensed_operation.output_values,
            f"unlicensed operation paraphrase was executed: {unlicensed_operation}")
    unlicensed_relation = compose_verified_filter(
        "From [12, 4, 4, 9, 7], return the values Nia can get to, then remove "
        "duplicate values then reverse the list.", knowledge, procedures)
    require(unlicensed_relation is not None
            and unlicensed_relation.status == "unsupported"
            and not unlicensed_relation.output_values,
            f"unlicensed relation paraphrase was executed: {unlicensed_relation}")

    unknown = compose_verified_filter(
        "From [12, 4, 8], return the values Nia reaches, then remove duplicate "
        "values then reverse the list.", knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (8,) and not unknown.output_values,
            f"unresolved membership was dropped before recombination: {unknown}")

    conflicted = CRMSKnowledgeBase()
    discover_and_accept(conflicted)
    add_chain(conflicted, "Nia", "Sol", "Tern", "7", "runtime:record-7",
              conclusion="positive")
    conflicted.add_negative_fact(
        "Nia", "reaches", "7", "runtime:record-7-negative")
    conflict = compose_verified_filter(
        "From [7], return the values Nia reaches, then remove duplicate values "
        "then reverse the list.", conflicted, procedures)
    require(conflict is not None and conflict.status == "conflict"
            and not conflict.output_values,
            f"conflicting membership was recombined: {conflict}")

    with tempfile.TemporaryDirectory(prefix="crms-compose-language-") as folder:
        root = Path(folder)
        knowledge.save(root / "knowledge.json")
        procedures.save(root / "rules.json")
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        alias_index.save(root / "index.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command,
            input="\n".join((
                *(request for request, _expected in cases),
                "why?",
                "From [12, 4, 8], return the values Nia reaches, then remove "
                "duplicate values then reverse the list.",
                "/quit", "")),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = chat.stdout + chat.stderr
        require(chat.returncode == 0 and "Traceback" not in output
                and all(str(list(expected)) in output
                        for _request, expected in cases)
                and "Taught relation wording: 'can reach' → 'reaches'" in output
                and "The relation wording 'can reach' was matched to 'reaches'" in output
                and all(source in output for source in alias_sources)
                and "I can't determine whether 8 satisfy Nia reaches" in output,
                f"fresh-process chat did not answer all licensed variants:\n{output}")

    print("four request frames across six cases, including learned relation")
    print("wording and an order-sensitive duplicate case: PASS")
    print("target operation orders were not directly taught; component and")
    print("connective evidence retained: PASS")
    print("verified proof set and explicit-negative handling are preserved: PASS")
    print("unlicensed operation and relation paraphrases remain unsupported: PASS")
    print("relation wording from one source document does not transfer: PASS")
    print("scope: controlled operation recombination over exact primitives;")
    print("no broad paraphrase or planning claim")


if __name__ == "__main__":
    main()
