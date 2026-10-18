"""CRMS generalization, ambiguity, conflict, and confidence evaluation.

Deterministic synthetic benchmark for the current finite transform library.
It measures where retrieval helps and where the system must abstain; it is
not a general language benchmark.

Run: python v1_7_generalization_eval.py
"""
import math
import numpy as np

from v1_6_training_regime import GroundedSession, TEACHING
from v1_3_crms import Memory, TRANSFORMS, apply_transform


# Separate paraphrases by construction: none of these are teaching phrases.
PARAPHRASES = {
    'reverse': ["put the items in backward order", "list the values from end to start",
                "turn the sequence around", "swap the order from front to back"],
    'sort_asc': ["arrange the numbers in increasing order", "order values low to high",
                 "put the smallest values first", "rank the entries upwards"],
    'sort_desc': ["arrange the numbers in decreasing order", "order values high to low",
                  "put the largest values first", "rank the entries downwards"],
    'double': ["multiply each number by two", "make every value twice as large",
               "replace each entry with two times itself", "scale all numbers by 2"],
    'evens': ["select the even-valued entries", "discard every odd number",
              "return numbers with remainder zero when divided by two",
              "which entries are multiples of two"],
    'odds': ["select the odd-valued entries", "discard every even number",
             "return numbers with remainder one when divided by two",
             "which entries are not multiples of two"],
    'add_k': ["increase every number by three", "add three to each value",
              "move all entries up by 3", "replace each number with itself plus three"],
    'first': ["return the opening value", "keep only the item at the start",
              "select the list's first member", "give me the initial number"],
    'last': ["return the closing value", "keep only the item at the end",
             "select the list's final member", "give me the terminal number"],
}

TEST_INPUTS = [[8, -2, 5, 1], [3, 0, -4, 7, 2], [11, -5, 6]]


def expected(rule, xs):
    return TRANSFORMS[rule](xs, k=3) if rule == 'add_k' else TRANSFORMS[rule](xs)


def fit_session(alpha=0.5):
    s = GroundedSession(Memory(seed=42), alpha=alpha)
    for rule, (phrase, demos) in TEACHING.items():
        s.teach_from_examples(phrase, demos)
    return s


def assess(alpha=0.5):
    s = fit_session(alpha)
    correct = total = covered = covered_correct = 0
    examples = []
    for rule, phrases in PARAPHRASES.items():
        for phrase in phrases:
            for xs in TEST_INPUTS:
                out = s.process(phrase, xs)
                ok = out == expected(rule, xs)
                correct += ok
                total += 1
                covered += out is not None
                covered_correct += out is not None and ok
                ranked = s.memory.retrieve(phrase, k=len(s.memory.cases), alpha=alpha)
                top_score, top = ranked[0]
                second_rule = next((sc for sc, c in ranked[1:]
                                     if (c['transform'], c['params']) !=
                                     (top['transform'], top['params'])), -1.0)
                margin = top_score - second_rule
                # Correct means top retrieved transform and parameters match label.
                label_ok = (top['transform'] == rule and
                            (rule != 'add_k' or top['params'].get('k') == 3))
                examples.append((top_score, label_ok, phrase, rule, margin))
    return {'correct': correct, 'total': total, 'covered': covered,
            'covered_correct': covered_correct, 'examples': examples, 'session': s}


def ece(rows, bins=5):
    """ECE of raw retrieval similarity treated as confidence after [0,1] scaling."""
    total = len(rows)
    value = 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        bucket = [r for r in rows if lo <= (r[0] + 1) / 2 < hi or
                  (i == bins - 1 and (r[0] + 1) / 2 == 1)]
        if bucket:
            conf = sum((r[0] + 1) / 2 for r in bucket) / len(bucket)
            acc = sum(r[1] for r in bucket) / len(bucket)
            value += len(bucket) / total * abs(conf - acc)
    return value


def selective_table(result):
    rows = result['examples']
    print('  score threshold | coverage | accuracy when answered')
    for threshold in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        selected = [r for r in rows if r[0] >= threshold and r[4] >= 0.08]
        acc = sum(r[1] for r in selected) / len(selected) if selected else float('nan')
        print(f'       {threshold:.2f}       | {len(selected)/len(rows):.3f}    | {acc:.3f}')


def ambiguity_and_conflict():
    # Near-overlapping unseen instruction: two competing learned operations.
    s = fit_session()
    probes = ['arrange the values', 'handle these numbers', 'change this list']
    print('\nAmbiguous / underspecified instruction probes:')
    for q in probes:
        out = s.process(q, [4, 1, 3])
        best = s.memory.retrieve(q, k=1, alpha=s.alpha)
        print(f'  {q!r:32s} -> {out!s:12s} top_score={best[0][0]:+.3f}')

    # Existing phrase with demonstrations inconsistent with every known rule.
    phrase = 'flip and sort the values'
    contradictory = [([1, 2, 3], [9, 9]), ([4, 1, 2], [0])]
    status = s.teach_from_examples(phrase, contradictory, min_examples=2)
    print(f'\nConflicting demonstrations: {status["status"]}; '
          f'candidate rules={len(status.get("candidates", []))}; '
          f'phrase stored={any(c["instruction"] == phrase for c in s.memory.cases)}')


def interactive_retry():
    """Model the ask -> demonstrate -> infer -> retry interaction."""
    rng = np.random.RandomState(2026)
    total = learned = answered = correct = 0
    for rule, phrases in PARAPHRASES.items():
        for phrase in phrases:
            # A fresh session prevents examples for one paraphrase leaking to another.
            session = fit_session()
            for _ in range(4):
                xs = list(map(int, rng.randint(-9, 12, size=5)))
                total += 1
                out = session.process(phrase, xs)
                if out is None:
                    # The system requests demonstrations; labels are withheld.
                    demos = TEACHING[rule][1]
                    result = session.teach_from_examples(phrase, demos, min_examples=2)
                    if result['status'] == 'learned':
                        learned += 1
                    out = session.process(phrase, xs)
                if out is not None:
                    answered += 1
                    correct += out == expected(rule, xs)
    return total, learned, answered, correct


def main():
    print('=== CRMS held-out paraphrase evaluation ===')
    for alpha in (0.0, 0.5, 1.0):
        r = assess(alpha)
        n = r['total']
        print(f'alpha={alpha:.1f}: current-gate coverage={r["covered"]/n:.3f}; '
              f'current-gate accuracy={r["covered_correct"]/max(1,r["covered"]):.3f}; '
              f'top-rule ECE={ece(r["examples"]):.3f}')
        if alpha == 0.5:
            selective_table(r)
    ambiguity_and_conflict()
    total, learned, answered, correct = interactive_retry()
    print('\nAsk-for-examples retry loop (fresh session per paraphrase):')
    print(f'  tasks={total}; phrases grounded={learned}/36; '
          f'answered={answered}/{total}; correct={correct}/{total}; '
          f'correct when answered={correct/max(1,answered):.3f}')
    print('\nInterpretation: paraphrases are deliberately held out, but they use a '
          'small synthetic rule set. Similarity scores are not probabilities; '
          'the threshold table is a calibration diagnostic, not a learned guarantee.')


if __name__ == '__main__':
    main()
