# Design: typed task and plan IR

**Status:** active contract; `crms_tasks.py` implements the data and invariants.
`crms_planner.py` implements the action contract and a deterministic executor.
`crms_actions.py` implements the two Family A adapters
(`select-verified-positive`, `apply-learned-procedure`);
`crms_family_b.py` implements the Family B domain actions. Request goals now
come from learned request frames (`docs/design_request_frames.md`); chat no
longer uses the regex compiler for composition. Licensed frames are mirrored
into the governed rule registry as family `request-frame`, and only active rules
may match. Typed plan executions are appended to `--plan-log` and summarized by
`run_compounding.py`. The regex path remains as a reference for parity tests.
**Date:** 2026-10-21

## Why

CRMS currently routes multi-step requests through a finite set of regex
families in `crms_task_composition.py`. Each new phrasing needs code, and the
harness can accidentally become the composer. The goal of the task IR is to
make composition an explicit, inspectable object:

```
ordinary language → TaskRequest → Plan → verified StepResults → answer
```

The IR does not understand language and does not plan by itself. It defines
what a request, a step, evidence, and a verified result are, so the planner,
chat, and independent checkers share one contract.

## Records

Implemented in `crms_tasks.py`:

| Record | Purpose |
|---|---|
| `TaskRequest` | Stable request id, original text, typed goal, slots, constraints, provenance |
| `Step` | One action invocation: id, action, inputs, output type, evidence, check, dependencies |
| `Plan` | Ordered, bounded steps plus a final verification check; deterministic `artifact_id` |
| `StepResult` | Outcome of one step: status, output, evidence, detail, reason code, structured metadata |
| `PlanResult` | Overall status (`ok`, `not_planned`, `unsupported`, `ambiguous`, `verification_failed`, `execution_failed`), output, step results, failures |
| `EvidenceRef` | Typed pointer to a fact, source, proof, procedure, rule, computation, translation, or generated artifact |
| `CheckSpec` | The check that must pass: exact, set, proof, citation, parity, oracle, or domain |

Invariants enforced today:

- a plan has 1–6 steps;
- step ids are unique and dependencies must appear earlier;
- actions and evidence kinds are explicit and non-empty;
- a successful step has an output;
- an `ok` plan result has a plan, an output, no failures, and every planned step
  completed;
- an unsupported/ambiguous/not-planned result cannot carry executed steps;
- plan and request ids are deterministic; a changed step changes the plan id.

## Action contract

Every action is a typed adapter with four methods:

```python
class Action(Protocol):
    name: str
    def can_apply(self, inputs: Mapping[str, Any], context: ActionContext) -> bool: ...
    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ActionContext) -> StepResult: ...
    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ActionContext) -> Verification: ...
```

Rules:

1. `apply` may propose an output; `verify` decides whether it is usable.
2. Verification is independent of the action that produced the output whenever
   an independent checker exists (proof checker, exact evaluator, parity
   harness, citation resolver).
3. An action declares its input and output types; the planner may not invent
   types or coerce silently.
4. An action returns `failed` with a reason or `ok` with evidence and output.
   It never returns a guessed value.
5. Actions are deterministic. Any bounded search reports its budget.

Initial adapters, in order:

1. `select-verified-positive` — implemented in `crms_actions.py`.
2. `apply-learned-procedure` — implemented in `crms_actions.py`.
3. `infer-relation` — bounded inference with a verified proof.
4. `compute-exact` — math/units with exact checks.
5. `translate-frame` — licensed translation frame.
6. `generate-code` — learned procedure → standalone Python.
7. `retrieve-source` — cited passage retrieval.
8. `write-grounded` — stored facts plus licensed sentence frames.

## Executor

`crms_planner.py` implements:

- `ActionRegistry` — named, typed actions; duplicate names rejected.
- `FunctionAction` — adapt a handler plus an independent verifier. A missing
  verifier fails the step; self-verification must be requested explicitly and
  is only appropriate for test fixtures.
- `ExecutionContext` — bounded data passed to actions and verifiers.
- `PlanExecutor` — resolves `STEP.output` references (including inside lists
  and dictionaries), runs steps in order, validates every `StepResult`,
  independently verifies each step, and stops at the first failure. It runs the
  optional plan-level verifier only after every step passes.
