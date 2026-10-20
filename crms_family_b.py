"""Typed Family B composition: retrieval -> reasoning -> domain action.

Family B routes requests through the same learned request-frame store as
Family A, but dispatches the bound goal to a bounded domain action. Every
action is independently verified before its output may be shown. The planner
never chooses evidence or silently falls back to a different route.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import Any, Mapping

from crms_codegen import (
    generate_list_then_math_python, generate_mapped_math_python,
    generate_math_python, generate_python, generate_unit_conversion_python,
    natural_language_request, render as render_codegen,
)
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath, render as render_math
from crms_model import CRMSModel
from crms_planner import (
    Action, ActionRegistry, ExecutionContext, PlanExecutor, Verification,
    check_for,
)
from crms_request_frames import RequestFrameStore
from crms_story import generate_short_story
from crms_tasks import EvidenceRef, Plan, Step, StepResult, TaskRequest, request_id
from crms_translation import CRMSTranslation, render as render_translation


@dataclass(frozen=True)
class FamilyBComposition:
    status: str
    text: str
    domain: str
    request_frame_id: str | None = None
    plan: dict[str, Any] | None = None
    steps: tuple[dict[str, Any], ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def plan_artifact_id(self) -> str | None:
        plan = self.plan or {}
        return plan.get("artifact_id")

    def to_log_record(self) -> dict[str, Any]:
        return {
            "route": "family-b",
            "status": self.status,
            "domain": self.domain,
            "request_frame_id": self.request_frame_id,
            "plan_artifact_id": self.plan_artifact_id,
            "steps": [dict(step) for step in self.steps],
            "failures": list(self.failures),
        }


class ResearchAnswerAction(Action):
    """Retrieve a source sentence and return its independently realized answer."""

    name = "answer-research"

    def __init__(self, knowledge: CRMSKnowledgeBase, index: Any) -> None:
        self.knowledge = knowledge
        self.index = index

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        return isinstance(inputs.get("request"), str) and bool(
            inputs["request"].strip())

    def _answer(self, request: str) -> dict[str, Any] | None:
        result = self.knowledge.research(request, self.index)
        realized = getattr(result, "realized_answer", None)
        if not isinstance(realized, Mapping):
            return None
        text = str(realized.get("text") or "").strip()
        citation = str(realized.get("citation") or "").strip()
        title = str(realized.get("source_title") or "").strip()
        if not text or not citation or not title:
            return None
        return {
            "text": f"{text} [Source: {title}; {citation}]",
            "answer": text,
            "citation": citation,
            "title": title,
            "sentence": str(realized.get("sentence") or ""),
            "method": str(realized.get("method") or ""),
        }

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        request = str(inputs["request"]).strip()
        answer = self._answer(request)
        if answer is None:
            return StepResult(
                step.id, "failed", reason_code="source_answer_unresolved",
                detail=("No independently realized source answer was found; "
                        "I won't assemble one from loose word matches."))
        evidence = (EvidenceRef(
            "source", answer["citation"], source=answer["title"],
            detail={
                "sentence": answer["sentence"],
                "method": answer["method"],
                "query": request,
            }),)
        return StepResult(
            step.id, "ok", output=answer, evidence=evidence,
            reason_code="source_answer",
            detail=f"realized a cited answer from {answer['title']}")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        request = str(inputs["request"]).strip()
        replay = self._answer(request)
        if replay is None:
            return Verification(False, "the source answer did not replay")
        if replay["text"] != result.output.get("text"):
            return Verification(False, "the realized answer changed on replay")
        if replay["citation"] != result.output.get("citation"):
            return Verification(False, "the cited passage changed on replay")
        return Verification(True)


class VerifyCitationAction(Action):
    """Resolve a citation again before an answer is shown."""

    name = "verify-citation"

    def __init__(self, index: Any) -> None:
        self.index = index

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        return (isinstance(inputs.get("answer"), str)
                and bool(inputs["answer"].strip())
                and isinstance(inputs.get("citation"), str)
                and bool(inputs["citation"].strip()))

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        citation = str(inputs["citation"]).strip()
        try:
            source_text = self.index.resolve_citation(citation)
        except (KeyError, ValueError) as error:
            return StepResult(
                step.id, "failed", reason_code="citation_unresolved",
                detail=f"the cited source no longer resolves: {error}")
        return StepResult(
            step.id, "ok",
            output={
                "text": str(inputs["answer"]).strip(),
                "citation": citation,
                "source_text": source_text,
            },
            evidence=(EvidenceRef("source", citation),),
            reason_code="citation_verified",
            detail="citation resolves to the stored source text")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        citation = str(inputs["citation"]).strip()
        try:
            source_text = self.index.resolve_citation(citation)
        except (KeyError, ValueError) as error:
            return Verification(False, f"citation no longer resolves: {error}")
        if source_text != result.output.get("source_text"):
            return Verification(False, "citation source text changed on replay")
        return Verification(True)


class MathAnswerAction(Action):
    """Evaluate an exact arithmetic or unit request through CRMSMath."""

    name = "answer-math"

    def __init__(self, math_model: CRMSMath, rules: CRMSModel) -> None:
        self.math_model = math_model
        self.rules = rules

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        return isinstance(inputs.get("request"), str) and bool(
            inputs["request"].strip())

    def _answer(self, request: str) -> dict[str, Any] | None:
        normalized = re.sub(
            r"^\s*what\s+is\s+the\s+value\s+of\s+",
            "What is ", request, flags=re.IGNORECASE)
        result = self.math_model.ask(
            normalized,
            grounded_cardinals=self.rules.grounded_cardinal_phrases())
        if result is None or result.status != "answered":
            return None
        return {
            "text": render_math(result),
            "value": str(result.value),
            "unit": result.unit,
            "examples": len(result.examples or ()),
            "unit_evidence": len(result.unit_evidence or ()),
        }

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        request = str(inputs["request"]).strip()
        answer = self._answer(request)
        if answer is None:
            return StepResult(
                step.id, "failed", reason_code="math_unresolved",
                detail=("I couldn't resolve that request to exact learned "
                        "arithmetic or unit evidence."))
        return StepResult(
            step.id, "ok", output=answer,
            evidence=(EvidenceRef(
                "computation", request,
                detail={"value": answer["value"], "unit": answer["unit"],
                        "examples": answer["examples"]}),),
            reason_code="math_answered",
            detail=f"exact value {answer['value']}"
                   + (f" {answer['unit']}" if answer["unit"] else ""))

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        replay = self._answer(str(inputs["request"]).strip())
        if replay is None:
            return Verification(False, "the math request no longer resolves")
        for key in ("text", "value", "unit"):
            if replay[key] != result.output.get(key):
                return Verification(False, f"math {key} changed on replay")
        return Verification(True)


class TranslateAnswerAction(Action):
    """Apply one learned translation frame and verify it again."""

    name = "answer-translation"

    def __init__(self, translation_model: CRMSTranslation) -> None:
        self.translation_model = translation_model

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        return isinstance(inputs.get("request"), str) and bool(
            inputs["request"].strip())

    def _answer(self, request: str) -> dict[str, Any] | None:
        result = self.translation_model.translate(request)
        if result is None or result.status != "translated":
            return None
        return {
            "text": render_translation(result),
            "output": result.output,
            "template": result.template,
            "register": result.register,
            "language_pair": list(result.language_pair or ()),
        }

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        request = str(inputs["request"]).strip()
        answer = self._answer(request)
        if answer is None:
            return StepResult(
                step.id, "failed", reason_code="translation_unresolved",
                detail=("No learned translation frame resolves this request."))
        return StepResult(
            step.id, "ok", output=answer,
            evidence=(EvidenceRef(
                "translation", str(answer["template"]),
                detail={"output": answer["output"],
                        "register": answer["register"],
                        "language_pair": answer["language_pair"]}),),
            reason_code="translated",
            detail=f"translated via {answer['template']}")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        replay = self._answer(str(inputs["request"]).strip())
        if replay is None:
            return Verification(False, "the translation no longer resolves")
        for key in ("text", "output", "template"):
            if replay[key] != result.output.get(key):
                return Verification(False, f"translation {key} changed on replay")
        return Verification(True)


def _generate_code(rules: CRMSModel, math_model: CRMSMath,
                   request: str):
    instruction = natural_language_request(request) or request
    generated = generate_list_then_math_python(
        rules, math_model, instruction,
        grounded_cardinals=rules.grounded_cardinal_phrases())
    if generated is None:
        generated = generate_python(rules, instruction)
    if generated is None:
        generated = generate_mapped_math_python(
            math_model, instruction,
            grounded_cardinals=rules.grounded_cardinal_phrases())
    if generated is None:
        generated = generate_math_python(
            math_model, instruction,
            grounded_cardinals=rules.grounded_cardinal_phrases())
    if generated is None:
        generated = generate_unit_conversion_python(math_model, instruction)
    return generated


class GenerateCodeAction(Action):
    """Generate a bounded Python artifact from committed learned evidence."""

    name = "generate-code"

    def __init__(self, rules: CRMSModel, math_model: CRMSMath) -> None:
        self.rules = rules
        self.math_model = math_model

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        return isinstance(inputs.get("request"), str) and bool(
            inputs["request"].strip())

    def _answer(self, request: str) -> dict[str, Any] | None:
        generated = _generate_code(self.rules, self.math_model, request)
        if generated is None:
            return None
        try:
            ast.parse(generated.source)
        except SyntaxError:
            return None
        return {
            "text": render_codegen(generated, request),
            "source": generated.source,
            "provenance_id": generated.provenance_id,
            "domain": generated.domain,
            "evidence_phrases": list(generated.evidence_phrases),
        }

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        request = str(inputs["request"]).strip()
        answer = self._answer(request)
        if answer is None:
            return StepResult(
                step.id, "failed", reason_code="codegen_unresolved",
                detail=("I couldn't resolve that request to committed learned "
                        "operations with a parseable Python artifact."))
        return StepResult(
            step.id, "ok", output=answer,
            evidence=(EvidenceRef(
                "generated-code", answer["provenance_id"],
                detail={"domain": answer["domain"],
                        "source": answer["source"],
                        "evidence_phrases": answer["evidence_phrases"]}),),
            reason_code="code_generated",
            detail=f"generated a parseable Python artifact "
                   f"({answer['provenance_id']})")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        request = str(inputs["request"]).strip()
        replay = self._answer(request)
        if replay is None:
            return Verification(False, "code generation no longer resolves")
        if replay["source"] != result.output.get("source"):
            return Verification(False, "generated source changed on replay")
        if replay["provenance_id"] != result.output.get("provenance_id"):
            return Verification(False, "generated provenance changed on replay")
        try:
            ast.parse(result.output["source"])
        except (KeyError, SyntaxError, TypeError) as error:
            return Verification(False, f"generated source is not parseable: {error}")
        return Verification(True)


class WriteStoryAction(Action):
    """Compose a deterministic fictional story from a bound topic."""

    name = "write-story"

    def __init__(self) -> None:
        pass

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        return isinstance(inputs.get("topic"), str) and bool(
            inputs["topic"].strip())

    def _answer(self, topic: str) -> dict[str, Any] | None:
        try:
            story = generate_short_story(topic)
        except ValueError:
            return None
        return {
            "text": story.render(),
            "template_id": story.template_id,
            "topic": story.topic,
        }

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        topic = str(inputs["topic"]).strip()
        answer = self._answer(topic)
        if answer is None:
            return StepResult(
                step.id, "failed", reason_code="story_unresolved",
                detail="The story topic is not usable by the bounded story grammar.")
        return StepResult(
            step.id, "ok", output=answer,
            evidence=(EvidenceRef(
                "generated-text", answer["template_id"],
                detail={"topic": answer["topic"], "fictional": True}),),
            reason_code="story_written",
            detail=f"composed fictional story {answer['template_id']}")

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        replay = self._answer(str(inputs["topic"]).strip())
        if replay is None:
            return Verification(False, "the story request no longer resolves")
        if replay["text"] != result.output.get("text"):
            return Verification(False, "story text changed on replay")
        return Verification(True)


def _check_plan(plan: Plan, outputs: Mapping[str, Any],
                context: ExecutionContext) -> Verification:
    last = outputs.get(plan.steps[-1].id)
    text = last.get("text") if isinstance(last, Mapping) else None
    passed = isinstance(text, str) and bool(text.strip())
    return Verification(
        passed, "" if passed else "the final Family B step produced no text")


def _actions(knowledge: CRMSKnowledgeBase, index: Any, rules: CRMSModel,
             math_model: CRMSMath,
             translation_model: CRMSTranslation) -> ActionRegistry:
    registry = ActionRegistry()
    registry.register(ResearchAnswerAction(knowledge, index))
    registry.register(VerifyCitationAction(index))
    registry.register(MathAnswerAction(math_model, rules))
    registry.register(TranslateAnswerAction(translation_model))
    registry.register(GenerateCodeAction(rules, math_model))
    registry.register(WriteStoryAction())
    return registry


def _plan_for(goal: str, instruction: str, slots: Mapping[str, Any],
              frame_id: str) -> Plan:
    common = {
        "id": request_id(instruction, goal),
        "text": instruction,
        "goal": goal,
        "slots": dict(slots),
        "provenance": {"parser": "learned-request-frame", "frame_id": frame_id},
    }
    if goal == "research-answer":
        steps = (
            Step(
                id="research", action="answer-research",
                inputs={"request": instruction}, output_type="research-answer",
                check=check_for("citation", ref="realized-answer"),
            ),
            Step(
                id="citation", action="verify-citation",
                inputs={
                    "answer": "research.output.text",
                    "citation": "research.output.citation",
                },
                output_type="cited-answer",
                check=check_for("citation", ref="resolved-source"),
                depends_on=("research",),
            ),
        )
    elif goal in {"math-compute", "unit-convert"}:
        request = instruction
        if goal == "unit-convert":
            quantity = str(slots.get("quantity", "")).strip()
            unit = str(slots.get("unit", "")).strip()
            if quantity and unit:
                request = f"Convert {quantity} to {unit}."
        steps = (
            Step(
                id="math", action="answer-math",
                inputs={"request": request}, output_type="math-answer",
                check=check_for("exact", ref="learned-arithmetic"),
            ),
        )
    elif goal == "translate":
        source_text = str(slots.get("source_text", "")).strip()
        target_language = str(slots.get("target_language", "")).strip()
        request = (f'Translate "{source_text}" into {target_language}.'
                   if source_text and target_language else instruction)
        steps = (
            Step(
                id="translation", action="answer-translation",
                inputs={"request": request}, output_type="translation",
                check=check_for("parity", ref="learned-translation"),
            ),
        )
    elif goal == "generate-code":
        steps = (
            Step(
                id="code", action="generate-code",
                inputs={"request": instruction}, output_type="generated-code",
                check=check_for("domain", ref="parseable-python"),
            ),
        )
    elif goal == "write-story":
        steps = (
            Step(
                id="story", action="write-story",
                inputs={"topic": str(slots.get("topic", ""))},
                output_type="generated-text",
                check=check_for("domain", ref="fictional-story"),
            ),
        )
    else:
        raise ValueError(f"unsupported Family B goal: {goal!r}")
    return Plan(
        request=TaskRequest(**common),
        steps=steps,
        verification=check_for("oracle", ref="family-b-output"),
    )


def compose_family_b_via_frames(
        instruction: str, knowledge: CRMSKnowledgeBase, rules: CRMSModel,
        frames: RequestFrameStore, index: Any, math_model: CRMSMath,
        translation_model: CRMSTranslation, *,
        allowed_frame_ids: set[str] | None = None,
        ) -> FamilyBComposition | None:
    """Match one governed Family B frame, build its plan, and execute it."""
    match_result = frames.match(
        instruction, allowed_frame_ids=allowed_frame_ids)
    if match_result.status == "no_match":
        return None
    if match_result.status == "ambiguous":
        templates = "; ".join(
            match.frame.template_text() for match in match_result.matches[:3])
        return FamilyBComposition(
            "ambiguous",
            "I found more than one licensed request frame for this wording. "
            "Please rephrase, or teach a narrower frame. Candidates: "
            + templates + ".",
            "family-b",
        )
    match = match_result.match
    if match is None:
        return None
    goal = match.frame.goal
    if goal == "select-then-procedure":
        return None
    if goal not in {"research-answer", "math-compute", "unit-convert",
                    "translate", "generate-code", "write-story"}:
        return FamilyBComposition(
            "unsupported",
            f"No Family B action is registered for the goal {goal!r}.",
            goal,
            request_frame_id=match.frame.frame_id,
        )
    plan = _plan_for(goal, instruction, match.slots, match.frame.frame_id)
    result = PlanExecutor(
        _actions(knowledge, index, rules, math_model, translation_model),
        plan_verifier=_check_plan).execute(
            plan, ExecutionContext({"instruction": instruction}))
    steps = tuple(step.to_dict() for step in result.steps)
    plan_payload = None
    if result.plan is not None:
        plan_payload = result.plan.to_dict()
        plan_payload["artifact_id"] = result.plan.artifact_id
    if result.status == "ok" and isinstance(result.output, Mapping):
        text = str(result.output.get("text") or "").strip()
        if text:
            return FamilyBComposition(
                "answered", text, goal,
                request_frame_id=match.frame.frame_id,
                plan=plan_payload,
                steps=steps,
            )
    failures = tuple(result.failures) or (
        f"the {goal} plan produced no answer",)
    return FamilyBComposition(
        "unsupported",
        "I couldn't verify this request: " + "; ".join(failures) + ".",
        goal,
        request_frame_id=match.frame.frame_id,
        plan=plan_payload,
        steps=steps,
        failures=failures,
    )
