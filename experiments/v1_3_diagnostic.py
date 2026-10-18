"""Diagnose retrieval failures in two-step CRMS instructions.

For each trial, measure step 1, step 2 on the gold intermediate, strict path
fidelity, and final output accuracy from ``Session.process``. Comparing the
marginal step-2 rate with its rate conditional on a successful step 1 checks
whether successful first steps select an easier or harder intermediate-state
distribution. The product ``p1 * p2_given_p1`` is the chain rule, not an
independence prediction; ``p1 * p2_marginal`` is the independence baseline.

Run from the project root: ``python3 experiments/v1_3_diagnostic.py``.
"""
import numpy as np

from v1_2_crms import INSTRUCTION_TEMPLATES, Memory, Session, TRANSFORMS, rand_input


def diagnostic(alpha, seed=42, n_trials=200):
    rng = np.random.RandomState(seed)
    memory = Memory(seed=42)
    for operation, templates in INSTRUCTION_TEMPLATES.items():
        if operation == 'add_k':
            continue
        example = [1, 2, 3]
        memory.add_case(templates[int(rng.randint(len(templates)))], example,
                        TRANSFORMS[operation](example), operation, {})

    names = ['reverse', 'sort_asc', 'sort_desc', 'double', 'first', 'last']
    step1_ok = step2_marginal_ok = step2_given_step1_ok = 0
    strict_path_ok = process_ok = rescued_final = 0
    process_matches_direct = 0

    for _ in range(n_trials):
        first, second = rng.choice(names, 2, replace=False)
        values = rand_input(int(rng.randint(3, 5)), rng)
        gold_mid = TRANSFORMS[first](values)
        gold_output = TRANSFORMS[second](gold_mid)
        phrase1 = INSTRUCTION_TEMPLATES[first][0]
        phrase2 = INSTRUCTION_TEMPLATES[second][0]
        session = Session(memory, alpha=alpha)

        predicted_mid = session._predict(phrase1, values)
        first_correct = predicted_mid == gold_mid
        step1_ok += first_correct

        # Measure step 2 on the gold intermediate on every trial, independent
        # of whether retrieval made step 1 correct.
        predicted_gold_step2 = session._predict(phrase2, gold_mid)
        second_correct_on_gold = predicted_gold_step2 == gold_output
        step2_marginal_ok += second_correct_on_gold
        if first_correct:
            step2_given_step1_ok += second_correct_on_gold
            strict_path_ok += second_correct_on_gold

        predicted_output = session.process(f'{phrase1}, then {phrase2}', values)
        final_correct = predicted_output == gold_output
        process_ok += final_correct
        rescued_final += final_correct and not first_correct

        # Check that process uses the same retrieval/application sequence as
        # explicitly applying the two parsed parts.
        direct_mid = session._predict(phrase1, values)
        direct_output = (None if direct_mid is None
                         else session._predict(phrase2, direct_mid))
        process_matches_direct += predicted_output == direct_output

    p1 = step1_ok / n_trials
    p2_marginal = step2_marginal_ok / n_trials
    p2_given_p1 = step2_given_step1_ok / step1_ok if step1_ok else 0.0
    return {
        'p1': p1,
        'p2_marginal': p2_marginal,
        'p2_given_p1': p2_given_p1,
        'independence_baseline': p1 * p2_marginal,
        'chain_rule_path': p1 * p2_given_p1,
        'strict_path': strict_path_ok / n_trials,
        'process': process_ok / n_trials,
        'rescued_final': rescued_final / n_trials,
        'process_matches_direct': process_matches_direct / n_trials,
        'n': n_trials,
    }


def main():
    print('v1.3 composition diagnostic (200 synthetic trials)')
    print('independence baseline = p1 * marginal p2; chain_rule_path = p1 * p2|p1')
    for alpha in (0.0, 0.5, 1.0):
        result = diagnostic(alpha)
        print(
            f"alpha={alpha:.1f}: p1={result['p1']:.3f}, "
            f"p2_marginal={result['p2_marginal']:.3f}, "
            f"p2|p1={result['p2_given_p1']:.3f}, "
            f"independence={result['independence_baseline']:.3f}, "
            f"strict_path={result['strict_path']:.3f}, "
            f"process_final={result['process']:.3f}, "
            f"rescued_by_final={result['rescued_final']:.3f}, "
            f"process_matches_direct={result['process_matches_direct']:.3f}"
        )


if __name__ == '__main__':
    main()