- Statuses: `execution_failed` for action/precondition/reference problems,
  `verification_failed` for a rejected step or plan check, and `ok` only when
  every planned step and the plan check pass.
- Failed and rejected step results stay in `PlanResult.steps` for audit; they
  never become the answer.

The executor never catches programming errors from an action; it converts only
explicit `ExecutionError` failures into a refused result.

## Planner

- **Search:** bounded best-first over action preconditions and postconditions.
- **Bounds:** ≤6 steps, explicit expansion budget, deterministic tie-break by
  `(step count, action order, input canonical JSON)`.
- **Ambiguity:** if two plans remain behaviorally distinct, return `ambiguous`
  with both plans and a contrastive request; do not execute either.
- **Missing support:** return `not_planned` or `unsupported` with the missing
  goal, never a partial answer.
- **Execution:** execute only a fully planned and verified prefix; a failed
  step stops the plan.
- **No harness composition:** the experiment supplies fixtures and oracles
  only. It never selects evidence or orders steps.
- **No regex goal parser:** goals come from learned request frames with typed
  slots. Explicit admin commands remain for debugging.

## Natural language → goal

Phase 2 uses learned request frames, implemented in
`crms_request_frames.py` and documented in `docs/design_request_frames.md`:

- the frame identifies the goal kind (`select-then-procedure`,
  `research-answer`, `math-compute`, `unit-convert`, `translate`,
  `generate-code`, `write-story`);
- slots bind entities, relations, numbers, lists, qualifiers, and the requested
  output form;
- at least two varied grounded examples license a frame;
- unknown wording or ungrounded slots abstain and ask for the smallest example
  that would license the construction.

This is the same evidence discipline as question frames; it is not a general
parser.

## Family A: select → procedure

Frozen specification: `experiments/scorecard/family_a_spec.md`.

Shape: a finite list of values, a relation with explicit positive and negative
evidence, and a learned list procedure. The request asks for the selected
values, a procedure applied to them, or both, in varied wording.

## Family B: retrieval → reasoning → domain action

Frozen specification: `experiments/scorecard/family_b_spec.md`.

Shape: a learned frame binds one of six domain goals. The typed plan retrieves a
cited source and re-resolves the citation, evaluates exact math or unit
evidence, applies a learned translation frame, generates a parseable Python
artifact from committed rules, or composes a deterministic fictional story.
Each action has an independent replay/parity verifier; failed steps abstain
instead of falling through to another route. `crms_plan_log.py` records the
request, frame, plan, steps, evidence, and failure candidate for the first
compounding baseline.

Independent oracle: a standalone Python function over the fixture fact set and
the taught procedure, not the planner.

Required negative controls: unknown claim (abstain), explicit negative evidence
(exclude), conflicting positive/negative evidence (ambiguous), missing
procedure (clarify), unsupported procedure (unsupported), partial request
(abstain), tampered output (verification failure).

## Migration from current composition

1. Keep `crms_task_composition.py` working during the transition. — done.
2. Wrap its proof-filter + procedure path as two actions. — done.
3. Compile its accepted request forms into `Plan` objects and compare outputs
   against the existing path on the same fixtures. — done, including rendered
   text parity (`experiments/v1_552_family_a_plan_parity.py`).
4. Flip chat to the plan path. — done for the explicit verified-filter frame.
5. Replace the transitional regex request compiler with learned request frames
   and typed slots, then remove the old dispatch. — done for chat:
   `crms_request_frames.py`, `experiments/v1_553_request_frames.py`,
   `experiments/v1_554_request_frame_composition.py`, and
   `experiments/v1_555_request_frame_chat.py`; the old compiler remains only as
   a reference path for parity and direct diagnostics.

The old `compose_verified_filter` remains as the reference path used by the
parity experiment and derived-composition checks. Chat uses only
`compose_verified_filter_via_frames`; it does not fall back to the regex
compiler.

## Open questions

- Should plans be persisted as reviewable artifacts, or regenerated per request?
  Default: regenerate; persist only verified derived results.
- What is the minimum evidence for an action that retrieves source text but does
  not assert a fact? Default: `EvidenceRef(kind="source")` with a resolvable
  citation.
- How are plan-level checks composed from step checks? Default: every step must
  pass, plus an optional independent plan oracle.
- How does a correction invalidate a plan-derived artifact? Phase 4 dependency
  graph: plan → step evidence → sources/rules.
