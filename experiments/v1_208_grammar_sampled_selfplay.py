"""Seeded self-play sampling from the active grammar with mechanical checks.

The explorer samples procedures from CRMS's configured operation grammar.
An independent interpreter generates demonstrations; an isolated learner gets
machine answers to contrastive probes. Targets one step beyond its active
search depth are retained as no-fit cases and passed to report-only proposal
discovery. No task or learned result enters persistent user memory.
"""
from __future__ import annotations

import itertools
import copy
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure


OPS = {"add_k", "reverse", "keep_odds", "sort_ascending", "repeat_each_k", "first"}
TRAINING_INPUTS = [[], [3, -2, 1, 4], [-5, 0, 2], [8, 7, 7], [1], [4, -1, 6]]


def reference(procedure: tuple[Step, ...], values: list[int]) -> list[int]:
    """Independent interpreter for the explicitly sampled operation subset."""
    result = list(values)
    for step in procedure:
        operation, parameters = step.operation, step.parameters
        if operation == "add_k":
            result = [value + parameters["k"] for value in result]
        elif operation == "reverse":
            result.reverse()
        elif operation == "keep_odds":
            result = [value for value in result if value % 2]
        elif operation == "sort_ascending":
            result = sorted(result)
        elif operation == "repeat_each_k":
            result = [value for item in result
                      for value in [item] * parameters["k"]]
        elif operation == "first":
            result = result[:1]
        else:
            raise ValueError(f"sampler emitted unsupported operation {operation!r}")
    return result


def audit_inputs() -> list[list[int]]:
    values = (-2, -1, 0, 1, 2)
    exhaustive = [list(items) for size in range(5)
                  for items in itertools.product(values, repeat=size)]
    rng = random.Random(208)
    return exhaustive + [[rng.randint(-20, 20)
                          for _ in range(rng.randint(5, 12))]
                         for _ in range(32)]


def step_key(step: Step) -> tuple[str, tuple[tuple[str, object], ...]]:
    return step.operation, tuple(sorted(step.parameters.items()))


def independent_absolute_difference(values: list[int]) -> list[int]:
    """Target outside the active grammar, defined without CRMS executors."""
    return [abs(values[index] - values[index + 1])
            for index in range(len(values) - 1)]


def independent_square_plus_next(values: list[int]) -> list[int]:
    """A distinct local-expression target used to test rule composition."""
    return [values[index] * values[index] + values[index + 1]
            for index in range(len(values) - 1)]


def sample_targets(model: CRMSModel, rng: random.Random,
                   probes: list[list[int]]) -> list[tuple[Step, ...]]:
    """Sample one-step in-grammar and distinguishing two-step tasks."""
    eligible = [step for step in model._steps if step.operation in OPS]
    if len(eligible) < 4:
        raise SystemExit("active grammar lacks enough reference-interpretable operations")
    one_step = rng.sample(eligible, min(4, len(eligible)))
    # Use the active executor only to exclude targets that are already
    # single-step behaviors. Target labels and audit expectations still come
    # from the independent reference interpreter below.
    signatures = {
        tuple(tuple(_apply_procedure((step,), values)) for values in probes)
        for step in model._steps
    }
    two_step: list[tuple[Step, ...]] = []
    seen = set()
    order = list(itertools.product(eligible, repeat=2))
    rng.shuffle(order)
    for pair in order:
        if step_key(pair[0]) == step_key(pair[1]):
            continue
        signature = tuple(tuple(reference(pair, values)) for values in probes)
        if signature in signatures or signature in seen:
            continue
        seen.add(signature)
        two_step.append(pair)
        if len(two_step) == 8:
            break
    if len(two_step) < 4:
        raise SystemExit("sampler could not find enough behaviorally distinct two-step tasks")
    return [*((step,) for step in one_step), *two_step]


