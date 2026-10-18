"""Check direct rule teaching through a bounded natural-language form."""
from __future__ import annotations

from dataclasses import asdict
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_knowledge import CRMSKnowledgeBase
from crms_dialogue import CRMSDialogue
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


RULE = ('Teach CRMS rule "parent-transitivity": if X has relation "parent" '
        'to Y and Y has relation "parent" to Z, then X has relation '
        '"ancestor" to Z.')
TYPED_RULE = (
    'Teach CRMS rule "part-property": if X has relation "part" to Y, '
    'Y is of kind "component", and Y has relation "links" to Z, '
    'Z is of kind "material", and Z has relation "color" to W, '
    'then X has relation "has-property" to W.')


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-natural-rule-") as tmp:
        root = Path(tmp)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb = CRMSKnowledgeBase()
        kb.add_fact("Ada", "parent", "Bea", "source:ab")
        kb.add_fact("Bea", "parent", "Cal", "source:bc")
        kb.add_fact("A", "part", "M1", "source:part")
        kb.add_fact("M1", "links", "M2", "source:links")
        kb.add_fact("M2", "color", "blue", "source:color")
        kb.add_fact("M1", "is-a", "component", "source:kind-1")
        kb.add_fact("M2", "is-a", "material", "source:kind-2")
        kb.add_fact("Ada", "parent", "Bea", "source:parent-ab")
        kb.add_fact("Bea", "parent", "Cal", "source:parent-bc")
        kb.add_fact("Bea", "parent", "Ivy", "source:parent-bi")
        kb.add_fact("Dee", "parent", "Eli", "source:parent-de")
        kb.add_fact("Eli", "parent", "Fay", "source:parent-ef")
        kb.add_fact("Gus", "parent", "Hal", "source:parent-gh")
        kb.add_fact("Hal", "parent", "Ivy", "source:parent-hi")
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        conflicting_id = RULE.replace('"ancestor"', '"descendant"')
        chat_command = [
            sys.executable, str(ROOT / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json")]
        process = subprocess.run(
            chat_command,
            input=(RULE + "\n" + conflicting_id + "\n" + TYPED_RULE + "\n"
                   'Teach a yes/no frame from examples: '
                   '"Does Gus have relation ancestor to Cal?" => no; '
                   '"Does Ada have relation ancestor to Fay?" => no\n'
                   'Teach a yes/no frame from examples: '
                   '"Does Ada have relation ancestor to Cal?" => yes; '
                   '"Does Dee have relation ancestor to Fay?" => yes\n'
                   "/infer-relation Ada|ancestor|Cal\n"
                   "/infer-relation A|has-property|blue\n"
                   "Does Gus have relation ancestor to Ivy?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(process.returncode == 0
                and "Stored explicit rule parent-transitivity" in process.stdout
                and "Could not teach inference rule: rule id already names a different inference rule"
                in process.stdout
                and "Stored explicit rule part-property: part then links then color entails has-property with middle kinds component and material."
                in process.stdout
                and "The examples do not uniquely match explicit facts with one shared relation and varying entities; no change was saved."
                in process.stdout
                and "Yes/no frame licensed from 2 explicit fact examples (relation: ancestor)."
                in process.stdout
                and "Derived: Ada — ancestor → Cal." in process.stdout,
                f"natural rule teaching or collision rejection failed:\n"
                f"{process.stdout}\n{process.stderr}")
        persisted_followup = subprocess.run(
            chat_command, input="What about Ada?\n/quit\n", text=True,
            capture_output=True, check=False, timeout=30)
        persisted_output = persisted_followup.stdout.casefold()
        require(persisted_followup.returncode == 0
                and "answer: yes." in persisted_output
                and "rule proof" in persisted_output
                and "ada" in persisted_output,
                f"restarted dialogue failed:\n{persisted_followup.stdout}\n"
                f"{persisted_followup.stderr}")

        restored = CRMSKnowledgeBase.load(knowledge_path)
        result = restored.infer_relation("Ada", "ancestor", "Cal")
        require(result.status == "answered" and result.proofs,
                f"naturally taught rule was not retained: {result}")
        typed_result = restored.infer_relation("A", "has-property", "blue")
        natural_answer = restored.ask(
            "Does Gus have relation ancestor to Ivy?")
        dialogue = CRMSDialogue(restored)
        first_turn = dialogue.turn(
            "Does Gus have relation ancestor to Ivy?")
        followup_turn = dialogue.turn("What about Ada?")
        require(typed_result.status == "answered" and typed_result.proofs,
                f"naturally taught typed rule was not retained: {typed_result}")
        require(natural_answer.status == "answered"
                and natural_answer.truth is True
                and natural_answer.inference_proofs,
                f"ordinary-language question did not use the taught rule: {natural_answer}")
        require(first_turn.status == "answered"
                and first_turn.response is not None
                and first_turn.response.inference_proofs
                and followup_turn.status == "answered"
                and followup_turn.resolved_question
                == "Does Ada have relation ancestor to Ivy?"
                and followup_turn.response is not None
                and followup_turn.response.truth is True
                and followup_turn.response.inference_proofs,
                f"inference-backed follow-up failed or lost its proof: {followup_turn}")
        require(len(restored._inference_rules) == 2,
                "conflicting re-teaching changed the stored rule set")
        for answer in (result, typed_result):
            for proof in answer.proofs:
                proof_check = verify_inference_proof(
                    proof, [asdict(fact) for fact in restored.facts()],
                    [asdict(rule) for rule in restored._inference_rules.values()],
                    expected_conclusion=answer.conclusion)
                require(proof_check.valid,
                        f"independent verifier rejected taught rule proof: {proof_check}")

    print("natural-language rule teaching: PASS")
    print("binary and typed rule teaching, natural question and proof-backed follow-up across restart, collision rejection, persistence, proof verification: PASS")


if __name__ == "__main__":
    main()
