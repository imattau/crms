# Design: typed task and plan IR

**Status:** proposed contract; `crms_tasks.py` implements the data and
invariants. Planning and action adapters are not implemented yet.
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
| `StepResult` | Outcome of one step: status, output, evidence, detail |
| `PlanResult` | Overall status (`ok`, `not_planned`, `unsupported`, `ambiguous`, `verification_failed`), output, step results, failures |
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
    def apply(self, inputs: Mapping[str, Any], context: ActionContext) -> StepResult: ...
    def verify(self, step: Step, result: StepResult,
               context: ActionContext) -> Verification: ...
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

1. `select-verified-positive` — facts/proofs select values or entities.
2. `apply-learned-procedure` — `CRMSModel.predict` over a typed integer list.
3. `infer-relation` — bounded inference with a verified proof.
4. `compute-exact` — math/units with exact checks.
5. `translate-frame` — licensed translation frame.
6. `generate-code` — learned procedure → standalone Python.
7. `retrieve-source` — cited passage retrieval.
8. `write-grounded` — stored facts plus licensed sentence frames.

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

Phase 2 uses learned request frames:

- the frame identifies the goal kind (`select-then-procedure`,
  `retrieve-then-infer`, `retrieve-then-domain`);
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

Independent oracle: a standalone Python function over the fixture fact set and
the taught procedure, not the planner.

Required negative controls: unknown claim (abstain), explicit negative evidence
(exclude), conflicting positive/negative evidence (ambiguous), missing
procedure (clarify), unsupported procedure (unsupported), partial request
(abstain), tampered output (verification failure).

## Migration from current composition

1. Keep `crms_task_composition.py` working during the transition.
2. Wrap its proof-filter + procedure path as two actions.
3. Compile its accepted request forms into `Plan` objects and compare outputs
   against the existing path on the same fixtures.
4. Only then remove the regex dispatch, after parity and negative controls
   pass.

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
