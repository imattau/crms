"""Bounded, report-only local expression proposals from no-fit records."""
from __future__ import annotations

import re
from typing import Any

from crms_primitive_discovery import (
    _integer_list_bits, _phrase_bits, _positive_bits,
)


OPS = ('+', '-', '*')


def _parse_rendered_tree(text: Any) -> Any:
    """Parse the small prefix notation used by expression proposal artifacts."""
    if not isinstance(text, str):
        raise ValueError('expression must be text')
    tokens = re.findall(r'\(|\)|abs|[+*-]|[xyz]', text)
    if ''.join(tokens).replace('(', '').replace(')', '') != re.sub(
            r'\s+', '', text).replace('(', '').replace(')', ''):
        raise ValueError('expression contains an unsupported token')
    cursor = 0

    def parse() -> Any:
        nonlocal cursor
        if cursor >= len(tokens):
            raise ValueError('expression is incomplete')
        token = tokens[cursor]
        cursor += 1
        if token in {'x', 'y', 'z'}:
            return (token,)
        if token != '(' or cursor >= len(tokens):
            raise ValueError('expression has invalid prefix syntax')
        operator = tokens[cursor]
        cursor += 1
        if operator == 'abs':
            child = parse()
            if cursor >= len(tokens) or tokens[cursor] != ')':
                raise ValueError('absolute expression is not closed')
            cursor += 1
            return ('abs', child)
        if operator not in OPS:
            raise ValueError('expression has an unsupported operator')
        left, right = parse(), parse()
        if cursor >= len(tokens) or tokens[cursor] != ')':
            raise ValueError('binary expression is not closed')
        cursor += 1
        return (operator, left, right)

    tree = parse()
    if cursor != len(tokens):
        raise ValueError('expression contains trailing syntax')
    return tree


def propose_shared_expression_subtrees(
        expression_proposals: list[dict[str, Any]], *,
        minimum_supporting_expressions: int = 2) -> list[dict[str, Any]]:
    """Report single-subtree grammar savings across validated proposals.

    This diagnostic does not create or accept primitives. It considers only
    distinct expressions that already passed their own held-out and MDL gates.
    Window width is part of a subtree's type, so expressions over different
    positional domains are not silently pooled.
    """
    if (type(minimum_supporting_expressions) is not int
            or minimum_supporting_expressions < 2):
        raise ValueError('minimum_supporting_expressions must be at least two')

    expressions: dict[tuple[int, Any], str] = {}
    for proposal in expression_proposals:
        if not isinstance(proposal, dict):
            continue
        descriptor = proposal.get('descriptor')
        if (not isinstance(descriptor, dict)
                or descriptor.get('operation') != 'map_window_expression'
                or proposal.get('held_out_valid') is not True
                or proposal.get('mdl_gate_passed') is not True):
            continue
        width = descriptor.get('window_width', 2)
        if type(width) is not int or width not in (2, 3):
            continue
        try:
            tree = _canonical_tree(_parse_rendered_tree(
                descriptor.get('expression')))
        except ValueError:
            continue
        variables = _tree_variables(tree)
        if (width == 2 and not variables <= {'x', 'y'}
                or width == 3 and not variables <= {'x', 'y', 'z'}):
            continue
        expressions[(width, tree)] = _render(tree)

    def node_bits(node: Any, width: int) -> int:
        if node in {('x',), ('y',), ('z',)}:
            return 1 if width == 2 else 2
        if node[0] == 'abs':
            return 2 + node_bits(node[1], width)
        return 2 + node_bits(node[1], width) + node_bits(node[2], width)

    subtrees: dict[tuple[int, Any], set[Any]] = {}

    def collect(node: Any, width: int, root: Any) -> None:
        if node != root and node[0] in {'abs', *OPS}:
            subtrees.setdefault((width, node), set()).add(root)
        if node[0] == 'abs':
            collect(node[1], width, root)
        elif len(node) == 3:
            collect(node[1], width, root)
            collect(node[2], width, root)

    for width, tree in expressions:
        collect(tree, width, tree)

    reports = []
    for (width, subtree), roots in subtrees.items():
        if len(roots) < minimum_supporting_expressions:
            continue

        def residual_bits(node: Any, root: Any) -> int:
            if node == subtree and node != root:
                return 3  # fixed-width reference to the one shared definition
            if node in {('x',), ('y',), ('z',)}:
                return 1 if width == 2 else 2
            if node[0] == 'abs':
                return 2 + residual_bits(node[1], root)
            return (2 + residual_bits(node[1], root)
                    + residual_bits(node[2], root))

        baseline = sum(node_bits(tree, width) for item_width, tree in expressions
                       if item_width == width)
        compressed = node_bits(subtree, width) + 4  # definition + symbol
        compressed += sum(residual_bits(tree, tree)
                          for item_width, tree in expressions
                          if item_width == width)
        gain = baseline - compressed
        if gain <= 0:
            continue
        reports.append({
            'subtree': _render(subtree),
            'window_width': width,
            'supporting_expressions': len(roots),
            'baseline_bits': baseline,
            'grammar_and_residual_bits': compressed,
            'description_length_gain_bits': gain,
            'source_expressions': sorted(_render(root) for root in roots),
            'report_only': True,
        })
    return sorted(reports, key=lambda item: (
        -item['description_length_gain_bits'], item['window_width'],
        item['subtree'], item['source_expressions']))