def train(model: CRMSModel, index: int, target: tuple[Step, ...],
          probes: list[list[int]]) -> tuple[str, int, int, float, int]:
    phrase = f"selfplay sampled task {index}"
    examples = [(values, reference(target, values))
                for values in TRAINING_INPUTS]
    started = time.perf_counter()
    for round_number in range(1, 16):
        result = model.teach(phrase, examples)
        if result.status == "learned":
            procedure = model._procedures[phrase]
            counterexample = next((values for values in probes
                                   if reference(procedure, values)
                                   != reference(target, values)), None)
            if counterexample is None:
                return ("learned", round_number, len(examples),
                        time.perf_counter() - started,
                        result.search_expansions)
            examples.append((counterexample, reference(target, counterexample)))
            continue
        if result.status == "no_fit":
            records = model.no_fit_cases()
            if not any(row["instruction"] == phrase for row in records):
                raise SystemExit("no-fit result was not recorded for the task")
            if not result.search_complete:
                raise SystemExit("incomplete search was recorded as a no-fit result")
            return ("no_fit", round_number, len(examples),
                    time.perf_counter() - started, result.search_expansions)
        if result.status != "need_more_examples":
            raise SystemExit(f"task {index} stopped with {result.status}")
        probe = result.contrastive_input
        if probe is None or any(existing == probe for existing, _ in examples):
            raise SystemExit(f"task {index} has no new contrastive input")
        examples.append((list(probe), reference(target, list(probe))))
    raise SystemExit(f"task {index} exceeded the bounded teaching-round limit")


