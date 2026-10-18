"""Measure one report-only shared subtree grammar over validated expressions."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_expression_discovery import propose_shared_expression_subtrees


def proposal(expression: str, width: int = 3) -> dict:
    return {
        'descriptor': {
            'operation': 'map_window_expression',
            'expression': expression,
            'stride': 1,
            'window_width': width,
        },
        'held_out_valid': True,
        'mdl_gate_passed': True,
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    expressions = [
        proposal('(+ (* (+ x y) (+ x y)) z)'),
        proposal('(- (* (+ x y) (+ x y)) z)'),
    ]
    before = deepcopy(expressions)
    reports = propose_shared_expression_subtrees(expressions)
    matches = [item for item in reports if item['subtree'] == '(+ x y)']
    require(len(matches) == 1, f"shared subtree not reported: {reports}")
    report = matches[0]
    require(report['window_width'] == 3
            and report['supporting_expressions'] == 2
            and report['description_length_gain_bits'] > 0
            and report['baseline_bits'] > report['grammar_and_residual_bits']
            and report['report_only'] is True,
            f"shared subtree MDL accounting is invalid: {report}")
    require(expressions == before, 'report-only analysis mutated its inputs')
    require(not propose_shared_expression_subtrees(
        expressions, minimum_supporting_expressions=3),
        'subtree below its support threshold was reported')

    invalid = deepcopy(expressions)
    invalid[1]['held_out_valid'] = False
    require(not propose_shared_expression_subtrees(invalid),
            'an expression without a valid holdout entered the grammar report')

    mixed_widths = [expressions[0], proposal(
        '(- (* (+ x y) (+ x y)) z)', width=2)]
    require(not propose_shared_expression_subtrees(mixed_widths),
            'incompatible window widths were pooled')

    malformed = [proposal('(+ (* (+ x y) (+ x y)) q)'), expressions[1]]
    require(not propose_shared_expression_subtrees(malformed),
            'malformed expression entered the grammar report')
    print('report-only expression subtree grammar: PASS')
    print(f"shared subtree={report['subtree']}; "
          f"width={report['window_width']}; "
          f"gain={report['description_length_gain_bits']} bits; "
          'held-out gate, support, typing, and immutability: PASS')


if __name__ == '__main__':
    main()
