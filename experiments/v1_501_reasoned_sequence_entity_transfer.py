"""Transfer learned rule/procedure composition to a new entity and values.

The three-premise reasoning rule is validated on held-out sources, the `and`
sequence connective is learned from two compound demonstrations, and a new
entity with previously unseen relation facts is queried through two natural
request frames. Interleaved duplicates make the two operation orders yield
different answers. This is an authored development transfer check, not an
independent user benchmark.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_451_reasoned_procedure_composition import add_chain, discover_and_accept
from v1_497_composition_derived_practice import run_chat, require
from v1_500_learned_and_reasoned_composition import learn_components
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


CASES = (
    ("filter frame / deduplicate then reverse",
     "Filter 23, 5, 23, and 8 to values Mira reaches, then remove duplicate "
     "values and reverse the list.",
     (5, 23), ("mira:record-23", "mira:record-5"),
     "mira:record-8-negative"),
    ("bracketed frame / reverse then deduplicate",
     "From [23, 5, 23, 8], return values Mira reaches, then reverse the list "
     "and remove duplicate values.",
     (23, 5), ("mira:record-23", "mira:record-5"),
     "mira:record-8-negative"),
)


def main() -> None:
    knowledge = CRMSKnowledgeBase()
    discover_and_accept(knowledge)
    add_chain(knowledge, "Mira", "Nell", "Quartz", "23",
              "mira:record-23", conclusion="none")
    add_chain(knowledge, "Mira", "Omar", "Ridge", "5",
              "mira:record-5", conclusion="none")
    knowledge.add_negative_fact(
        "Mira", "reaches", "8", "mira:record-8-negative")
    procedures = learn_components()

    results = []
    for name, request, expected, positive_sources, negative_source in CASES:
        result = compose_verified_filter(request, knowledge, procedures)
        require(result is not None and result.status == "answered"
                and result.included_values == (23, 5, 23)
                and result.excluded_negative == (8,)
                and result.output_values == expected
                and result.inference_proofs
                and set(positive_sources) <= set(result.evidence_sources)
                and negative_source in result.evidence_sources,
                f"{name} failed to transfer proof-backed composition: {result}")
        results.append((name, request, expected, positive_sources,
                        negative_source))

    unknown_request = (
        "Filter 23, 5, 23, and 11 to values Mira reaches, then remove duplicate "
        "values and reverse the list.")
    unknown = compose_verified_filter(unknown_request, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (11,)
            and not unknown.output_values,
            f"open-world value entered transferred composition: {unknown}")

    with tempfile.TemporaryDirectory(prefix="crms-entity-transfer-") as d:
        root = Path(d)
        knowledge_path = root / "model.sqlite3"
        procedure_path = root / "procedures.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(procedure_path)
        CRMSResearchIndex().save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        for number, (name, request, expected, positive_sources,
                     negative_source) in enumerate(results):
            session = root / f"session-{number}"
            session.mkdir()
            for source in (knowledge_path, procedure_path, index_path,
                           root / "math.json", root / "translations.json"):
                shutil.copy2(source, session / source.name)
            output = run_chat(session, session / knowledge_path.name,
                              session / procedure_path.name,
                              session / index_path.name, (request, "why?"))
            require(str(list(expected)) in output
                    and all(source in output for source in positive_sources)
                    and negative_source in output
                    and "codex:sequence-teacher" in output
                    and "Because Mira" in output
                    and "Traceback" not in output,
                    f"{name} failed after fresh-process reload:\n{output}")

    print("held-out entity and numeric values use the transferred three-premise rule: PASS")
    print("two request frames preserve distinct operation orders: PASS")
    print("positive proof, explicit negative, and procedure lineage survive chat: PASS")
    print("unknown member blocks the whole recombination: PASS")
    print("scope: authored entity/value transfer check; not an independent user benchmark")


if __name__ == "__main__":
    main()
