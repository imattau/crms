"""Check bounded three-premise typed rules and their independently verified proofs."""

from __future__ import annotations

from dataclasses import asdict
import copy
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def seed() -> tuple[CRMSKnowledgeBase, object]:
    kb = CRMSKnowledgeBase()
    for subject, machine, component, site, source in (
            ("Ada", "Engine", "Rotor", "Lab", "ada"),
            ("Dee", "Vehicle", "Wheel", "Garage", "dee"),
            ("Nia", "Device", "Sensor", "Depot", "nia")):
        kb.add_fact(subject, "owns", machine, f"owns:{source}")
        kb.add_fact(machine, "has-part", component, f"part:{source}")
        kb.add_fact(component, "located-in", site, f"location:{source}")
        kb.add_fact(machine, "is-a", "machine", f"kind-machine:{source}")
        kb.add_fact(component, "is-a", "component", f"kind-component:{source}")
    rule = kb.add_inference_rule(
        "machine-component-location", "owns", "has-part", "can-access",
        third_relation="located-in", middle_kind="machine",
        second_middle_kind="component")
    return kb, rule


def main() -> None:
    kb, rule = seed()
    result = kb.infer_relation("Ada", "can-access", "Lab", max_expansions=2)
    require(result.status == "answered" and result.complete
            and result.lineage_count == 1,
            f"three-premise rule did not derive the complete conclusion: {result}")
    proof = result.proofs[0]
    require(len(proof["premises"]) == 3
            and [fact["object"] for fact in proof["middle_kind_facts"]]
            == ["machine", "component"],
            "three-premise proof omitted its chain or typed middle guards")
    facts = [asdict(fact) for fact in kb.facts()]
    check = verify_inference_proof(
        proof, facts, [asdict(rule)], expected_conclusion=result.conclusion)
    require(check.valid, f"independent verifier rejected three-premise proof: {check}")
    require(result.source_documents == (
        "kind-component:ada", "kind-machine:ada", "location:ada", "owns:ada", "part:ada"),
        f"proof lineage omitted premise or kind sources: {result.source_documents}")

    licensed = False
    for question, subject, site in (
            ("Can Ada access Lab?", "Ada", "Lab"),
            ("Can Dee access Garage?", "Dee", "Garage")):
        licensed = kb.teach_polar_question(
            question, subject=subject, relation="can-access", obj=site,
            answer=True)
    if not licensed:
        raise SystemExit("typed three-premise examples did not license a polar frame")
    language_answer = kb.ask("Can Nia access Depot?")
    require(language_answer.status == "answered" and language_answer.truth is True
            and language_answer.inference_proofs
            and "kind-component:nia" in kb.render(language_answer),
            f"language-facing answer omitted the typed recursive proof: {language_answer}")

    kb.add_fact("Lab", "has-status", "approved", "status:approved")
    outer_rule = kb.add_inference_rule(
        "approved-access", "can-access", "has-status", "can-use")
    nested = kb.infer_relation("Ada", "can-use", "approved")
    nested_check = verify_inference_proof(
        nested.proofs[0], [asdict(fact) for fact in kb.facts()],
        [asdict(rule), asdict(outer_rule)], expected_conclusion=nested.conclusion)
    require(nested.status == "answered" and nested_check.valid,
            f"three-premise proof could not serve as a recursive premise: {nested_check}")

    forged_kind = copy.deepcopy(proof)
    forged_kind["middle_kind_facts"][1]["object"] = "machine"
    require(not verify_inference_proof(forged_kind, facts, [asdict(rule)]).valid,
            "verifier accepted a mismatched second middle kind")
    missing_kind = copy.deepcopy(proof)
    missing_kind["middle_kind_facts"].pop()
    require(not verify_inference_proof(missing_kind, facts, [asdict(rule)]).valid,
            "verifier accepted a three-premise proof missing a type guard")

    limited = kb.infer_relation(
        "Ada", "can-access", "Lab", max_expansions=1)
    require(limited.status == "unknown" and not limited.complete
            and limited.reason_code == "search_limit" and not limited.proofs,
            "three-premise search returned a partial proof at its bound")
    kb.add_negative_fact("Rotor", "is-a", "component", "kind:counter")
    conflict = kb.infer_relation("Ada", "can-access", "Lab")
    require(conflict.status == "ambiguous" and conflict.support_class == "contested",
            "contradictory second-middle kind was silently accepted")

    try:
        CRMSKnowledgeBase().add_inference_rule(
            "untyped-3", "a", "b", "d", third_relation="c",
            middle_kind="one")
    except ValueError:
        pass
    else:
        raise SystemExit("three-premise rule accepted without both middle kinds")

    restored_source, _ = seed()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        session_path = root / "rule-session.json"
        restored_source.save(knowledge_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        loaded_result = restored.infer_relation("Ada", "can-access", "Lab")
        require(loaded_result.status == "answered"
                and len(loaded_result.proofs[0]["premises"]) == 3,
                "typed three-premise rule did not survive persistence")

        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(state_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input=("/teach-inference-rule cli-three|owns|has-part|located-in|can-access|"
                   "middle_kind=machine|second_middle_kind=component\n"
                   "/infer-relation Ada|can-access|Lab\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
    require("with middle kinds: machine, component." in process.stdout
                and "under rule cli-three" in process.stdout
                and "Rotor is-a component [sources: kind-component:ada]" in process.stdout,
                f"three-premise CLI route omitted rule or type evidence:\n{process.stdout}")

    print("three-premise inference diagnostic: PASS")
    print("bounded typed chain, language QA, independent proofs, tamper/limit/conflict handling, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