def _trees(variables: tuple[str, ...], max_nodes: int = 7):
    by_size = {1: [(variable,) for variable in variables]}
    yield from by_size[1]
    for size in range(2, max_nodes + 1):
        current = []
        for child in by_size.get(size - 1, []):
            if child[0] == 'abs':
                # Absolute value is idempotent.
                continue
            if (len(child) == 3 and child[0] == '-'
                    and repr(child[1]) > repr(child[2])):
                # abs(a-b) and abs(b-a) are exactly the same integer function.
                continue
            current.append(('abs', child))
        for left_size in range(1, size - 1):
            right_size = size - 1 - left_size
            for left in by_size.get(left_size, []):
                for right in by_size.get(right_size, []):
                    for op in OPS:
                        if op in {'+', '*'} and repr(left) > repr(right):
                            continue
                        current.append((op, left, right))
        by_size[size] = current
        yield from current


def _eval(tree: Any, window: list[int]) -> int:
    if tree in {('x',), ('y',), ('z',)}:
        return window[{'x': 0, 'y': 1, 'z': 2}[tree[0]]]
    if tree[0] == 'abs':
        return abs(_eval(tree[1], window))
    a, b = _eval(tree[1], window), _eval(tree[2], window)
    return a + b if tree[0] == '+' else a - b if tree[0] == '-' else a * b


def _render(tree: Any) -> str:
    if tree in {('x',), ('y',), ('z',)}:
        return tree[0]
    if tree[0] == 'abs':
        return f'(abs {_render(tree[1])})'
    return f'({tree[0]} {_render(tree[1])} {_render(tree[2])})'


def _is_existing_step(tree: Any) -> bool:
    return (len(tree) == 3 and tree[0] in OPS
            and tree[1] in {('x',), ('y',)}
            and tree[2] in {('x',), ('y',)})


def _tree_variables(tree: Any) -> set[str]:
    if tree in {('x',), ('y',), ('z',)}:
        return {tree[0]}
    if tree[0] == 'abs':
        return _tree_variables(tree[1])
    return _tree_variables(tree[1]) | _tree_variables(tree[2])


def _canonical_tree(tree: Any) -> Any:
    """Apply a few exact integer identities to collapse duplicate proposals."""
    if tree in {('x',), ('y',), ('z',)}:
        return tree
    if tree[0] == 'abs':
        child = _canonical_tree(tree[1])
        if child[0] == 'abs':
            return child
        if len(child) == 3 and child[0] == '*':
            return _canonical_tree((
                '*', ('abs', child[1]), ('abs', child[2])))
        if len(child) == 3 and child[0] == '-':
            left, right = child[1], child[2]
            if repr(left) > repr(right):
                child = ('-', right, left)
        return ('abs', child)

    operator = tree[0]
    left, right = _canonical_tree(tree[1]), _canonical_tree(tree[2])
    if operator in {'+', '*'} and repr(left) > repr(right):
        left, right = right, left
    if (operator == '*' and left == right and len(left) == 2
            and left[0] == 'abs' and left[1] in {('x',), ('y',), ('z',)}):
        return ('*', left[1], left[1])
    return (operator, left, right)


def _polynomial(tree: Any) -> dict[tuple[str, ...], int] | None:
    if tree in {('x',), ('y',), ('z',)}:
        return {(tree[0],): 1}
    if tree[0] == 'abs':
        return None
    left, right = _polynomial(tree[1]), _polynomial(tree[2])
    if left is None or right is None:
        return None
    if tree[0] in {'+', '-'}:
        result = dict(left)
        sign = 1 if tree[0] == '+' else -1
        for monomial, coefficient in right.items():
            result[monomial] = result.get(monomial, 0) + sign * coefficient
        return {monomial: coefficient for monomial, coefficient in result.items()
                if coefficient}
    result: dict[tuple[str, ...], int] = {}
    for left_monomial, left_coefficient in left.items():
        for right_monomial, right_coefficient in right.items():
            monomial = tuple(sorted(left_monomial + right_monomial))
            result[monomial] = (result.get(monomial, 0)
                                + left_coefficient * right_coefficient)
    return {monomial: coefficient for monomial, coefficient in result.items()
            if coefficient}


def _polynomial_key(polynomial: dict[tuple[str, ...], int]) -> tuple:
    return tuple(sorted(polynomial.items()))


def _absolute_polynomial_key(polynomial: dict[tuple[str, ...], int]) -> tuple:
    ordered = _polynomial_key(polynomial)
    if ordered and ordered[0][1] < 0:
        return tuple((monomial, -coefficient)
                     for monomial, coefficient in ordered)
    return ordered


