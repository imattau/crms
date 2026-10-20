"""Family B typed-plan, verifier, and plan-log contract tests."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_family_b import (  # noqa: E402
    MathAnswerAction, ResearchAnswerAction, compose_family_b_via_frames,
)
from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_math import CRMSMath  # noqa: E402
from crms_model import CRMSModel  # noqa: E402
from crms_plan_log import (  # noqa: E402
    append_plan, load_plan_log, plan_trace, record_plan, summarize_plan_log,
)
from crms_planner import ExecutionContext  # noqa: E402
from crms_request_frames import GOALS, RequestFrameStore  # noqa: E402
from crms_research import CRMSResearchIndex  # noqa: E402
from crms_tasks import Step, StepResult  # noqa: E402
from crms_translation import CRMSTranslation  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    frames = RequestFrameStore()
    frames.add_seed_file(PROJECT / "crms_request_frames_seed.json")
    licensed = frames.frames()
    require(len(licensed) == 29,
            f"expected 29 seed frames, got {len(licensed)}")
    require(set(GOALS) == {
        "select-then-procedure", "research-answer", "math-compute",
        "unit-convert", "translate", "generate-code", "write-story"},
        f"unexpected goals: {GOALS}")
    family_b_frames = [frame for frame in licensed
                       if frame.goal != "select-then-procedure"]
    require(len(family_b_frames) == 9,
            f"expected 9 Family B frames, got {len(family_b_frames)}")

    knowledge = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    index.add_document(
        "people.txt", "people.txt",
        "Guido van Rossum created Python.\n"
        "Linus Torvalds created Linux.\n"
        "Ada Lovelace wrote the first algorithm.")
    math_model = CRMSMath()
    for question, answer in (
            ("What is 2 plus 3?", "5"), ("What is 5 plus 3?", "8")):
        math_model.teach(question, answer)
    math_model.teach_unit_equivalence("1 kilometre|1000 metres")
    math_model.teach_unit_equivalence("2 kilometres|2000 metres")
    translation = CRMSTranslation()
    translation.teach(
        "English", "French", "neutral", "Hello, {name}.",
        "Bonjour, {name}.",
        [("Hello, Ada.", "Bonjour, Ada."),
         ("Hello, Malik.", "Bonjour, Malik.")])
    rules = CRMSModel(max_composition_depth=1, max_workers=1)
    for inputs, outputs in (
            ([1, 2], [2, 1]), ([3, 4, 5], [5, 4, 3]), ([8], [8]),
            ([1, 3, 2], [2, 3, 1]), ([9, -1, 4], [4, -1, 9])):
        rules.teach("reverse the list", [(inputs, outputs)])

    requests = {
        "research-answer": "Who created Python?",
        "math-compute": "Compute 4 plus 5.",
        "unit-convert": "How many metres are in 3 kilometres?",
        "translate": "Translate Hello, Rowan into French.",
        "generate-code": "Write Python code that reverse the list.",
        "write-story": "Write a short story about Python.",
    }
    compositions = {}
    for goal, request in requests.items():
        composition = compose_family_b_via_frames(
            request, knowledge, rules, frames, index, math_model, translation)
        require(composition is not None and composition.status == "answered",
                f"{goal} did not answer: {composition}")
        require(composition.domain == goal, f"{goal} routed to {composition.domain}")
        require(composition.plan is not None
                and composition.plan.get("artifact_id", "").startswith("plan-"),
                f"{goal} produced no plan artifact")
        require(composition.steps, f"{goal} produced no step results")
        if goal == "research-answer":
            require("[Source: people.txt" in composition.text,
                    "research answer lost its citation")
            trace = plan_trace(composition.plan, composition.steps)
            require([step["action"] for step in trace]
                    == ["answer-research", "verify-citation"],
                    f"research plan steps are wrong: {trace}")
        compositions[goal] = composition

    unknown = compose_family_b_via_frames(
        "Who created Atlantis?", knowledge, rules, frames, index,
        math_model, translation)
    require(unknown is not None and unknown.status == "unsupported"
            and "couldn't verify" in unknown.text
            and "Atlantis created" not in unknown.text,
            f"unknown research request did not abstain: {unknown}")

    # A tampered realized answer must fail the independent verifier.
    research = ResearchAnswerAction(knowledge, index)
    step = Step(id="research", action="answer-research",
                inputs={"request": "Who created Python?"},
                output_type="research-answer")
    result = research.apply(step, {"request": "Who created Python?"},
                            ExecutionContext())
    require(result.status == "ok", f"research action failed: {result}")
    tampered = StepResult(
        step.id, "ok", output=dict(result.output, text="Someone else created Python."),
        evidence=result.evidence)
    require(not research.verify(
        step, {"request": "Who created Python?"}, tampered,
        ExecutionContext()).passed,
        "tampered research output passed verification")

    math_action = MathAnswerAction(math_model, rules)
    math_step = Step(id="math", action="answer-math",
                     inputs={"request": "Compute 4 plus 5."},
                     output_type="math-answer")
    math_result = math_action.apply(
        math_step, {"request": "Compute 4 plus 5."}, ExecutionContext())
    require(math_result.status == "ok", f"math action failed: {math_result}")
    altered = StepResult(
        math_step.id, "ok", output=dict(math_result.output, value="10"),
        evidence=math_result.evidence)
    require(not math_action.verify(
        math_step, {"request": "Compute 4 plus 5."}, altered,
        ExecutionContext()).passed,
        "tampered math output passed verification")

    with tempfile.TemporaryDirectory(prefix="crms-plan-log-") as folder:
        log = Path(folder) / "plans.jsonl"
        for composition in compositions.values():
            trace = plan_trace(composition.plan, composition.steps)
            append_plan(log, record_plan(
                request=requests[composition.domain],
                route="family-b",
                status=composition.status,
                goal=composition.domain,
                domain=composition.domain,
                frame_id=composition.request_frame_id,
                plan=composition.plan,
                steps=trace,
                failures=composition.failures,
            ))
        append_plan(log, record_plan(
            request="Who created Atlantis?", route="family-b",
            status="unsupported", goal="research-answer",
            frame_id="frame-unknown", plan=None, steps=(),
            failures=("no realized source answer",)))
        records = load_plan_log(log)
        summary = summarize_plan_log(records)
        require(summary["total"] == 7 and summary["answered"] == 6
                and summary["success_rate"] == 6 / 7,
                f"plan log summary is wrong: {summary}")
        require(summary["distinct_frames"] >= 6
                and summary["distinct_actions"] >= 6,
                f"plan log lost frame/action coverage: {summary}")
        require(summary["failure_count"] == 1,
                f"plan log lost the failure candidate: {summary}")

    print("seven goals and nine Family B frames license from the seed: PASS")
    print("research, math, unit, translation, code, and story answer via plans: PASS")
    print("unknown research abstains; tampered outputs fail verification: PASS")
    print("plan log computes the first compounding baseline: PASS")


if __name__ == "__main__":
    main()