def main() -> None:
    learner = CRMSModel(max_composition_depth=1, max_workers=1, max_add=2)
    probes = audit_inputs()
    targets = sample_targets(learner, random.Random(208), probes)
    counts = {"learned": 0, "no_fit": 0}
    total_rounds = total_examples = total_expansions = 0
    total_seconds = 0.0
    for index, target in enumerate(targets):
        status, rounds, examples, elapsed, expansions = train(
            learner, index, target, probes)
        counts[status] += 1
        total_rounds += rounds
        total_examples += examples
        total_expansions += expansions
        total_seconds += elapsed
        if status == "learned":
            print(f"task {index}: sampled_depth={len(target)}; status=learned; "
                  f"examples={examples}; rounds={rounds}; expansions={expansions}; "
                  f"seconds={elapsed:.4f}; audit={len(probes)}; PASS")
        else:
            print(f"task {index}: sampled_depth={len(target)}; status=no_fit; "
                  f"examples={examples}; rounds={rounds}; expansions={expansions}; "
                  f"seconds={elapsed:.4f}; complete_search=true; recorded=PASS")

    if not counts["learned"] or not counts["no_fit"]:
        raise SystemExit(f"curriculum did not exercise both outcomes: {counts}")
    proposals = learner.propose_primitive_candidates()
    if any(not proposal.get("report_only") for proposal in proposals):
        raise SystemExit("self-play primitive discovery promoted an unreviewed proposal")
    if len(learner.no_fit_cases()) != counts["no_fit"]:
        raise SystemExit("no-fit record count differs from sampled failures")
    print(f"grammar-sampled self-play: learned={counts['learned']}; "
          f"no_fit={counts['no_fit']}; examples={total_examples}; "
          f"training rounds={total_rounds}; search_expansions={total_expansions}; "
          f"seconds={total_seconds:.4f}; report-only proposals={len(proposals)}; PASS")

    # Separately sample a target outside the learner's active operation table.
    # Its output labels come from this small independent reference function,
    # and three distinct phrases provide the proposal's cross-phrase evidence.
    external_phrases = (
        "find the absolute difference of adjacent values",
        "take the magnitude of the first minus the next",
        "for each pair return how far apart the values are",
    )
    rng = random.Random(2081)
    external_examples: dict[str, list[tuple[list[int], list[int]]]] = {}
    for phrase in external_phrases:
        examples = []
        for _ in range(12):
            values = [rng.randint(-30, 30)
                      for _ in range(rng.randint(8, 16))]
            examples.append((values, independent_absolute_difference(values)))
        result = learner.teach(phrase, examples)
        if result.status != "no_fit" or not result.search_complete:
            raise SystemExit(
                f"out-of-grammar task did not produce a complete no-fit: {result}")
        external_examples[phrase] = examples

    expected = {
        "operation": "map_window_expression",
        "expression": "(abs (- x y))",
        "stride": 1,
    }
    external_proposals = [
        proposal for proposal in learner.propose_primitive_candidates()
        if proposal["descriptor"].get("operation") == "map_window_expression"
        and proposal["descriptor"].get("expression") == expected["expression"]
        and proposal["descriptor"].get("stride") == expected["stride"]
    ]
    if (len(external_proposals) != 1
            or not external_proposals[0]["held_out_valid"]
            or not external_proposals[0]["mdl_gate_passed"]
            or not external_proposals[0]["report_only"]):
        raise SystemExit(
            f"independent out-of-grammar rule did not pass proposal gates: "
            f"{external_proposals}")
    proposal = external_proposals[0]
    if set(proposal["supporting_instructions"]) != set(external_phrases):
        raise SystemExit("out-of-grammar proposal lacked independent phrase support")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        rules_path = root / "rules.json"
        cli_model = copy.deepcopy(learner)
        cli_model.save(rules_path)
        chat = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "index.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(rules_path), "--rule-depth", "1",
             "--rule-max-add", "2"],
            input=f"Learn from validated primitive proposal {proposal['artifact_id']}\n/quit\n",
            text=True, capture_output=True, check=True, timeout=30)
        if "Learned validated primitive" not in chat.stdout:
            raise SystemExit(
                f"natural-language primitive learning route failed:\n{chat.stdout}")
        restored = CRMSModel(
            rules_path, max_composition_depth=1, max_add=2, max_workers=1)
        if (not restored.accepted_primitive_candidates()
                or any(restored.predict(phrase, [17, -3]).status != "ok"
                       for phrase in external_phrases)):
            raise SystemExit("natural-language primitive learning was not persisted")

        auto_rules_path = root / "auto-rules.json"
        auto_model = copy.deepcopy(learner)
        auto_model.save(auto_rules_path)
        auto_chat = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(root / "auto-knowledge.json"),
             "--index", str(root / "auto-index.json"),
             "--dialogue-state", str(root / "auto-dialogue.json"),
             "--rules", str(auto_rules_path), "--rule-depth", "1",
             "--rule-max-add", "2"],
            input="Learn the best validated primitive proposal.\n/quit\n",
            text=True, capture_output=True, check=True, timeout=30)
        if "Learned validated primitive" not in auto_chat.stdout:
            raise SystemExit(
                f"automatic proposal selection failed:\n{auto_chat.stdout}")
        auto_restored = CRMSModel(
            auto_rules_path, max_composition_depth=1, max_add=2, max_workers=1)
        if (not auto_restored.accepted_primitive_candidates()
                or any(auto_restored.predict(phrase, [17, -3]).status != "ok"
                       for phrase in external_phrases)):
            raise SystemExit("automatically selected rule was not persisted")

    atomicity_trial = copy.deepcopy(learner)
    trial_phrase = external_phrases[0]
    atomicity_trial._examples[trial_phrase].append(([1001, -1002], [0]))
    before_steps = len(atomicity_trial._steps)
    before_procedures = dict(atomicity_trial._procedures)
    try:
        atomicity_trial.learn_primitive_proposal(proposal["artifact_id"])
    except ValueError:
        pass
    else:
        raise SystemExit("transactional promotion accepted a contradictory example")
    if (len(atomicity_trial._steps) != before_steps
            or atomicity_trial._procedures != before_procedures
            or atomicity_trial.accepted_primitive_candidates()):
        raise SystemExit("failed transactional promotion changed the active model")

    learned_artifact = learner.learn_primitive_proposal(proposal["artifact_id"])
    if (learned_artifact["status"] != "learned"
            or learned_artifact["descriptor"] != expected
            or set(learned_artifact["learned_phrases"]) != set(external_phrases)
            or learned_artifact["replayed_examples"]
                != sum(map(len, external_examples.values()))):
        raise SystemExit(
            f"transactional primitive learning returned incomplete evidence: "
            f"{learned_artifact}")
    for phrase, examples in external_examples.items():
        for inputs, outputs in examples:
            prediction = learner.predict(phrase, inputs)
            if prediction.status != "ok" or prediction.output != outputs:
                raise SystemExit(
                    f"learned external rule failed source example for {phrase}")

    # A newly learned primitive should also unlock older complete failures.
    # This composed target is intentionally not part of the proposal's support.
    composition_model = CRMSModel(
        max_composition_depth=2, max_workers=1, max_add=1, max_scale=3,
        max_modulus=3, max_rotation=1, max_repeat=2,
        max_position_stride=3)
    composition_phrases = (
        "square each left value then add its neighbor",
        "square each left number then add its follower",
        "square first then add next",
    )
    composition_rng = random.Random(2082)
    composition_training = {}
    for phrase in composition_phrases:
        examples = []
        for _ in range(12):
            values = [composition_rng.randint(-30, 30)
                      for _ in range(composition_rng.randint(8, 16))]
            examples.append((values, independent_square_plus_next(values)))
        composition_training[phrase] = examples
        seeded = composition_model.teach(phrase, examples)
        if seeded.status != "no_fit":
            raise SystemExit(
                f"composed-learning fixture unexpectedly fit before discovery: "
                f"{phrase} -> {seeded.status}")
    composed_phrase = "reverse squared-adjacent sums"
    composed_examples = [
        (values, list(reversed(independent_square_plus_next(values))))
        for values, _outputs in composition_training[composition_phrases[0]]]
    seeded_composed = composition_model.teach(composed_phrase, composed_examples)
    if seeded_composed.status != "no_fit":
        raise SystemExit(
            f"composed target unexpectedly fit before primitive learning: "
            f"{seeded_composed.status}")
    composition_result = composition_model.learn_best_primitive_proposal(
        max_pending_rechecks=8)
    if (composition_result is None
            or composition_result["descriptor"].get("expression")
                != "(+ (* x x) y)"
            or set(composition_result["learned_phrases"])
                != set(composition_phrases)
            or composed_phrase not in composition_result["rechecked_phrases"]
            or composed_phrase not in composition_result["newly_learned_phrases"]):
        raise SystemExit(
            f"validated primitive did not unlock the pending composed task: "
            f"{composition_result}")
    generated_labels = composition_result["mechanical_disambiguation_probes"]
    if (not generated_labels
            or any(probe["source"]
                   != "contrastive_probe_labeled_by_validated_primitive"
                   for probes in generated_labels.values() for probe in probes)
            or any(len(composition_model._examples[phrase])
                   != len(composition_training[phrase])
                   for phrase in composition_phrases)):
        raise SystemExit(
            "mechanically labeled contrastive probes were not separately recorded")
    for inputs, expected_output in composed_examples:
        prediction = composition_model.predict(composed_phrase, inputs)
        if prediction.status != "ok" or prediction.output != expected_output:
            raise SystemExit(
                f"refreshed composed rule failed replay: {prediction}")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "composition-rules.json"
        composition_model.save(path)
        restored_composition = CRMSModel(
            path, max_composition_depth=2, max_workers=1, max_add=1,
            max_scale=3, max_modulus=3, max_rotation=1, max_repeat=2,
            max_position_stride=3)
        stored_artifact = restored_composition.accepted_primitive_artifacts()[0]
        if stored_artifact.get("mechanical_disambiguation_probes") != generated_labels:
            raise SystemExit("mechanical-probe provenance did not survive persistence")

    print("out-of-grammar mechanical supervision: generated 3 independently "
          "labeled phrase clusters; held-out and MDL gates passed; transactional "
          "failure left the model unchanged; accepted run learned all phrases, "
          "recorded distinct mechanical probe labels, refreshed one composed "
          "task, and replayed examples; PASS")


if __name__ == "__main__":
    main()