def _behavior_key(tree: Any) -> tuple:
    canonical = _canonical_tree(tree)
    polynomial = _polynomial(canonical)
    if polynomial is not None:
        return ('polynomial', _polynomial_key(polynomial))
    if canonical[0] == 'abs':
        child_polynomial = _polynomial(canonical[1])
        if child_polynomial is not None:
            return ('absolute-polynomial',
                    _absolute_polynomial_key(child_polynomial))
    return ('tree', canonical)


def _fits(tree: Any, examples: list, width: int) -> bool:
    for inputs, outputs in examples:
        if len(outputs) != len(inputs) - width + 1:
            return False
        if any(_eval(tree, inputs[index:index + width]) != output
               for index, output in enumerate(outputs)):
            return False
    return True


def propose_window_expression_primitives(
        no_fit_records: list[dict[str, Any]], *,
        minimum_supporting_phrases: int = 2,
        integer_code: str = 'gamma') -> list[dict[str, Any]]:
    """Find cross-phrase adjacent-window expressions with holdout and MDL gates.

    This proposal grammar is intentionally small and is independent of the
    existing binary-operation proposal grammar. No model state is changed.
    """
    if integer_code not in {'gamma', 'delta'}:
        raise ValueError("integer_code must be 'gamma' or 'delta'")
    if type(minimum_supporting_phrases) is not int or minimum_supporting_phrases < 2:
        raise ValueError('minimum_supporting_phrases must be at least two')
    parsed = []
    for record in no_fit_records:
        if not isinstance(record, dict):
            continue
        phrase, examples, split = (record.get('instruction'), record.get('examples'),
                                   record.get('proposal_split'))
        if not isinstance(phrase, str) or not isinstance(examples, list) or not isinstance(split, dict):
            continue
        try:
            training = [examples[index] for index in split['training_indices']]
            held_out = [examples[index] for index in split['held_out_indices']]
            if (not training or not held_out
                    or any(len(pair) != 2 for pair in (*training, *held_out))):
                continue
            parsed.append((phrase, training, held_out))
        except (KeyError, IndexError, TypeError):
            continue

    proposals = []
    for width in (2, 3):
        variables = ('x', 'y') if width == 2 else ('x', 'y', 'z')
        seen_trees = set()
        for tree in _trees(variables):
            tree = _canonical_tree(tree)
            behavior = _behavior_key(tree)
            if behavior in seen_trees:
                continue
            seen_trees.add(behavior)
            tree_variables = _tree_variables(tree)
            valid_variables = (
                tree_variables == {'x', 'y'} if width == 2 else
                'z' in tree_variables and len(tree_variables) >= 2)
            if not valid_variables:
                continue
            if width == 2 and _is_existing_step(tree):
                continue
            support = []
            for phrase, training, held_out in parsed:
                if _fits(tree, training, width) and _fits(tree, held_out, width):
                    support.append((phrase, training, held_out))
            if len({item[0] for item in support}) < minimum_supporting_phrases:
                continue

            records = [{'instruction': phrase,
                        'examples': [{'input': x, 'output': y} for x, y in training]}
                       for phrase, training, _ in support]
            literal_bits = _positive_bits(len(records) + 1, integer_code)
            input_records = []
            for record in records:
                phrase = record['instruction']
                examples = record['examples']
                literal_bits += _phrase_bits(phrase, integer_code)
                literal_bits += _positive_bits(len(examples) + 1, integer_code)
                for pair in examples:
                    literal_bits += (_integer_list_bits(pair['input'], integer_code)
                                     + _integer_list_bits(pair['output'], integer_code))
                input_records.append((phrase, [pair['input'] for pair in examples]))

            def tree_bits(node: Any) -> int:
                if node in {('x',), ('y',), ('z',)}:
                    return 1 if width == 2 else 2
                if node[0] == 'abs':
                    return 2 + tree_bits(node[1])
                return 2 + tree_bits(node[1]) + tree_bits(node[2])

            schema_bits = tree_bits(tree) + 16 + (1 if width == 3 else 0)
            candidate_bits = _positive_bits(len(input_records) + 1, integer_code) + schema_bits
            for phrase, inputs in input_records:
                candidate_bits += _phrase_bits(phrase, integer_code)
                candidate_bits += 1  # phrase-to-shared-expression association
                candidate_bits += _positive_bits(len(inputs) + 1, integer_code)
                candidate_bits += sum(_integer_list_bits(values, integer_code) for values in inputs)
            if candidate_bits >= literal_bits:
                continue

            descriptor = {'operation': 'map_window_expression',
                          'expression': _render(tree), 'stride': 1}
            if width == 3:
                descriptor['window_width'] = 3
            proposals.append({
            'descriptor': descriptor,
            'supporting_instructions': sorted(item[0] for item in support),
            'training_examples': sum(len(item[1]) for item in support),
            'held_out_examples': sum(len(item[2]) for item in support),
            'held_out_valid': True,
            'integer_code': integer_code,
            'description_length_bits_baseline': literal_bits,
            'description_length_bits_candidate': candidate_bits,
            'description_length_gain_bits': literal_bits - candidate_bits,
            'mdl_gate_passed': True,
            })
    return proposals
