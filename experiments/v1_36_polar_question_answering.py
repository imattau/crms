"""Check evidence-grounded yes/no questions and open-world abstention.

Run from the project root with:
    python3 experiments/v1_36_polar_question_answering.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_dialogue import CRMSDialogue
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_closed_world_denial


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document("positive", "Engine record",
                       "Ada Lovelace designed the Analytical Engine.",
                       "records/engine.txt")
    positive_hit = index.search("Ada Lovelace designed Analytical Engine", limit=1)[0]
    index.add_document("negative", "Compiler record",
                       "Grace Hopper did not design the Compiler.",
                       "records/compiler.txt")
    negative_hit = index.search("Grace Hopper did not design Compiler", limit=1)[0]

    kb = CRMSKnowledgeBase()
    kb.add_fact_from_hit("Ada Lovelace", "designed", "the Analytical Engine",
                         index, positive_hit)
    kb.add_negative_fact_from_hit("Grace Hopper", "designed", "the Compiler",
                                  index, negative_hit)
    if kb.teach_polar_question(
            "Did Ada Lovelace design the Analytical Engine?",
            subject="Ada Lovelace", relation="designed",
            obj="the Analytical Engine", answer=True):
        raise SystemExit("one polar example unexpectedly licensed a frame")
    if not kb.teach_polar_question(
            "Did Grace Hopper design the Compiler?",
            subject="Grace Hopper", relation="designed",
            obj="the Compiler", answer=False):
        raise SystemExit("two varied polar examples did not license a frame")

    yes = kb.ask("Did Ada Lovelace design the Analytical Engine?")
    no = kb.ask("Did Grace Hopper design the Compiler?")
    if yes.status != "answered" or yes.truth is not True or yes.answer != "Yes":
        raise SystemExit(f"positive polar answer failed: {yes}")
    if no.status != "answered" or no.truth is not False or no.answer != "No":
        raise SystemExit(f"negative polar answer failed: {no}")
    if index.citation(positive_hit) not in kb.render(yes):
        raise SystemExit("positive answer omitted its source")
    if index.citation(negative_hit) not in kb.render(no):
        raise SystemExit("negative answer omitted its source")

    # A learned frame is not a closed-world assumption: missing evidence stays unknown.
    unknown = kb.ask("Did Ada Lovelace design the Compiler?")
    if unknown.status != "unknown":
        raise SystemExit(f"missing proposition was treated as false: {unknown}")

    kb.add_fact("Grace Hopper", "designed", "the Compiler", "conflict-source")
    conflict = kb.ask("Did Grace Hopper design the Compiler?")
    if conflict.status != "ambiguous" or "conflicts" not in kb.render(conflict):
        raise SystemExit(f"contradictory evidence was not surfaced: {conflict}")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        loaded = restored.ask("Did Ada Lovelace design the Analytical Engine?")
    if loaded.status != "answered" or loaded.truth is not True:
        raise SystemExit(f"polar knowledge did not persist: {loaded}")

    # A source-licensed relation frame should support the bounded active
    # do-support form without separately teaching a polar-question template.
    zero_index = CRMSResearchIndex()
    zero_kb = CRMSKnowledgeBase()
    for document_id, sentence, subject, obj in (
            ("create-engine", "Ada Lovelace created the Engine.",
             "Ada Lovelace", "the Engine"),
            ("create-compiler", "Grace Hopper created the Compiler.",
             "Grace Hopper", "the Compiler")):
        zero_index.add_document(document_id, document_id, sentence,
                                f"records/{document_id}.txt")
        hit = zero_index.search(sentence, limit=1)[0]
        zero_kb.add_fact_from_hit(subject, "create", obj, zero_index, hit)
        zero_kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="create", obj=obj,
            research_index=zero_index, hit=hit, predicate_phrase="created")
    zero_positive = zero_kb.ask("Did Ada Lovelace create the Engine?")
    zero_missing = zero_kb.ask("Did Ada Lovelace create Linux?")
    if (zero_positive.status != "answered" or zero_positive.answer != "Yes"
            or not zero_positive.evidence):
        raise SystemExit(
            f"source-licensed do-support failed positive evidence: {zero_positive}")
    chat_turn = CRMSDialogue(zero_kb).turn(
        "Did Ada Lovelace create the Engine?")
    if chat_turn.status != "answered" or "Yes" not in chat_turn.text:
        raise SystemExit(
            f"ordinary dialogue did not reach source-licensed do-support: {chat_turn}")
    object_wh = zero_kb.ask("What did Ada Lovelace create?")
    object_wh_unknown = zero_kb.ask("What did Sydney create?")
    if (object_wh.status != "answered" or object_wh.answer != "the Engine"
            or object_wh_unknown.status != "unknown"):
        raise SystemExit(
            f"source-licensed object wh-question failed: "
            f"{object_wh}; {object_wh_unknown}")
    if (zero_missing.status != "unknown"
            or zero_missing.truth is not None
            or "no explicit positive or negative evidence" not in
            (zero_missing.request or "")):
        raise SystemExit(
            f"source-licensed do-support treated absence as false: {zero_missing}")
    zero_kb.add_relation_type("create", "closed-world", "teacher:closed-world")
    closed_world_no = zero_kb.ask("Did Ada Lovelace create Linux?")
    if (closed_world_no.status != "answered" or closed_world_no.truth is not False
            or closed_world_no.answer != "No"
            or not any(item.get("object") == "closed-world"
                       for item in closed_world_no.evidence or [])):
        raise SystemExit(
            f"explicit closed-world declaration did not ground a negative answer: "
            f"{closed_world_no}")
    closed_world_inference = zero_kb.infer_relation(
        "Ada Lovelace", "create", "Linux")
    if (closed_world_inference.status != "denied"
            or not closed_world_inference.complete
            or not closed_world_inference.denial_evidence):
        raise SystemExit(
            "closed-world absence did not produce a complete, evidenced denial: "
            f"{closed_world_inference}")
    if "Denied by the declared closed-world boundary" not in \
            CRMSKnowledgeBase.render_inference(closed_world_inference):
        raise SystemExit("inference renderer did not preserve the denied status")
    expected = closed_world_inference.conclusion
    declaration = closed_world_inference.denial_evidence
    if verify_closed_world_denial(
            expected, declaration, expected_conclusion=expected,
            complete=False, facts=zero_kb.facts()).valid:
        raise SystemExit("denial verifier accepted an incomplete search")
    if verify_closed_world_denial(
            expected, None, expected_conclusion=expected,
            complete=True, facts=zero_kb.facts()).valid:
        raise SystemExit("denial verifier accepted a missing declaration")
    if verify_closed_world_denial(
            {"subject": "Grace Hopper", "relation": "create", "object": "Linux"},
            declaration, expected_conclusion=expected,
            complete=True, facts=zero_kb.facts()).valid:
        raise SystemExit("denial verifier accepted a different conclusion")
    still_yes = zero_kb.ask("Did Ada Lovelace create the Engine?")
    if still_yes.status != "answered" or still_yes.truth is not True:
        raise SystemExit("closed-world absence changed a directly supported positive")
    zero_kb.add_inference_rule(
        "parent-recursion", "parent", "ancestor", "ancestor")
    zero_kb.add_inference_rule(
        "parent-base", "parent", "parent", "ancestor")
    zero_kb.add_fact("Ada Lovelace", "parent", "Bea", "family:one")
    zero_kb.add_fact("Bea", "parent", "Cara", "family:two")
    zero_kb.add_relation_type(
        "ancestor", "closed-world", "teacher:ancestor-closed-world")
    bounded_no = zero_kb.infer_relation(
        "Ada Lovelace", "ancestor", "Missing", max_expansions=1)
    if (bounded_no.status != "unknown" or bounded_no.complete
            or bounded_no.failure_kind != "search_limit"
            or bounded_no.reason_code == "closed_world_absence"):
        raise SystemExit(
            f"incomplete inference was incorrectly turned into closed-world no: {bounded_no}")
    zero_kb.add_negative_fact(
        "Ada Lovelace", "create", "Linux", "explicit-negative")
    zero_negative = zero_kb.ask("Did Ada Lovelace create Linux?")
    if (zero_negative.status != "answered" or zero_negative.answer != "No"
            or zero_negative.truth is not False):
        raise SystemExit(
            f"source-licensed do-support missed explicit negative: {zero_negative}")
    with tempfile.TemporaryDirectory() as folder:
        memory_path = Path(folder) / "knowledge.json"
        fact_db_path = Path(folder) / "facts.sqlite"
        zero_kb.save(memory_path)
        disk_kb = CRMSKnowledgeBase.load(memory_path, fact_db=fact_db_path)
        disk_result = disk_kb.ask("Did Grace Hopper create the Compiler?")
        disk_unknown = disk_kb.ask("Did Grace Hopper create Linux?")
        disk_closed_no = disk_kb.ask("Did Ada Lovelace create Linux?")
        if disk_result.status != "answered" or disk_result.answer != "Yes":
            raise SystemExit(
                f"SQLite fact lookup failed source-licensed do-support: {disk_result}")
        if disk_unknown.status != "answered" or disk_unknown.truth is not False:
            raise SystemExit(
                f"SQLite closed-world schema did not answer missing proposition: {disk_unknown}")
        if disk_closed_no.status != "answered" or disk_closed_no.truth is not False:
            raise SystemExit(
                "SQLite relation schema did not preserve closed-world no semantics")

    copular_index = CRMSResearchIndex()
    copular_kb = CRMSKnowledgeBase()
    for document_id, sentence, subject, obj in (
            ("capital-france", "Paris is the capital of France.",
             "Paris", "France"),
            ("capital-england", "London is the capital of England.",
             "London", "England")):
        copular_index.add_document(document_id, document_id, sentence,
                                   f"records/{document_id}.txt")
        hit = copular_index.search(sentence, limit=1)[0]
        copular_kb.add_fact_from_hit(
            subject, "capital of", obj, copular_index, hit)
        copular_kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="capital of", obj=obj,
            research_index=copular_index, hit=hit,
            predicate_phrase="capital of")
    copular_yes = copular_kb.ask("Is Paris the capital of France?")
    copular_unknown = copular_kb.ask("Is Sydney the capital of Australia?")
    if copular_yes.status != "answered" or copular_yes.answer != "Yes":
        raise SystemExit(
            f"source-licensed copular question failed positive evidence: {copular_yes}")
    if copular_unknown.status != "unknown":
        raise SystemExit(
            f"copular question treated absence as false: {copular_unknown}")
    copular_kb.add_negative_fact(
        "Sydney", "capital of", "Australia", "explicit-negative")
    copular_no = copular_kb.ask("Is Sydney the capital of Australia?")
    if (copular_no.status != "answered" or copular_no.answer != "No"
            or copular_no.truth is not False):
        raise SystemExit(
            f"source-licensed copular question missed explicit negative: {copular_no}")

    print("polar question diagnostic: PASS")
    print("explicit positive/negative evidence, open-world unknown, conflict, citations, persistence, source-licensed do-support: PASS")


if __name__ == "__main__":
    main()
