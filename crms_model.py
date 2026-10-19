"""A self-contained, example-grounded CRMS prototype.

CRMS learns instruction-to-procedure associations from input/output examples.
It can reuse lexical, positional, and parameter patterns induced from grounded
phrases, while abstaining on conflicting evidence. Procedures are one to four
operations from a small explicit library. It does not claim general language
understanding.

Quick start:
    from crms_model import CRMSModel
    model = CRMSModel('memory.json')
    result = model.teach('apply doubling twice', [([1, 2], [4, 8]),
                                                  ([3, -1], [12, -4])])
    print(result)
    print(model.predict('apply doubling twice', [5, 2]))
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import re
import sqlite3
from collections import Counter, OrderedDict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import combinations, product
from pathlib import Path
from typing import Any, Iterable
from crms_text import casefold_nfc, tokens as normalized_tokens


_RULE_DB_APPLICATION_ID = int.from_bytes(b"CRUL", "big")
_RULE_DB_VERSION = 1
_RULE_DB_TABLES = {
    "rule_store_settings", "rule_examples", "rule_procedures",
    "rule_artifacts",
}


def _rule_database_payload(path: Path) -> dict[str, Any]:
    """Reconstruct the JSON-compatible rule memory from normalized SQLite rows."""
    try:
        connection = sqlite3.connect(
            f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            if (connection.execute("PRAGMA application_id").fetchone()[0]
                    != _RULE_DB_APPLICATION_ID
                    or connection.execute("PRAGMA user_version").fetchone()[0]
                    != _RULE_DB_VERSION):
                raise ValueError("unsupported CRMS SQLite rule memory header")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")}
            if tables != _RULE_DB_TABLES:
                raise ValueError("SQLite file is not a CRMS rule memory")
            row = connection.execute(
                "SELECT payload_json FROM rule_store_settings WHERE id=1").fetchone()
            if row is None:
                raise ValueError("SQLite rule memory has no settings row")
            payload = json.loads(row[0])
            if not isinstance(payload, dict):
                raise ValueError("SQLite rule settings are malformed")
            examples: dict[str, list[list[list[int]]]] = {}
            for phrase, _ordinal, inputs, outputs in connection.execute(
                    "SELECT phrase,ordinal,input_json,output_json "
                    "FROM rule_examples ORDER BY phrase,ordinal"):
                examples.setdefault(phrase, []).append(
                    [json.loads(inputs), json.loads(outputs)])
            procedures = {
                phrase: json.loads(steps)
                for phrase, steps in connection.execute(
                    "SELECT phrase,steps_json FROM rule_procedures ORDER BY phrase")
            }
            auxiliary: dict[str, list[Any]] = {}
            for kind, _ordinal, value in connection.execute(
                    "SELECT kind,ordinal,payload_json FROM rule_artifacts "
                    "ORDER BY kind,ordinal"):
                auxiliary.setdefault(kind, []).append(json.loads(value))
            payload["examples"] = examples
            payload["procedures"] = procedures
            for kind in ("accepted_primitives", "accepted_primitive_artifacts",
                         "no_fit_cases"):
                payload[kind] = auxiliary.get(kind, [])
            expected_digest = payload.pop("memory_sha256", None)
            if (not isinstance(expected_digest, str)
                    or hashlib.sha256(json.dumps(
                        payload, ensure_ascii=False,
                        separators=(",", ":")).encode("utf-8")).hexdigest()
                    != expected_digest):
                raise ValueError("SQLite rule memory integrity check failed")
            return payload
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise ValueError("invalid CRMS SQLite rule memory") from error


def _write_rule_database(path: Path, payload: dict[str, Any]) -> None:
    """Replace one SQLite rule-memory snapshot in a single transaction."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
        if tables and (tables != _RULE_DB_TABLES
                       or connection.execute("PRAGMA application_id").fetchone()[0]
                       != _RULE_DB_APPLICATION_ID
                       or connection.execute("PRAGMA user_version").fetchone()[0]
                       != _RULE_DB_VERSION):
            raise ValueError("existing SQLite file is not a CRMS rule memory")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS rule_store_settings ("
                           "id INTEGER PRIMARY KEY CHECK(id=1), "
                           "payload_json TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS rule_examples ("
                           "phrase TEXT NOT NULL, ordinal INTEGER NOT NULL, "
                           "input_json TEXT NOT NULL, output_json TEXT NOT NULL, "
                           "PRIMARY KEY(phrase,ordinal)) WITHOUT ROWID")
        connection.execute("CREATE TABLE IF NOT EXISTS rule_procedures ("
                           "phrase TEXT PRIMARY KEY, steps_json TEXT NOT NULL) "
                           "WITHOUT ROWID")
        connection.execute("CREATE TABLE IF NOT EXISTS rule_artifacts ("
                           "kind TEXT NOT NULL, ordinal INTEGER NOT NULL, "
                           "payload_json TEXT NOT NULL, PRIMARY KEY(kind,ordinal)) "
                           "WITHOUT ROWID")
        connection.execute(f"PRAGMA application_id={_RULE_DB_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version={_RULE_DB_VERSION}")
        connection.execute("BEGIN IMMEDIATE")
        for table in _RULE_DB_TABLES:
            connection.execute(f"DELETE FROM {table}")
        settings = {key: value for key, value in payload.items()
                    if key not in {"examples", "procedures",
                                   "accepted_primitives",
                                   "accepted_primitive_artifacts", "no_fit_cases"}}
        settings["memory_sha256"] = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        connection.execute("INSERT INTO rule_store_settings VALUES (1,?)",
                           (json.dumps(settings, ensure_ascii=False,
                                       separators=(",", ":")),))
        connection.executemany(
            "INSERT INTO rule_examples VALUES (?,?,?,?)",
            ((phrase, ordinal,
              json.dumps(pair[0], ensure_ascii=False, separators=(",", ":")),
              json.dumps(pair[1], ensure_ascii=False, separators=(",", ":")))
             for phrase, examples in payload["examples"].items()
             for ordinal, pair in enumerate(examples)))
        connection.executemany(
            "INSERT INTO rule_procedures VALUES (?,?)",
            ((phrase, json.dumps(steps, ensure_ascii=False,
                                 separators=(",", ":")))
             for phrase, steps in payload["procedures"].items()))
        connection.executemany(
            "INSERT INTO rule_artifacts VALUES (?,?,?)",
            ((kind, ordinal,
              json.dumps(value, ensure_ascii=False, separators=(",", ":")))
             for kind in ("accepted_primitives", "accepted_primitive_artifacts",
                          "no_fit_cases")
             for ordinal, value in enumerate(payload[kind])))
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _reverse(xs: list[int], **_: Any) -> list[int]:
    return list(reversed(xs))


def _identity(xs: list[int], **_: Any) -> list[int]:
    return list(xs)


def _sort_asc(xs: list[int], **_: Any) -> list[int]:
    return sorted(xs)


def _sort_desc(xs: list[int], **_: Any) -> list[int]:
    return sorted(xs, reverse=True)


def _sort_by_magnitude(xs: list[int], **_: Any) -> list[int]:
    """Stable-sort integers from smallest to largest absolute value."""
    return sorted(xs, key=abs)


def _stable_unique(xs: list[int], **_: Any) -> list[int]:
    """Keep the first occurrence of each value, preserving input order."""
    return list(dict.fromkeys(xs))


def _sum_values(xs: list[int], **_: Any) -> list[int]:
    """Reduce an integer list to its sum; the empty sum is zero."""
    return [sum(xs)]


def _cumulative_sum(xs: list[int], **_: Any) -> list[int]:
    """Return the running total at each position; empty input stays empty."""
    total = 0
    result: list[int] = []
    for value in xs:
        total += value
        result.append(total)
    return result


def _adjacent_difference(xs: list[int], **_: Any) -> list[int]:
    """Return each value's difference from the value immediately before it."""
    return [right - left for left, right in zip(xs, xs[1:])]


def _double(xs: list[int], **_: Any) -> list[int]:
    return [2 * x for x in xs]


def _square_values(xs: list[int], **_: Any) -> list[int]:
    """Square every value while preserving list order and length."""
    return [value * value for value in xs]


def _absolute_values(xs: list[int], **_: Any) -> list[int]:
    """Replace each integer with its non-negative magnitude."""
    return [abs(value) for value in xs]


def _duplicate_each(xs: list[int], **_: Any) -> list[int]:
    return [value for value in xs for _copy in range(2)]


def _repeat_each(xs: list[int], k: int, **_: Any) -> list[int]:
    return [value for value in xs for _copy in range(k)]


def _scale(xs: list[int], k: int, **_: Any) -> list[int]:
    return [k * x for x in xs]


def _evens(xs: list[int], **_: Any) -> list[int]:
    return [x for x in xs if x % 2 == 0]


def _odds(xs: list[int], **_: Any) -> list[int]:
    return [x for x in xs if x % 2 != 0]


def _even_positions(xs: list[int], **_: Any) -> list[int]:
    """Keep ordinal positions 2, 4, 6, ... (one-based)."""
    return xs[1::2]


def _odd_positions(xs: list[int], **_: Any) -> list[int]:
    """Keep ordinal positions 1, 3, 5, ... (one-based)."""
    return xs[::2]


def _every_kth_position(xs: list[int], k: int, **_: Any) -> list[int]:
    """Keep positions k, 2k, 3k, ... (one-based)."""
    return xs[k - 1::k]


def _greater_than_first(xs: list[int], **_: Any) -> list[int]:
    return [value for value in xs if xs and value > xs[0]]


def _less_than_first(xs: list[int], **_: Any) -> list[int]:
    return [value for value in xs if xs and value < xs[0]]


def _multiples(xs: list[int], k: int, **_: Any) -> list[int]:
    return [x for x in xs if x % k == 0]


def _add(xs: list[int], k: int, **_: Any) -> list[int]:
    return [x + k for x in xs]


def _add_position(xs: list[int], **_: Any) -> list[int]:
    """Add each value's one-based position to that value."""
    return [value + position for position, value in enumerate(xs, start=1)]


def _add_first(xs: list[int], **_: Any) -> list[int]:
    return [x + xs[0] for x in xs] if xs else []


def _subtract_first(xs: list[int], **_: Any) -> list[int]:
    return [x - xs[0] for x in xs] if xs else []


def _first(xs: list[int], **_: Any) -> list[int]:
    return list(xs[:1])


def _last(xs: list[int], **_: Any) -> list[int]:
    return list(xs[-1:])


def _drop_first(xs: list[int], **_: Any) -> list[int]:
    return list(xs[1:])


def _drop_last(xs: list[int], **_: Any) -> list[int]:
    return list(xs[:-1])


def _rotate_left(xs: list[int], k: int, **_: Any) -> list[int]:
    if not xs:
        return []
    offset = k % len(xs)
    return xs[offset:] + xs[:offset]


_WINDOW_BINARY_OPERATORS = (
    'add', 'subtract', 'multiply', 'maximum', 'minimum', 'modulo')


def _map_window_binary(xs: list[int], operator_id: int, window_width: int,
                       left_offset: int, right_offset: int, stride: int,
                       **_: Any) -> list[int]:
    operations = (lambda left, right: left + right,
                  lambda left, right: left - right,
                  lambda left, right: left * right,
                  max, min, lambda left, right: left % right)
    operation = operations[operator_id]
    last_start = len(xs) - window_width
    return [operation(xs[index + left_offset], xs[index + right_offset])
            for index in range(0, last_start + 1, stride)]


_WINDOW_EXPRESSION_OPERATORS = {'+': 3, '-': 4, '*': 5}
_WINDOW_EXPRESSION_TAG = 1_000_000_000
_WINDOW_EXPRESSION_EXTENDED_TAG = 2_000_000_000


def _expression_has_abs(tree: Any) -> bool:
    if isinstance(tree, str):
        return False
    return (tree[0] == 'abs'
            or _expression_has_abs(tree[1])
            or (len(tree) == 3 and _expression_has_abs(tree[2])))


def _expression_prefix_tokens(tree: Any) -> list[int]:
    if tree == 'x':
        return [0]
    if tree == 'y':
        return [1]
    if tree == 'z':
        return [2]
    if tree[0] == 'abs':
        return [6, *_expression_prefix_tokens(tree[1])]
    operator, left, right = tree
    return [_WINDOW_EXPRESSION_OPERATORS[operator],
            *_expression_prefix_tokens(left), *_expression_prefix_tokens(right)]


def _encode_window_expression(tree: Any) -> int:
    tokens = _expression_prefix_tokens(tree)
    has_abs = _expression_has_abs(tree)
    if has_abs:
        encoded = 0
        for token in tokens:
            encoded = encoded * 7 + token
        return _WINDOW_EXPRESSION_EXTENDED_TAG + 7 ** len(tokens) + encoded
    if 2 not in tokens:
        # Preserve the original compact two-input code for saved memories.
        legacy_ops = {'+': 2, '-': 3, '*': 4}

        def legacy(node: Any) -> list[int]:
            if node == 'x': return [0]
            if node == 'y': return [1]
            return [legacy_ops[node[0]], *legacy(node[1]), *legacy(node[2])]

        tokens = legacy(tree)
        encoded = 0
        for token in tokens:
            encoded = encoded * 5 + token
        return 5 ** len(tokens) + encoded
    encoded = 0
    for token in tokens:
        encoded = encoded * 6 + token
    return _WINDOW_EXPRESSION_TAG + 6 ** len(tokens) + encoded


def _decode_window_expression(code: int) -> Any:
    if type(code) is not int or code < 5:
        raise ValueError('window expression code is invalid')
    extended = code >= _WINDOW_EXPRESSION_EXTENDED_TAG
    modern = code >= _WINDOW_EXPRESSION_TAG and not extended
    radix = 7 if extended else 6 if modern else 5
    local_code = (code - _WINDOW_EXPRESSION_EXTENDED_TAG if extended else
                  code - _WINDOW_EXPRESSION_TAG if modern else code)
    length = 1
    while local_code >= radix ** (length + 1):
        length += 1
    if length > 9:
        raise ValueError('window expression exceeds the bounded grammar')
    encoded = local_code - radix ** length
    tokens = [0] * length
    for index in range(length - 1, -1, -1):
        tokens[index] = encoded % radix
        encoded //= radix
    if encoded:
        raise ValueError('window expression code is outside the bounded grammar')
    reverse_ops = ({3: '+', 4: '-', 5: '*'} if modern or extended
                   else {2: '+', 3: '-', 4: '*'})

    def parse(offset: int) -> tuple[Any, int]:
        if offset >= len(tokens):
            raise ValueError('window expression is truncated')
        token = tokens[offset]
        if token == 0:
            return 'x', offset + 1
        if token == 1:
            return 'y', offset + 1
        if (modern or extended) and token == 2:
            return 'z', offset + 1
        if extended and token == 6:
            child, offset = parse(offset + 1)
            return ('abs', child), offset
        if token not in reverse_ops:
            raise ValueError('window expression has an invalid token')
        left, offset = parse(offset + 1)
        right, offset = parse(offset)
        return (reverse_ops[token], left, right), offset

    tree, consumed = parse(0)
    if consumed != length:
        raise ValueError('window expression contains trailing tokens')
    leaves: list[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, str) and node in {'x', 'y', 'z'}:
            leaves.append(node)
        elif node[0] == 'abs':
            collect(node[1])
        else:
            collect(node[1])
            collect(node[2])

    collect(tree)
    variables = set(leaves)
    width = max({'x': 0, 'y': 1, 'z': 2}[variable] for variable in variables) + 1
    valid_variables = (
        variables == {'x', 'y'} if width == 2 else
        width == 3 and 'z' in variables and len(variables) >= 2)
    if not valid_variables:
        raise ValueError('window expression must use all positions in its window')
    return tree


def _parse_window_expression(text: Any) -> Any:
    if not isinstance(text, str):
        raise ValueError('window expression must be a prefix string')
    tokens = re.findall(r'\(|\)|abs|[+*-]|[xyz]', text)
    if ''.join(tokens).replace('(', '').replace(')', '') != re.sub(r'\s+', '', text).replace('(', '').replace(')', ''):
        raise ValueError('window expression contains unsupported characters')
    cursor = 0

    def parse() -> Any:
        nonlocal cursor
        if cursor >= len(tokens):
            raise ValueError('window expression is truncated')
        token = tokens[cursor]
        cursor += 1
        if token in {'x', 'y', 'z'}:
            return token
        if token != '(' or cursor >= len(tokens):
            raise ValueError('window expression must use prefix notation')
        operator = tokens[cursor]
        cursor += 1
        if operator == 'abs':
            child = parse()
            if cursor >= len(tokens) or tokens[cursor] != ')':
                raise ValueError('window expression parentheses do not balance')
            cursor += 1
            return ('abs', child)
        if operator not in _WINDOW_EXPRESSION_OPERATORS:
            raise ValueError('window expression has an unsupported operator')
        left, right = parse(), parse()
        if cursor >= len(tokens) or tokens[cursor] != ')':
            raise ValueError('window expression parentheses do not balance')
        cursor += 1
        return (operator, left, right)

    tree = parse()
    if cursor != len(tokens):
        raise ValueError('window expression contains trailing tokens')
    code = _encode_window_expression(tree)
    _decode_window_expression(code)  # enforce depth, size, and variable bounds
    return tree


def _window_expression_width(code: int) -> int:
    tree = _decode_window_expression(code)
    variables: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, str) and node in {'x', 'y', 'z'}:
            variables.add(node)
        elif node[0] == 'abs':
            collect(node[1])
        else:
            collect(node[1])
            collect(node[2])

    collect(tree)
    return max({'x': 0, 'y': 1, 'z': 2}[variable]
               for variable in variables) + 1


def _map_window_expression(xs: list[int], expression_code: int,
                           stride: int, window_width: int = 2,
                           **_: Any) -> list[int]:
    tree = _decode_window_expression(expression_code)
    if (type(window_width) is not int
            or window_width != _window_expression_width(expression_code)
            or type(stride) is not int or not 1 <= stride <= 3):
        raise ValueError('window-expression parameters do not match the expression')

    def apply(node: Any, window: list[int]) -> int:
        if node == 'x':
            return window[0]
        if node == 'y':
            return window[1]
        if node == 'z':
            return window[2]
        if node[0] == 'abs':
            return abs(apply(node[1], window))
        operator, left, right = node
        a, b = apply(left, window), apply(right, window)
        return a + b if operator == '+' else a - b if operator == '-' else a * b

    return [apply(tree, xs[index:index + window_width])
            for index in range(0, len(xs) - window_width + 1, stride)]


OPERATIONS = {
    'identity': _identity,
    'reverse': _reverse,
    'sort_ascending': _sort_asc,
    'sort_descending': _sort_desc,
    'sort_by_magnitude': _sort_by_magnitude,
    'stable_unique': _stable_unique,
    'sum_values': _sum_values,
    'cumulative_sum': _cumulative_sum,
    'adjacent_difference': _adjacent_difference,
    'double': _double,
    'square_values': _square_values,
    'absolute_values': _absolute_values,
    'duplicate_each': _duplicate_each,
    'repeat_each_k': _repeat_each,
    'scale_k': _scale,
    'keep_evens': _evens,
    'keep_odds': _odds,
    'keep_even_positions': _even_positions,
    'keep_odd_positions': _odd_positions,
    'keep_every_kth_position': _every_kth_position,
    'keep_greater_than_first': _greater_than_first,
    'keep_less_than_first': _less_than_first,
    'keep_multiples_k': _multiples,
    'add_k': _add,
    'add_position': _add_position,
    'add_first': _add_first,
    'subtract_first': _subtract_first,
    'first': _first,
    'last': _last,
    'drop_first': _drop_first,
    'drop_last': _drop_last,
    'rotate_left_k': _rotate_left,
    'map_window_binary': _map_window_binary,
    'map_window_expression': _map_window_expression,
}


def _numeric_instruction_value(token: str) -> int | None:
    """Parse a cardinal integer or correctly suffixed English ordinal."""
    cardinal = re.fullmatch(r"[+-]?\d+", token)
    if cardinal:
        return int(token)
    ordinal = re.fullmatch(r"(\d+)(st|nd|rd|th)", token)
    if ordinal is None:
        return None
    value = int(ordinal.group(1))
    remainder_100 = value % 100
    expected = ("th" if 11 <= remainder_100 <= 13 else
                {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th"))
    return value if ordinal.group(2) == expected else None

_POSITION_FILTER_OPERATIONS = frozenset({
    'keep_even_positions', 'keep_odd_positions',
    'keep_every_kth_position',
})
_POSITION_AFFINE_OPERATIONS = _POSITION_FILTER_OPERATIONS | frozenset({
    'identity', 'double', 'scale_k', 'add_k',
})
_POSITION_EXTENSIBLE_OPERATIONS = _POSITION_AFFINE_OPERATIONS | frozenset({
    'reverse', 'sort_ascending', 'sort_descending', 'rotate_left_k',
    'stable_unique', 'sum_values',
})
_RELATIONAL_FILTER_OPERATIONS = frozenset({
    'keep_greater_than_first', 'keep_less_than_first',
})
_RELATIONAL_ENDPOINT_OPERATIONS = frozenset({
    'first', 'last', 'drop_first', 'drop_last',
})
_CANDIDATE_CACHE_MAX_INSTRUCTIONS = 16
_CANDIDATE_CACHE_MAX_PROCEDURES = 10_000
def _position_filter_extension_allowed(first: Step, second: Step) -> bool:
    """Gate positional composition to exact summaries or safe syntax fallback."""
    if (first.operation in _POSITION_FILTER_OPERATIONS
            or second.operation in _POSITION_FILTER_OPERATIONS):
        return (first.operation in _POSITION_EXTENSIBLE_OPERATIONS
                and second.operation in _POSITION_EXTENSIBLE_OPERATIONS)
    return True


def _position_sequence_extension_allowed(
    procedure: tuple[Step, ...], next_step: Step,
) -> bool:
    """Gate positional composition to modeled operations or syntax fallback."""
    return (
        not any(step.operation in _POSITION_FILTER_OPERATIONS
                for step in procedure)
        and next_step.operation not in _POSITION_FILTER_OPERATIONS
    ) or all(step.operation in _POSITION_EXTENSIBLE_OPERATIONS
             for step in procedure + (next_step,))


def _sequence_extension_signature(procedure: tuple[Step, ...]) -> tuple[bool, bool, bool]:
    """Return syntactic state that can change which future steps are legal."""
    relational = any(step.operation in {
        'keep_greater_than_first', 'keep_less_than_first'}
        for step in procedure)
    positional = any(step.operation in _POSITION_FILTER_OPERATIONS
                     for step in procedure)
    position_compatible = all(step.operation in _POSITION_EXTENSIBLE_OPERATIONS
                              for step in procedure)
    return relational, positional, position_compatible


def _extend_search_signature(
    signature: tuple[bool, bool, bool], next_step: Step,
) -> tuple[bool, bool, bool] | None:
    """Update bounded composition gates incrementally."""
    has_relational, has_positional, prior_position_compatible = signature
    operation = next_step.operation
    relational = operation in _RELATIONAL_FILTER_OPERATIONS
    positional = operation in _POSITION_FILTER_OPERATIONS
    next_position_compatible = operation in _POSITION_EXTENSIBLE_OPERATIONS
    if has_relational and operation not in _RELATIONAL_ENDPOINT_OPERATIONS:
        return None
    if not ((not has_positional and not positional)
            or (prior_position_compatible and next_position_compatible)):
        return None
    return (has_relational or relational,
            has_positional or positional,
            prior_position_compatible and next_position_compatible)


class _VSAEncoder:
    """Deterministic bipolar hypervector encoder using only the stdlib.

    Token and position vectors are generated from stable hashes, so vectors do
    not depend on insertion order and can be reconstructed after loading
    memory. Binding is bipolar multiplication; bundling is coordinate-wise
    majority with zero-valued ties.
    """

    def __init__(self, dimension: int = 1000, seed: int = 42):
        self.dimension = dimension
        self.seed = seed
        self._vectors: dict[tuple[str, str], tuple[int, ...]] = {}
        self._packed_vectors: dict[tuple[str, str], int] = {}
        self._dimension_mask = (1 << dimension) - 1

    def _random_vector(self, kind: str, key: str) -> tuple[int, ...]:
        identity = f'{self.seed}:{kind}:{key}'.encode('utf-8')
        stable_seed = int.from_bytes(hashlib.sha256(identity).digest()[:8], 'big')
        rng = random.Random(stable_seed)
        return tuple(rng.choice((-1, 1)) for _ in range(self.dimension))

    def _vector(self, kind: str, key: str) -> tuple[int, ...]:
        cache_key = (kind, key)
        if cache_key not in self._vectors:
            self._vectors[cache_key] = self._random_vector(kind, key)
        return self._vectors[cache_key]

    def encode(self, tokens: list[str]) -> tuple[tuple[int, ...], tuple[int, ...]]:
        if not tokens:
            zero = (0,) * self.dimension
            return zero, zero
        token_vectors = [self._vector('token', token) for token in tokens]
        positional = [
            tuple(token_value * position_value
                  for token_value, position_value in zip(
                      token_vector, self._vector('position', str(index))))
            for index, token_vector in enumerate(token_vectors)
        ]
        return self._bundle(positional), self._bundle(token_vectors)

    def _bundle(self, vectors: list[tuple[int, ...]]) -> tuple[int, ...]:
        return tuple(
            1 if total > 0 else -1 if total < 0 else 0
            for total in (sum(vector[index] for vector in vectors)
                          for index in range(self.dimension))
        )

    def similarity(self, left: tuple[int, ...], right: tuple[int, ...]) -> float:
        return sum(a * b for a, b in zip(left, right)) / self.dimension

    @staticmethod
    def _pack(vector: tuple[int, ...]) -> tuple[int, int]:
        """Pack a bipolar vector as (positive bits, nonzero bits)."""
        positive = 0
        nonzero = 0
        for index, value in enumerate(vector):
            if value:
                nonzero |= 1 << index
                if value > 0:
                    positive |= 1 << index
        return positive, nonzero

    def packed_similarity(
        self, left: tuple[int, int], right: tuple[int, int],
    ) -> float:
        """Compute the existing bipolar dot score using packed bit counts."""
        left_positive, left_nonzero = left
        right_positive, right_nonzero = right
        common = left_nonzero & right_nonzero
        same = common & ~(left_positive ^ right_positive)
        different = common & (left_positive ^ right_positive)
        return (same.bit_count() - different.bit_count()) / self.dimension

    def encode_packed(
        self, tokens: list[str],
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        if not tokens:
            return (0, 0), (0, 0)

        token_vectors = [self._vector_packed('token', token) for token in tokens]
        positional = [
            self._dimension_mask ^ (token ^ self._vector_packed('position', str(index)))
            for index, token in enumerate(token_vectors)
        ]
        return self._majority_packed(positional), self._majority_packed(token_vectors)

    def _vector_packed(self, kind: str, key: str) -> int:
        cache_key = (kind, key)
        cached = self._packed_vectors.get(cache_key)
        if cached is None:
            identity = f'{self.seed}:{kind}:{key}'.encode('utf-8')
            stable_seed = int.from_bytes(hashlib.sha256(identity).digest()[:8], 'big')
            rng = random.Random(stable_seed)
            positive = 0
            for index in range(self.dimension):
                if rng.choice((-1, 1)) > 0:
                    positive |= 1 << index
            self._packed_vectors[cache_key] = positive
            return positive
        return cached

    def _majority_packed(self, vectors: list[int]) -> tuple[int, int]:
        """Coordinate-wise bipolar majority using bit-sliced counters."""
        if not vectors:
            return 0, 0
        planes: list[int] = []
        for vector in vectors:
            carry = vector
            index = 0
            while carry:
                if index == len(planes):
                    planes.append(carry)
                    break
                old = planes[index]
                planes[index] = old ^ carry
                carry = old & carry
                index += 1

        threshold = len(vectors) // 2
        equal = self._dimension_mask
        greater = 0
        for index in range(len(planes) - 1, -1, -1):
            plane = planes[index]
            if threshold & (1 << index):
                equal &= plane
            else:
                greater |= equal & plane
                equal &= self._dimension_mask ^ plane

        valid = (self._dimension_mask ^ equal
                 if len(vectors) % 2 == 0 else self._dimension_mask)
        return greater & valid, valid


@dataclass(frozen=True)
class Step:
    operation: str
    parameters: dict[str, int]


def _primitive_step_from_descriptor(descriptor: Any) -> Step:
    if isinstance(descriptor, dict) and descriptor.get('operation') == 'map_window_expression':
        allowed = {'operation', 'expression', 'stride'}
        if set(descriptor) not in (allowed, allowed | {'window_width'}):
            raise ValueError('expression primitive descriptor has an invalid shape')
        tree = _parse_window_expression(descriptor['expression'])
        stride = descriptor['stride']
        if type(stride) is not int or not 1 <= stride <= 3:
            raise ValueError('expression primitive stride is outside the bounded grammar')
        code = _encode_window_expression(tree)
        width = _window_expression_width(code)
        if ('window_width' in descriptor
                and (type(descriptor['window_width']) is not int
                     or descriptor['window_width'] != width)):
            raise ValueError('expression primitive window width does not match its variables')
        parameters = {'expression_code': code, 'stride': stride}
        if width > 2:
            parameters['window_width'] = width
        return Step('map_window_expression', parameters)
    expected = {'operation', 'operator', 'window_width', 'left_offset',
                'right_offset', 'stride'}
    if not isinstance(descriptor, dict) or set(descriptor) != expected:
        raise ValueError('primitive descriptor has an invalid shape')
    if descriptor['operation'] != 'map_window_binary':
        raise ValueError('unsupported proposed primitive operation')
    operator = descriptor['operator']
    if operator not in _WINDOW_BINARY_OPERATORS:
        raise ValueError('primitive descriptor has an unsupported operator')
    width = descriptor['window_width']
    left = descriptor['left_offset']
    right = descriptor['right_offset']
    stride = descriptor['stride']
    if (type(width) is not int or width not in (2, 3)
            or type(left) is not int or not 0 <= left < width
            or type(right) is not int or not 0 <= right < width
            or type(stride) is not int or not 1 <= stride <= width):
        raise ValueError('primitive descriptor is outside the bounded grammar')
    return Step('map_window_binary', {
        'operator_id': _WINDOW_BINARY_OPERATORS.index(operator),
        'window_width': width,
        'left_offset': left,
        'right_offset': right,
        'stride': stride,
    })


def _primitive_descriptor_from_step(step: Step) -> dict[str, Any]:
    if step.operation == 'map_window_expression':
        expected = {'expression_code', 'stride'}
        if set(step.parameters) not in (expected, expected | {'window_width'}):
            raise ValueError('expression primitive has invalid parameters')
        code = step.parameters['expression_code']
        stride = step.parameters['stride']
        width = _window_expression_width(code)
        if (type(stride) is not int or not 1 <= stride <= 3
                or step.parameters.get('window_width', width) != width):
            raise ValueError('expression primitive has invalid parameters')
        tree = _decode_window_expression(code)

        def render(node: Any) -> str:
            if node in {'x', 'y', 'z'}:
                return node
            if node[0] == 'abs':
                return f'(abs {render(node[1])})'
            return f'({node[0]} {render(node[1])} {render(node[2])})'

        descriptor = {'operation': 'map_window_expression',
                      'expression': render(tree), 'stride': stride}
        if width > 2:
            descriptor['window_width'] = width
        return descriptor
    if step.operation != 'map_window_binary':
        raise ValueError('step is not an accepted window primitive')
    operator_id = step.parameters.get('operator_id')
    if type(operator_id) is not int or not 0 <= operator_id < len(_WINDOW_BINARY_OPERATORS):
        raise ValueError('window primitive has an invalid operator id')
    return {
        'operation': 'map_window_binary',
        'operator': _WINDOW_BINARY_OPERATORS[operator_id],
        'window_width': step.parameters['window_width'],
        'left_offset': step.parameters['left_offset'],
        'right_offset': step.parameters['right_offset'],
        'stride': step.parameters['stride'],
    }


@dataclass
class LearnResult:
    status: str
    instruction: str
    examples_used: int
    candidate_count: int
    procedure: list[dict[str, Any]] | None = None
    request: str | None = None
    message: str | None = None
    contrastive_input: list[int] | None = None
    candidate_outputs: list[list[int]] | None = None
    candidate_procedures: list[list[dict[str, Any]]] | None = None
    evidence_phrases: list[str] | None = None
    proposed_procedures: list[list[dict[str, Any]]] | None = None
    search_complete: bool = True
    search_expansions: int = 0


@dataclass
class Prediction:
    status: str
    output: list[int] | None
    instruction: str
    procedure: list[dict[str, Any]] | None = None
    request: str | None = None
    message: str | None = None
    evidence_phrases: list[str] | None = None
    matched_tokens: list[str] | None = None
    matched_bigrams: list[str] | None = None
    matched_templates: list[str] | None = None
    retrieval_score: float | None = None
    retrieval_margin: float | None = None
    contrastive_input: list[int] | None = None
    candidate_outputs: list[list[int]] | None = None
    language_gaps: dict[str, list[str]] | None = None
    retrieval_evidence: list[dict[str, Any]] | None = None
    candidate_routes: list[dict[str, Any]] | None = None


def _step_space(max_add: int, max_scale: int, max_modulus: int,
                max_rotation: int, max_repeat: int,
                max_position_stride: int,
                enable_position_arithmetic: bool = False) -> list[Step]:
    base = [Step(name, {}) for name in OPERATIONS
            if name not in ('add_k', 'scale_k', 'keep_multiples_k',
                            'rotate_left_k', 'repeat_each_k',
                            'keep_every_kth_position',
                            'duplicate_each', 'map_window_binary',
                            'map_window_expression')
            and (enable_position_arithmetic or name != 'add_position')]
    base.extend(Step('add_k', {'k': k})
                for k in range(-max_add, max_add + 1) if k)
    base.extend(Step('scale_k', {'k': k})
                for k in (*range(-max_scale, 1), *range(3, max_scale + 1)))
    base.extend(Step('keep_multiples_k', {'k': k})
                for k in range(3, max_modulus + 1))
    base.extend(Step('rotate_left_k', {'k': k})
                for k in range(-max_rotation, max_rotation + 1) if k)
    base.extend(Step('repeat_each_k', {'k': k})
                for k in range(2, max_repeat + 1))
    base.extend(Step('keep_every_kth_position', {'k': k})
                for k in range(3, max_position_stride + 1))
    return base


@lru_cache(maxsize=65_536)
def _list_length_can_reach(source: int, target: int, steps_left: int,
                           max_repeat: int, can_sum: bool = False) -> bool:
    """Conservatively test whether remaining list operations can reach a length.

    Filters are over-approximated as being able to retain any subset size, so
    this may keep impossible programs but cannot discard a valid one. Length
    preserving operations are ignored; endpoint selection and deletion can
    shrink lists, duplication/repetition can increase length, and sum reduces
    any list to one value (including empty input to ``[0]``).
    """
    if (source < 0 or target < 0 or steps_left < 0 or max_repeat < 2):
        return False
    if can_sum and steps_left > 0:
        # Summing first reaches a singleton even from the empty input. Model
        # the suffix with the existing exact-length over-approximation; using
        # a broad power bound here needlessly keeps most composed states alive.
        if _list_length_can_reach(1, target, steps_left - 1,
                                  max_repeat, can_sum=False):
            return True
    if source == target:
        return True
    if steps_left == 0:
        return False
    if target <= source:
        return True
    if source == 0:
        return False

    products = {1}
    for repeat_count in range(1, steps_left + 1):
        products = {product * factor for product in products
                    for factor in range(2, max_repeat + 1)}
        for multiplier in products:
            maximum = source * multiplier
            # With an operation remaining after repetition, a filter can
            # conservatively retain any target count up to this maximum.
            if repeat_count < steps_left and target <= maximum:
                return True
            # If all remaining operations repeat, the full input length must
            # be multiplied exactly; an initial filter would need another
            # operation and is therefore included only when one remains.
            if target % multiplier == 0:
                retained = target // multiplier
                if (1 <= retained <= source
                        and (retained == source or repeat_count < steps_left)):
                    return True
    return False


def _apply_step(step: Step, values: list[int]) -> list[int]:
    return OPERATIONS[step.operation](list(values), **step.parameters)


def _apply_procedure(procedure: Iterable[Step], values: list[int]) -> list[int]:
    result = list(values)
    for step in procedure:
        result = _apply_step(step, result)
    return result


def _procedure_dict(procedure: Iterable[Step]) -> list[dict[str, Any]]:
    return [asdict(step) for step in procedure]


def _proposal_split_indices(examples: list[tuple[list[int], list[int]]]
                            ) -> dict[str, list[int]]:
    """Choose one content-stable holdout without depending on input order."""
    count = len(examples)
    if count < 3:
        return {'training_indices': list(range(count)), 'held_out_indices': []}
    holdout = max(
        range(count),
        key=lambda index: hashlib.sha256(json.dumps(
            examples[index], separators=(',', ':')).encode('utf-8')).digest())
    return {
        'training_indices': [index for index in range(count)
                             if index != holdout],
        'held_out_indices': [holdout],
    }


def _phrase_example_fingerprint(
        phrase: str, examples: Iterable[tuple[list[int], list[int]]]
        ) -> str:
    normalized = sorted(
        ([list(inputs), list(outputs)] for inputs, outputs in examples),
        key=lambda item: json.dumps(item, separators=(',', ':')))
    payload = {'instruction': phrase, 'examples': normalized}
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _primitive_proposal_artifact_id(
        descriptor: dict[str, Any], lineage: list[dict[str, Any]], *,
        minimum_supporting_phrases: int, integer_code: str,
        baseline_bits: int, candidate_bits: int) -> str:
    source_fingerprints = []
    for item in lineage:
        source = {'instruction': item['instruction'],
                  'fingerprint': item['fingerprint']}
        if 'evidence_fingerprint' in item:
            source['evidence_fingerprint'] = item['evidence_fingerprint']
        source_fingerprints.append(source)
    payload = {
        'artifact_version': 1,
        'descriptor': descriptor,
        'source_fingerprints': source_fingerprints,
        'minimum_supporting_phrases': minimum_supporting_phrases,
        'integer_code': integer_code,
        'description_length_bits_baseline': baseline_bits,
        'description_length_bits_candidate': candidate_bits,
        'split_policy': 'sha256-example-v1',
        'validation_policy': 'training-mdl-heldout-v1',
    }
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return 'primitive-proposal-v1-' + digest


def _contrastive_probe(
    procedures: list[tuple[Step, ...]],
) -> tuple[list[int] | None, list[list[int]] | None]:
    """Find a bounded input that splits candidate behaviors as evenly as possible.

    This only proposes a teacher query; it does not assume that the finite
    probe domain proves two procedures equivalent. A found probe is always a
    real separating example because each candidate is executed on that input.
    Probe values include constants and combined modular periods grounded in
    the remaining procedures. The most balanced split is preferred, with
    shorter inputs as a tie-breaker; larger searches are bounded to keep highly
    ambiguous inductions responsive.
    """
    probe_values = {-1, 0, 1}
    interaction_values: set[int] = set()
    for procedure in procedures:
        filter_moduli = []
        for step in procedure:
            if step.operation == 'keep_evens':
                filter_moduli.append(2)
            elif step.operation == 'keep_odds':
                filter_moduli.append(2)
            elif step.operation == 'keep_multiples_k':
                filter_moduli.append(step.parameters['k'])
            parameter = step.parameters.get('k')
            if type(parameter) is not int:
                continue
            probe_values.update((parameter, -parameter,
                                 parameter - 1, parameter + 1,
                                 -parameter - 1, -parameter + 1))
        # Intersecting modular filters repeat over their combined period.
        # Include these values as focused probes instead of adding them
        # to the Cartesian domain below, whose cost grows exponentially.
        for left in range(len(filter_moduli)):
            for right in range(left + 1, len(filter_moduli)):
                interaction_values.add(math.lcm(
                    filter_moduli[left], filter_moduli[right]))
        if len(filter_moduli) > 2:
            interaction_values.add(math.lcm(*filter_moduli))

    ordered_values = tuple(sorted(probe_values, key=lambda value: (abs(value), value)))
    single_values = set(ordered_values)
    for value in interaction_values:
        single_values.update((value, -value, value - 1, value + 1,
                             -value - 1, -value + 1))
    ordered_single_values = tuple(sorted(
        single_values, key=lambda value: (abs(value), value)))

    work_budget = 5_000_000
    work_used = 0
    best_input = None
    best_outputs = None
    best_score = None

    rotation_parameters = [
        abs(step.parameters['k'])
        for procedure in procedures for step in procedure
        if step.operation == 'rotate_left_k'
    ]
    structured_filter_parameters = any(
        step.operation in {
            'keep_evens', 'keep_odds', 'keep_multiples_k',
            'keep_even_positions', 'keep_odd_positions',
            'keep_every_kth_position',
        }
        for procedure in procedures for step in procedure)
    long_probe_reserve = (
        min(work_budget // 2, len(procedures) * 2048)
        if rotation_parameters or structured_filter_parameters else 0)
    short_probe_budget = work_budget - long_probe_reserve

    # Empty input distinguishes procedures whose behavior differs only at
    # the identity/empty-sum boundary (for example last→scale vs
    # last→sum→scale). It is the shortest valid teacher probe.
    for length in range(0, 4):
        domain = ordered_single_values if length == 1 else ordered_values
        for values in product(domain, repeat=length):
            if work_used + len(procedures) > short_probe_budget:
                break
            probe = list(values)
            outputs = [_apply_procedure(procedure, probe) for procedure in procedures]
            work_used += len(procedures)
            counts = Counter(tuple(output) for output in outputs)
            if len(counts) > 1:
                # Minimize collisions, then prefer more output classes and a
                # shorter input. Sorted domains and product() make ties stable.
                score = (-sum(count * count for count in counts.values()),
                         len(counts), -length)
                if best_score is None or score > best_score:
                    best_input = probe
                    best_outputs = outputs
                    best_score = score
                    if len(counts) == len(procedures):
                        return best_input, best_outputs
        if work_used + len(procedures) > short_probe_budget:
            break

    # Short separators that leave most candidates in one output class are
    # technically valid but poor teacher questions. A short probe that sends
    # at least 10% of the version space to another output is useful enough to
    # answer and often preferable to a much longer, marginally more balanced
    # list. Spend the reserved budget on period-covering lists only when the
    # short probe would leave more than 90% of candidates in one class.
    if best_input is not None:
        short_counts = Counter(tuple(output) for output in best_outputs or [])
        dominant_fraction = max(short_counts.values()) / len(procedures)
        if dominant_fraction <= 0.90:
            # Prefer a familiar, positive, duplicate-free list when it retains
            # most of the information in the mathematically best probe. Such
            # inputs make contrastive questions easier to answer and explain
            # without changing what the teacher is being asked to disambiguate.
            readable: dict[tuple[int, ...], list[list[int]]] = {}
            for length in range(3, 9):
                ascending = list(range(1, length + 1))
                candidates = [
                    ascending[offset:] + ascending[:offset]
                    for offset in range(1, length)
                ]
                candidates.append([
                    value for pair in zip(ascending[1::2], ascending[::2])
                    for value in pair
                ] + (ascending[-1:] if length % 2 else []))
                # Also try one adjacent transposition at a time. This creates
                # an ordinary-looking permutation while exposing ordering
                # rules that would agree on a sorted ascending probe.
                for position in range(length - 1):
                    swapped = list(ascending)
                    swapped[position], swapped[position + 1] = (
                        swapped[position + 1], swapped[position])
                    candidates.append(swapped)
                for values in candidates:
                    if (len(set(values)) != length or min(values) < 1
                            or max(values) > 8):
                        continue
                    signature = tuple(values)
                    if signature in readable:
                        continue
                    readable[signature] = [
                        _apply_procedure(procedure, values)
                        for procedure in procedures]
            readable_options = []
            minimum_classes = (4 * len(short_counts) + 4) // 5
            for probe, outputs in readable.items():
                counts = Counter(tuple(output) for output in outputs)
                if (len(counts) < minimum_classes
                        or max(counts.values())
                           > max(2, 2 * max(short_counts.values()))):
                    continue
                score = (-sum(count * count for count in counts.values()),
                         len(counts), -len(probe))
                readable_options.append((score, probe, outputs))
            if readable_options:
                _score, readable_input, readable_outputs = max(
                    readable_options, key=lambda item: (item[0],
                                                         tuple(-value for value in item[1])))
                best_input, best_outputs = list(readable_input), readable_outputs
            return best_input, best_outputs

    # When competing procedures differ by deduplication after a positional
    # selector, ordinary distinct-value probes cannot expose the difference.
    # Construct a list with a repeated value at two known selected positions.
    dedup_position_pairs: set[tuple[int, int]] = set()
    for procedure in procedures:
        for unique_index, step in enumerate(procedure):
            if step.operation != 'stable_unique':
                continue
            for selector in procedure[:unique_index]:
                if selector.operation == 'keep_even_positions':
                    period, offset = 2, 1
                elif selector.operation == 'keep_odd_positions':
                    period, offset = 2, 0
                elif selector.operation == 'keep_every_kth_position':
                    period = selector.parameters['k']
                    offset = period - 1
                else:
                    continue
                if offset + 2 * period <= 512:
                    dedup_position_pairs.add((period, offset))
    for period, offset in sorted(dedup_position_pairs):
        length = offset + period + 1
        probe = list(range(length))
        probe[offset + period] = probe[offset]
        cost = len(procedures) * length
        if work_used + cost > work_budget:
            break
        outputs = [_apply_procedure(procedure, probe) for procedure in procedures]
        work_used += cost
        counts = Counter(tuple(output) for output in outputs)
        if len(counts) > 1:
            score = (-sum(count * count for count in counts.values()),
                     len(counts), -length)
            if best_score is None or score > best_score:
                best_input, best_outputs, best_score = probe, outputs, score
                if len(counts) == len(procedures):
                    return best_input, best_outputs

    if rotation_parameters or structured_filter_parameters:
        # Composed filters can have a survivor period equal to the LCM of all
        # their moduli, not merely the largest individual modulus. Include
        # positional filters as a factor of two each. A rotation may need that
        # many source elements per shifted survivor before offsets stop
        # aliasing.
        long_lengths: set[int] = set()
        for procedure in procedures:
            moduli = []
            positional_period = 1
            rotations = 0
            for step in procedure:
                if step.operation in ('keep_evens', 'keep_odds'):
                    moduli.append(2)
                elif step.operation == 'keep_multiples_k':
                    moduli.append(step.parameters['k'])
                elif step.operation in _POSITION_FILTER_OPERATIONS:
                    positional_period *= 2
                elif step.operation == 'keep_every_kth_position':
                    positional_period *= step.parameters['k']
                elif step.operation == 'rotate_left_k':
                    rotations += abs(step.parameters['k'])
            period = math.lcm(*(moduli or [1]), positional_period)
            required = min(4096, max(16, (rotations + 2) * period))
            long_lengths.update((required, min(4096, required + period)))

        for length in sorted(long_lengths):
            cost = len(procedures) * length
            if work_used + cost > work_budget:
                continue
            probe = list(range(length))
            outputs = [_apply_procedure(procedure, probe)
                       for procedure in procedures]
            work_used += cost
            counts = Counter(tuple(output) for output in outputs)
            if len(counts) > 1:
                score = (-sum(count * count for count in counts.values()),
                         len(counts), -length)
                if best_score is None or score > best_score:
                    best_input, best_outputs, best_score = probe, outputs, score
                    if len(counts) == len(procedures):
                        return best_input, best_outputs

        # Ordered ranges can make most filter candidates return empty. Probe a
        # small deterministic mixed-value sample as well, so combined value
        # and position interactions can produce a more balanced teacher query.
        pool = tuple(sorted(
            set(ordered_single_values) | set(range(-32, 33)),
            key=lambda value: (abs(value), value)))
        rng = random.Random(42)
        seen_probes = set()
        for _ in range(192):
            length = rng.choice((4, 5, 6, 8, 10, 12, 16))
            probe = [rng.choice(pool) for _ in range(length)]
            signature = tuple(probe)
            if signature in seen_probes:
                continue
            seen_probes.add(signature)
            cost = len(procedures) * length
            if work_used + cost > work_budget:
                break
            outputs = [_apply_procedure(procedure, probe)
                       for procedure in procedures]
            work_used += cost
            counts = Counter(tuple(output) for output in outputs)
            if len(counts) > 1:
                score = (-sum(count * count for count in counts.values()),
                         len(counts), -length)
                if best_score is None or score > best_score:
                    best_input, best_outputs, best_score = probe, outputs, score
                    if len(counts) == len(procedures):
                        return best_input, best_outputs

    return best_input, best_outputs


def _procedure_key(procedure: Iterable[Step]) -> tuple:
    key = []
    for step in procedure:
        parameters = step.parameters
        # Operation parameters are usually empty or a single ``k`` value.
        # Their iteration order is already canonical, so sorting them on
        # every semantic-key computation only adds hot-loop overhead. Keep
        # sorting for multi-parameter steps, where insertion order is not a
        # reliable canonical representation.
        parameter_key = (tuple(parameters.items()) if len(parameters) < 2
                         else tuple(sorted(parameters.items())))
        key.append((step.operation, parameter_key))
    return tuple(key)


def _format_candidate_outputs(outputs: list[list[int]], *, max_groups: int = 8) -> str:
    """Render ambiguity compactly while retaining every prediction in results."""
    counts = Counter(tuple(output) for output in outputs)
    if len(counts) <= max_groups:
        rendered = ", ".join(
            f"{list(output)} × {count}" if count > 1 else str(list(output))
            for output, count in sorted(counts.items(), key=lambda item: item[0]))
    else:
        common = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        rendered = ", ".join(
            f"{list(output)} × {count}" if count > 1 else str(list(output))
            for output, count in common[:max_groups])
        rendered += f", … {len(counts) - max_groups} other output types"
    return (f"{len(outputs)} candidate procedures predict {len(counts)} distinct outputs: "
            f"{rendered}.")


def _rotation_fallback_key(procedure: Iterable[Step]) -> tuple:
    """Keep unresolved ordering/repetition interactions syntactically distinct."""
    raw_steps = tuple(procedure)
    # Uniform affine value maps commute with list rotation. Canonicalize each
    # uninterrupted affine/rotation run without moving operations across a
    # filter, selector, or other list-level transform.
    commuted: list[Step] = []
    index = 0
    affine_and_rotation = {'double', 'scale_k', 'add_k', 'rotate_left_k'}
    while index < len(raw_steps):
        if raw_steps[index].operation not in affine_and_rotation:
            commuted.append(raw_steps[index])
            index += 1
            continue
        end = index
        affine_run = []
        rotation = 0
        while (end < len(raw_steps)
               and raw_steps[end].operation in affine_and_rotation):
            step = raw_steps[end]
            if step.operation == 'rotate_left_k':
                rotation += step.parameters['k']
            else:
                affine_run.append(step)
            end += 1
        commuted.extend(affine_run)
        if rotation:
            commuted.append(Step('rotate_left_k', {'k': rotation}))
        index = end

    normalized: list[Step] = []
    seen_filters: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
    for step in commuted:
        if step.operation == 'identity':
            continue
        if step.operation in ('double', 'scale_k', 'add_k'):
            seen_filters.clear()
        if step.operation in ('keep_evens', 'keep_odds', 'keep_multiples_k'):
            signature = (step.operation, tuple(sorted(step.parameters.items())))
            if signature in seen_filters:
                continue
            seen_filters.add(signature)
        if step.operation == 'rotate_left_k' and normalized:
            previous = normalized[-1]
            if previous.operation == 'rotate_left_k':
                combined = previous.parameters['k'] + step.parameters['k']
                normalized.pop()
                if combined:
                    normalized.append(Step('rotate_left_k', {'k': combined}))
                continue
        normalized.append(step)
    return _procedure_key(normalized)


def _relational_fallback_key(procedure: tuple[Step, ...]) -> tuple:
    """Apply proven rotation simplifications before retaining relational syntax."""
    fallback = _rotation_fallback_key(procedure)
    if fallback != _procedure_key(procedure):
        normalized = tuple(Step(operation, dict(parameters))
                           for operation, parameters in fallback)
        if (_normalized_procedure_key(normalized)
                != _normalized_procedure_key(procedure)):
            return _semantic_key(normalized)
    return ('unreduced_relational_filter', fallback)


def _canonical_residues(modulus: int, residues: set[int]) -> tuple[int, tuple[int, ...]]:
    """Reduce a periodic integer set to its smallest equivalent modulus."""
    if not residues:
        return 1, ()
    normalized = {value % modulus for value in residues}
    for candidate in range(1, modulus + 1):
        if modulus % candidate:
            continue
        reduced = {value % candidate for value in normalized}
        if all(((value in normalized) == (value % candidate in reduced))
               for value in range(modulus)):
            return candidate, tuple(sorted(reduced))
    return modulus, tuple(sorted(normalized))


def _square_divisibility_preimage(modulus: int) -> int | None:
    """Return q such that modulus divides x² exactly when q divides x."""
    remaining = abs(modulus)
    if remaining == 0:
        return None
    preimage = 1
    factor = 2
    while factor * factor <= remaining:
        exponent = 0
        while remaining % factor == 0:
            remaining //= factor
            exponent += 1
        if exponent:
            preimage *= factor ** ((exponent + 1) // 2)
        factor = 3 if factor == 2 else factor + 2
    if remaining > 1:
        preimage *= remaining
    return preimage


def _proven_always_empty(procedure: tuple[Step, ...]) -> bool:
    """Prove emptiness with a finite modular over-approximation.

    The relation tracks residues for an arbitrary list value and the current
    first value. Relative operations transform both exactly. Filters project
    to the values that could survive, then permit any survivor to become the
    new first; this forgets ordering and correlations, so it can miss proofs
    but cannot claim emptiness when a real value survives. Large periods fall
    back to syntax.
    """
    supported = {
        "identity", "double", "scale_k", "add_k", "add_first",
        "subtract_first", "duplicate_each", "repeat_each_k",
        "keep_evens", "keep_odds", "keep_multiples_k", "reverse",
        "sort_ascending", "sort_descending", "rotate_left_k", "first", "last",
    }
    if any(step.operation not in supported for step in procedure):
        return False
    moduli = []
    filter_seen = False
    complex_interaction = False
    has_filter = False
    for step in procedure:
        if step.operation in ("keep_evens", "keep_odds"):
            moduli.append(2)
            filter_seen = has_filter = True
        elif step.operation == "keep_multiples_k":
            moduli.append(step.parameters["k"])
            filter_seen = has_filter = True
        elif step.operation in ("add_first", "subtract_first") and filter_seen:
            complex_interaction = True
    if has_filter and any(step.operation in ("first", "last")
                          for step in procedure):
        complex_interaction = True
    if not complex_interaction:
        return False
    if not moduli:
        return False
    period = math.lcm(*moduli)
    if period > 256:
        return False

    # Every pair of residues can occur in a list with a chosen first value and
    # a chosen candidate value. Tuples are (candidate value, current first).
    relation = {(value, first) for value in range(period)
                for first in range(period)}
    for step in procedure:
        operation = step.operation
        if operation == "identity":
            continue
        if operation in ("duplicate_each", "repeat_each_k"):
            continue
        if operation == "double":
            relation = {(2 * value % period, 2 * first % period)
                        for value, first in relation}
        elif operation == "scale_k":
            factor = step.parameters["k"]
            relation = {(factor * value % period, factor * first % period)
                        for value, first in relation}
        elif operation == "add_k":
            offset = step.parameters["k"]
            relation = {((value + offset) % period, (first + offset) % period)
                        for value, first in relation}
        elif operation == "add_first":
            relation = {((value + first) % period, (2 * first) % period)
                        for value, first in relation}
        elif operation == "subtract_first":
            relation = {((value - first) % period, 0)
                        for value, first in relation}
        elif operation in ("keep_evens", "keep_odds", "keep_multiples_k"):
            if operation == "keep_evens":
                modulus, wanted = 2, {0}
            elif operation == "keep_odds":
                modulus, wanted = 2, {1}
            else:
                modulus, wanted = step.parameters["k"], {0}
            survivors = {value for value, _first in relation
                         if value % modulus in wanted}
            if not survivors:
                return True
            # Over-approximate the post-filter list: any surviving value may
            # be its first and any surviving value may be queried later.
            relation = {(value, first) for value in survivors
                        for first in survivors}
        elif operation == "first":
            first_values = {first for _value, first in relation}
            relation = {(value, value) for value in first_values}
        elif operation == "last":
            last_values = {value for value, _first in relation}
            relation = {(value, value) for value in last_values}
        else:  # Reordering preserves values but may change the first element.
            values = {value for value, _first in relation}
            relation = {(value, first) for value in values for first in values}
    return not relation


def _normalize_adjacent_affine_steps(procedure: Iterable[Step]) -> tuple[Step, ...]:
    """Combine contiguous element-wise affine steps without crossing an op."""
    steps = tuple(procedure)
    normalized: list[Step] = []
    index = 0
    affine_operations = {'double', 'scale_k', 'add_k'}
    while index < len(steps):
        step = steps[index]
        if step.operation == 'identity':
            index += 1
            continue
        if step.operation not in affine_operations:
            normalized.append(step)
            index += 1
            continue
        scale, offset = 1, 0
        while (index < len(steps)
               and steps[index].operation in affine_operations):
            affine_step = steps[index]
            if affine_step.operation == 'double':
                factor, addition = 2, 0
            elif affine_step.operation == 'scale_k':
                factor, addition = affine_step.parameters['k'], 0
            else:
                factor, addition = 1, affine_step.parameters['k']
            scale, offset = factor * scale, factor * offset + addition
            index += 1
        if scale == 1:
            if offset:
                normalized.append(Step('add_k', {'k': offset}))
        else:
            normalized.append(Step(
                'double', {}) if scale == 2 else
                Step('scale_k', {'k': scale}))
            if offset:
                normalized.append(Step('add_k', {'k': offset}))
    return tuple(normalized)


def _normalize_commuting_value_maps(procedure: Iterable[Step]) -> tuple[Step, ...]:
    """Move exact element-wise maps right across operations they commute with."""
    steps = list(procedure)
    translation_commuting = {
        'rotate_left_k', 'drop_first', 'drop_last', 'first', 'last',
        'reverse', 'sort_ascending', 'sort_descending', 'stable_unique',
        'keep_even_positions', 'keep_odd_positions', 'duplicate_each',
        'keep_every_kth_position', 'repeat_each_k',
    }
    scale_commuting = (translation_commuting
                       - {'sort_ascending', 'sort_descending'}) | {
        'sum_values', 'cumulative_sum', 'adjacent_difference',
        'add_first', 'subtract_first', 'sort_by_magnitude',
    }
    moved = True
    while moved:
        moved = False
        for index in range(len(steps) - 1):
            operation = steps[index].operation
            if operation == 'add_k':
                can_move = steps[index + 1].operation in translation_commuting
            elif operation == 'double':
                can_move = steps[index + 1].operation in scale_commuting
            elif operation == 'scale_k':
                can_move = (steps[index].parameters.get('k') != 0
                            and steps[index + 1].operation in scale_commuting)
            else:
                can_move = False
            if can_move:
                steps[index], steps[index + 1] = steps[index + 1], steps[index]
                moved = True
    return tuple(steps)


def _normalized_procedure_key(procedure: Iterable[Step]) -> tuple:
    """Compare programs after the shared exact affine-run normalization."""
    return _procedure_key(_normalize_adjacent_affine_steps(
        _normalize_commuting_value_maps(procedure)))


def _semantic_key(procedure: Iterable[Step]) -> tuple:
    """Return an exact canonical key, reusing bounded deterministic results."""
    steps = tuple(procedure)
    return _cached_semantic_key(_procedure_key(steps))


@lru_cache(maxsize=131_072)
def _cached_semantic_key(procedure_key: tuple) -> tuple:
    # Step parameter dictionaries are mutable and therefore cannot be cache
    # keys. The canonical procedure tuple is immutable; reconstructing these
    # tiny records keeps the semantic rules in one implementation.
    procedure = tuple(
        Step(operation, dict(parameters))
        for operation, parameters in procedure_key)
    return _semantic_key_uncached(procedure)


def _semantic_key_uncached(procedure: Iterable[Step]) -> tuple:
    """Canonical behavior for the current integer-list operation set.

    Programs can apply affine value maps, uniform repetition, filters,
    reordering and endpoint/extreme selection. Sequence-wide aggregation,
    prefix accumulation, and neighbor-dependent differences use a conservative
    syntax key until their interactions with other operations have exact
    normal forms.
    The compact state captures those effects exactly for arbitrary finite
    integer lists when rotations do not cross a value filter or endpoint
    selection. Uniform repetition is tracked by its run width and the phase of
    any rotation through those runs. If a rotation/filter interaction creates
    a shape not summarized here, it falls back to a syntax key instead of
    claiming unproved equivalence.
    """
    steps = tuple(procedure)
    if any(step.operation in {'map_window_binary', 'map_window_expression'}
           for step in steps):
        # Accepted window primitives are exact executable transforms, but
        # compositions involving them retain syntax until their laws are
        # independently proved. Identity steps are proven no-ops everywhere
        # and should not create false ambiguity around an accepted primitive.
        compacted = tuple(step for step in steps
                          if step.operation != 'identity')
        return ('window_primitive_syntax', _procedure_key(compacted))
    if (len(steps) == 2 and steps[0].operation == 'sum_values'
            and steps[1].operation == 'keep_odd_positions'):
        # Summation produces one item, which odd-position selection preserves.
        return _semantic_key((steps[0],))
    if (len(steps) == 2 and steps[0].operation == 'sum_values'
            and steps[1].operation in {
                'keep_even_positions', 'keep_every_kth_position'}):
        # These selectors remove the sole one-based position of a singleton.
        return ('always_empty',)
    raw_steps = _normalize_adjacent_affine_steps(
        _normalize_commuting_value_maps(steps))
    # Evenness is exactly divisibility by two. Keep one spelling when a
    # syntax-preserving subsystem (for example nonlinear square handling)
    # cannot use the compact modular-filter state to recognize the alias.
    canonical_modular_steps = tuple(
        Step('keep_evens', {})
        if (step.operation == 'keep_multiples_k'
            and abs(step.parameters['k']) == 2)
        else step
        for step in raw_steps)
    if canonical_modular_steps != raw_steps:
        return _semantic_key(canonical_modular_steps)
    # Adjacent rotations compose by adding their offsets, including when a
    # later positional filter would otherwise force a conservative syntax key.
    rotation_compacted: list[Step] = []
    for step in raw_steps:
        if (step.operation == 'rotate_left_k' and rotation_compacted
                and rotation_compacted[-1].operation == 'rotate_left_k'):
            combined = rotation_compacted.pop().parameters['k'] + step.parameters['k']
            if combined:
                rotation_compacted.append(Step('rotate_left_k', {'k': combined}))
        else:
            rotation_compacted.append(step)
    if tuple(rotation_compacted) != raw_steps:
        return _semantic_key(rotation_compacted)
    # Once selection or summation leaves at most one item, these operations
    # are exact identities. Canonicalize before specialized sort/aggregate
    # syntax fallbacks so equivalent scalar procedures do not remain separate
    # candidates merely because they contain a sequence-wide operator.
    singleton_noops = {
        'first', 'last', 'reverse', 'sort_ascending', 'sort_descending',
        'sort_by_magnitude', 'rotate_left_k', 'stable_unique',
        'keep_odd_positions', 'cumulative_sum', 'identity',
    }
    compacted: list[Step] = []
    at_most_one = False
    sum_guarantees_singleton = False
    singleton_reduction = False
    for step in raw_steps:
        if (step.operation == 'sum_values'
                and sum_guarantees_singleton):
            singleton_reduction = True
            continue
        if at_most_one and step.operation in singleton_noops:
            singleton_reduction = True
            continue
        compacted.append(step)
        if step.operation in {'first', 'last', 'sum_values'}:
            at_most_one = True
        elif step.operation in {'duplicate_each', 'repeat_each_k'}:
            at_most_one = False
        if step.operation == 'sum_values':
            sum_guarantees_singleton = True
        elif step.operation in {'first', 'last'}:
            # Endpoint selection can be empty on empty input.
            sum_guarantees_singleton = False
        elif step.operation in {
                'keep_even_positions', 'keep_every_kth_position',
                'keep_evens', 'keep_odds', 'keep_multiples_k',
                'keep_greater_than_first', 'keep_less_than_first',
                'drop_first', 'drop_last', 'adjacent_difference'}:
            # These operations can preserve at most one item but can also
            # remove the singleton, changing a later empty-sum result.
            sum_guarantees_singleton = False
        elif step.operation in {'duplicate_each', 'repeat_each_k'}:
            sum_guarantees_singleton = False
    if singleton_reduction:
        return _semantic_key(compacted)
    # Summation is invariant under list reordering. Move it left across exact
    # permutations so they become no-ops on its singleton result, just as
    # permutations after a sum already do in the scalar compaction above.
    sum_permutations = {
        'reverse', 'rotate_left_k', 'sort_ascending', 'sort_descending',
        'sort_by_magnitude',
    }
    sum_normalized = list(raw_steps)
    changed = True
    while changed:
        changed = False
        for index in range(1, len(sum_normalized)):
            if (sum_normalized[index].operation == 'sum_values'
                    and sum_normalized[index - 1].operation in sum_permutations):
                sum_normalized[index - 1], sum_normalized[index] = (
                    sum_normalized[index], sum_normalized[index - 1])
                changed = True
    if tuple(sum_normalized) != raw_steps:
        return _semantic_key(sum_normalized)
    # A divisibility filter after a pure scale tests the scaled values. Pull it
    # before the scale using gcd: m | (a*x) iff m/gcd(m,|a|) | x. This also
    # removes parity/multiple filters made redundant by an even or zero scale.
    for index in range(len(raw_steps) - 1):
        value_map, value_filter = raw_steps[index:index + 2]
        if (value_map.operation not in {'double', 'scale_k'}
                or value_filter.operation not in {
                    'keep_evens', 'keep_multiples_k'}):
            continue
        factor = (2 if value_map.operation == 'double'
                  else value_map.parameters['k'])
        modulus = (2 if value_filter.operation == 'keep_evens'
                   else value_filter.parameters['k'])
        if modulus <= 0:
            continue
        preimage_modulus = modulus // math.gcd(modulus, abs(factor))
        if (preimage_modulus != 1
                and any(step.operation in {'add_first', 'subtract_first'}
                        for step in raw_steps)):
            # Input-relative arithmetic has a dedicated affine/filter normal
            # form below; applying a nontrivial preimage rewrite can cycle.
            continue
        rewritten = list(raw_steps)
        if preimage_modulus == 1:
            del rewritten[index + 1]
        else:
            rewritten[index:index + 2] = [
                Step('keep_multiples_k', {'k': preimage_modulus}), value_map]
        return _semantic_key(rewritten)
    if any(step.operation == 'add_position' for step in raw_steps):
        # One-based position arithmetic depends on sequence structure. Until
        # its exact interactions are modeled, preserve the full program.
        return ('position_dependent_syntax', _procedure_key(raw_steps))
    if any(step.operation == 'square_values' for step in raw_steps):
        # Squaring is nonlinear. Keep programs containing it syntactically
        # distinct except for exact list-structure commutations. Finite probes
        # are not enough to merge it with value filters or order changes.
        # Magnitude ordering followed by squaring has the same result as
        # squaring followed by ascending numeric order: x^2 is nonnegative
        # and monotone in |x|, and equal-magnitude ties become equal values.
        for index in range(len(raw_steps) - 1):
            before, after = raw_steps[index:index + 2]
            if (before.operation == 'sort_by_magnitude'
                    and after.operation == 'square_values'):
                rewritten = list(raw_steps)
                rewritten[index:index + 2] = [
                    Step('square_values', {}), Step('sort_ascending', {})]
                return _semantic_key(rewritten)
            if (before.operation == 'square_values'
                    and after.operation == 'sort_by_magnitude'):
                rewritten = list(raw_steps)
                rewritten[index:index + 2] = [
                    Step('square_values', {}), Step('sort_ascending', {})]
                return _semantic_key(rewritten)
        commuting = {
            'reverse', 'rotate_left_k', 'duplicate_each', 'repeat_each_k',
            'keep_even_positions', 'keep_odd_positions', 'keep_evens',
            'keep_odds', 'first', 'last', 'drop_first', 'drop_last',
        }
        normalized = list(raw_steps)
        # A filter before and after squaring constrains the original input by
        # both moduli: m | x and n | x². Replace the pair with the exact LCM
        # of m and the square-divisibility preimage of n.
        for index in range(len(normalized) - 2):
            before, square, after = normalized[index:index + 3]
            if (before.operation == 'keep_multiples_k'
                    and square.operation == 'square_values'
                    and after.operation == 'keep_multiples_k'):
                before_modulus = abs(before.parameters['k'])
                after_preimage = _square_divisibility_preimage(
                    after.parameters['k'])
                if before_modulus > 0 and after_preimage is not None:
                    combined = math.lcm(before_modulus, after_preimage)
                    rewritten = list(normalized)
                    rewritten[index:index + 3] = [
                        Step('keep_multiples_k', {'k': combined}), square]
                    return _semantic_key(rewritten)
        # A divisibility test after squaring has an exact preimage on the
        # original value: p^e divides x² iff p^ceil(e/2) divides x. Move the
        # filter before the square and reduce its modulus to that preimage.
        for index in range(len(normalized) - 1):
            square, value_filter = normalized[index:index + 2]
            if (square.operation == 'square_values'
                    and value_filter.operation == 'keep_multiples_k'):
                preimage = _square_divisibility_preimage(
                    value_filter.parameters['k'])
                if preimage is not None:
                    rewritten = list(normalized)
                    if preimage == 1:
                        rewritten[index:index + 2] = [square]
                    else:
                        rewritten[index:index + 2] = [
                            Step('keep_multiples_k', {'k': preimage}), square]
                    return _semantic_key(rewritten)
        # Squaring discards sign, so adjacent absolute-value operations are
        # exact no-ops on either side of a square. Normalize this before the
        # broader syntax-preserving fallback.
        signless_square: list[Step] = []
        for index, step in enumerate(normalized):
            if (step.operation == 'absolute_values'
                    and ((index > 0
                          and normalized[index - 1].operation == 'square_values')
                         or (index + 1 < len(normalized)
                             and normalized[index + 1].operation == 'square_values'))):
                continue
            if (step.operation == 'scale_k' and step.parameters['k'] == -1
                    and index + 1 < len(normalized)
                    and normalized[index + 1].operation == 'square_values'):
                # (-x)^2 = x^2; the negative scale is redundant only before
                # the square, not after it.
                continue
            signless_square.append(step)
        if len(signless_square) != len(normalized):
            return _semantic_key(signless_square)
        index = 1
        while index < len(normalized):
            previous = normalized[index - 1]
            if (normalized[index].operation == 'square_values'
                    and previous.operation in commuting):
                normalized[index - 1], normalized[index] = (
                    normalized[index], normalized[index - 1])
                index = max(1, index - 1)
            else:
                index += 1
        return ('square_values_syntax', _procedure_key(normalized))
    if any(step.operation == 'sort_by_magnitude' for step in raw_steps):
        # Magnitude ordering has stable tie behavior and does not share the
        # exact ordering laws of numeric ascending/descending sort. Preserve
        # syntax except for identity, idempotence, and proved commutations.
        normalized: list[Step] = []
        for step in raw_steps:
            if step.operation == 'identity':
                continue
            if (step.operation in {'sort_ascending', 'sort_descending'}
                    and normalized
                    and normalized[-1].operation == 'sort_by_magnitude'):
                # A final total numeric sort discards the ordering established
                # by magnitude sort while preserving the same multiset.
                normalized.pop()
            if (step.operation == 'sort_by_magnitude' and normalized
                    and normalized[-1].operation == 'sort_by_magnitude'):
                continue
            normalized.append(step)
        changed = True
        while changed:
            changed = False
            for index in range(len(normalized) - 1):
                left, right = normalized[index:index + 2]
                # Repetition preserves each equal-magnitude tie as a run;
                # stable deduplication preserves tie order. Choose one exact
                # normal order for those commuting pairs.
                if (left.operation == 'sort_by_magnitude'
                        and right.operation in {'duplicate_each', 'repeat_each_k'}):
                    normalized[index], normalized[index + 1] = right, left
                    changed = True
                    break
                if (left.operation == 'sort_by_magnitude'
                        and right.operation == 'stable_unique'):
                    normalized[index], normalized[index + 1] = right, left
                    changed = True
                    break
                # A value-only filter keeps the relative input order of all
                # survivors. Stable magnitude sorting therefore produces
                # the same ordered subsequence whether filtering happens
                # before or after the sort. Filters that inspect positions
                # or the first value are intentionally excluded.
                if (left.operation == 'sort_by_magnitude'
                        and right.operation in {
                            'keep_evens', 'keep_odds', 'keep_multiples_k'}):
                    normalized[index], normalized[index + 1] = right, left
                    changed = True
                    break
            collapsed: list[Step] = []
            for step in normalized:
                if (step.operation == 'sort_by_magnitude' and collapsed
                        and collapsed[-1].operation == 'sort_by_magnitude'):
                    continue
                collapsed.append(step)
            normalized = collapsed
        if not any(step.operation == 'sort_by_magnitude'
                   for step in normalized):
            return _semantic_key(normalized)
        return ('sort_by_magnitude_syntax', _procedure_key(normalized))
    # Magnitude is nonlinear over signed integers. Until the compact summary
    # models its interactions with filters and order-sensitive operations,
    # retain its procedure syntax except for exact pointwise/reordering laws:
    # absolute value is idempotent and commutes with structure-only operators
    # and parity filters, all of which preserve the selected values' mapping.
    # ``keep_every_kth_position`` has the same value-independent selection
    # property, so it commutes with the pointwise absolute-value map as well.
    if any(step.operation == 'absolute_values' for step in raw_steps):
        absolute_commuting = {
            'reverse', 'rotate_left_k', 'duplicate_each', 'repeat_each_k',
            'keep_even_positions', 'keep_odd_positions', 'keep_evens',
            'keep_every_kth_position', 'keep_odds', 'keep_multiples_k',
            'first', 'last',
            'drop_first', 'drop_last',
        }
        normalized = list(raw_steps)
        index = 1
        while index < len(normalized):
            current = normalized[index]
            previous = normalized[index - 1]
            if current.operation == 'absolute_values':
                if previous.operation in absolute_commuting:
                    normalized[index - 1], normalized[index] = current, previous
                    index = max(1, index - 1)
                    continue
                if previous.operation in {'double', 'scale_k'}:
                    factor = (2 if previous.operation == 'double'
                              else previous.parameters['k'])
                    normalized[index - 1:index + 1] = [
                        current,
                        (Step('double', {}) if abs(factor) == 2 else
                         Step('scale_k', {'k': abs(factor)})),
                    ]
                    index = max(1, index - 1)
                    continue
            index += 1
        compacted: list[Step] = []
        for step in normalized:
            if (step.operation == 'absolute_values' and compacted
                    and compacted[-1].operation == 'absolute_values'):
                continue
            if (step.operation == 'rotate_left_k' and compacted
                    and compacted[-1].operation == 'rotate_left_k'):
                combined = compacted.pop().parameters['k'] + step.parameters['k']
                if combined:
                    compacted.append(Step('rotate_left_k', {'k': combined}))
                continue
            compacted.append(step)
        if tuple(compacted) != raw_steps:
            # Re-run the shared normalizer after the exact scale/absolute
            # rewrite so adjacent affine maps collapse to one representation.
            return _semantic_key(compacted)
        return ('unreduced_absolute_values', _procedure_key(compacted))
    # Canonicalize the two exact endpoint deletion aliases before the broader
    # filtered-affine key handles them. Keep composed deletion programs in
    # their existing specialized path.
    if (len(raw_steps) == 1 and raw_steps[0].operation == 'drop_last'):
        return _semantic_key((Step('rotate_left_k', {'k': -1}),
                              Step('drop_first', {})))
    for index in range(len(raw_steps) - 1):
        rotation, deletion = raw_steps[index:index + 2]
        if (rotation.operation == 'rotate_left_k'
                and deletion.operation == 'drop_last'):
            offset = rotation.parameters['k'] - 1
            rewritten = [*raw_steps[:index]]
            if offset:
                rewritten.append(Step('rotate_left_k', {'k': offset}))
            rewritten.append(Step('drop_first', {}))
            rewritten.extend(raw_steps[index + 2:])
            return _semantic_key(rewritten)
    # A uniform translation cancels under adjacent differences, while a
    # uniform scale commutes with them: diff(a*x + b) == a*diff(x).
    affine_operations = {'double', 'scale_k', 'add_k'}
    for difference_index, difference in enumerate(raw_steps):
        if difference.operation != 'adjacent_difference':
            continue
        start = difference_index
        while (start > 0
               and raw_steps[start - 1].operation in affine_operations):
            start -= 1
        if start == difference_index:
            continue
        scale = 1
        for affine_step in raw_steps[start:difference_index]:
            if affine_step.operation == 'double':
                scale *= 2
            elif affine_step.operation == 'scale_k':
                scale *= affine_step.parameters['k']
        rewritten = [*raw_steps[:start], difference]
        if scale != 1:
            rewritten.append(Step(
                'double', {}) if scale == 2 else
                Step('scale_k', {'k': scale}))
        rewritten.extend(raw_steps[difference_index + 1:])
        if _normalized_procedure_key(rewritten) != _procedure_key(raw_steps):
            return _semantic_key(rewritten)
    modular_filters = {'keep_evens', 'keep_odds', 'keep_multiples_k'}
    for repeat_index, repeat_step in enumerate(raw_steps):
        if repeat_step.operation != 'repeat_each_k':
            continue
        filter_end = repeat_index + 1
        while (filter_end < len(raw_steps)
               and raw_steps[filter_end].operation in modular_filters):
            filter_end += 1
        if filter_end == repeat_index + 1 or filter_end + 1 >= len(raw_steps):
            continue
        rotation, relative = raw_steps[filter_end:filter_end + 2]
        if (rotation.operation != 'rotate_left_k'
                or relative.operation not in {
                    'keep_greater_than_first', 'keep_less_than_first'}):
            continue
        copies = repeat_step.parameters['k']
        offset = rotation.parameters['k']
        aligned_offset = (offset // copies) * copies
        rewritten = [*raw_steps[:repeat_index],
                     *raw_steps[repeat_index + 1:filter_end], repeat_step]
        if aligned_offset:
            rewritten.append(Step('rotate_left_k', {'k': aligned_offset}))
        rewritten.extend(raw_steps[filter_end + 1:])
        if _normalized_procedure_key(rewritten) != _procedure_key(raw_steps):
            # Repetition commutes with value-only filters. The strict
            # first-relative filter then discards every copy of the partially
            # rotated boundary run, so only whole-run rotation affects which
            # values survive.
            return _semantic_key(rewritten)
    # Repetition scales a preceding cyclic shift: repeat(rotate(xs)) is the
    # same list as rotating the repeated list by the same number of value runs.
    # Use this exact identity to expose aliases to the relative-filter rewrite
    # below (for example rotate one value then repeat twice vs. repeat then
    # rotate two values).
    for rotation_index in range(len(raw_steps) - 1):
        rotation, repeat_step = raw_steps[rotation_index:rotation_index + 2]
        if (rotation.operation != 'rotate_left_k'
                or repeat_step.operation not in {
                    'duplicate_each', 'repeat_each_k'}):
            continue
        copies = (2 if repeat_step.operation == 'duplicate_each'
                  else repeat_step.parameters['k'])
        shifted = rotation.parameters['k'] * copies
        rewritten = [*raw_steps[:rotation_index], repeat_step]
        if shifted:
            rewritten.append(Step('rotate_left_k', {'k': shifted}))
        rewritten.extend(raw_steps[rotation_index + 2:])
        return _semantic_key(rewritten)
    if any(step.operation in {
            'sum_values', 'cumulative_sum', 'adjacent_difference'}
           for step in raw_steps):
        # Sequence-wide and neighbor-dependent value changes retain syntax
        # until exact interaction laws are established.
        # Still remove identities and operations proved inert while the list
        # has at most one item, to avoid multiplying the search space with
        # syntactic no-ops around an aggregate.
        normalized: list[Step] = []
        at_most_one = False
        singleton_noops = {
            'first', 'last', 'reverse', 'sort_ascending',
            'sort_descending', 'sort_by_magnitude', 'rotate_left_k',
            'stable_unique', 'keep_odd_positions', 'cumulative_sum',
            'identity',
        }
        for step in raw_steps:
            operation = step.operation
            if at_most_one and operation in singleton_noops:
                continue
            normalized.append(step)
            if operation in {'sum_values', 'first', 'last'}:
                at_most_one = True
            elif operation in {'duplicate_each', 'repeat_each_k'}:
                at_most_one = False
        if not any(step.operation in {
                'sum_values', 'cumulative_sum', 'adjacent_difference'}
                   for step in normalized):
            return _semantic_key(normalized)
        return ('sequence_aggregate_syntax', _procedure_key(normalized))
    steps_list: list[Step] = []
    selected = False
    repeated_after_selection = False
    for step in raw_steps:
        if (selected and not repeated_after_selection
                and step.operation in ("first", "last", "reverse",
                                       "sort_ascending", "sort_descending",
                                       "sort_by_magnitude", "rotate_left_k")):
            # A selected value may later be repeated, but every copy is equal;
            # these operations cannot change that singleton's values. Once
            # repetition creates multiple copies, another endpoint selection
            # changes the output length and must remain in the program.
            continue
        if selected and step.operation == "add_first":
            # Once selection has reduced the list to equal values, adding the
            # first value to every item is exactly a doubling operation.
            step = Step("double", {})
        elif selected and step.operation == "subtract_first":
            # Subtracting the first value from equal entries produces zeros.
            step = Step("scale_k", {"k": 0})
        steps_list.append(step)
        if step.operation in ("first", "last"):
            selected = True
            repeated_after_selection = False
        elif selected and step.operation in ("duplicate_each", "repeat_each_k"):
            repeated_after_selection = True
    steps = tuple(step for step in steps_list
                  if step.operation != 'identity')
    relative_positions = [index for index, step in enumerate(steps)
                          if step.operation in {
                              'keep_greater_than_first',
                              'keep_less_than_first'}]
    if any(any(step.operation in {'first', 'last'}
               for step in steps[:relative_index])
           for relative_index in relative_positions):
        # Endpoint selection leaves only copies of one value; element-wise
        # maps, repetition, deletion, and reordering preserve that equality,
        # so a later strict comparison with the first removes every value.
        return ('always_empty',)
    if (any(step.operation == 'stable_unique' for step in steps)
            and _proven_always_empty(steps)):
        # The modular proof treats deduplication as a value-preserving
        # over-approximation; it may miss emptiness, but cannot invent it.
        return ('always_empty',)
    if any(step.operation == 'stable_unique' for step in steps):
        # Stable deduplication commutes with injective pointwise maps, value
        # filters, and sorting. For each input list, these operations either
        # preserve equalities exactly or retain/discard every copy of the same
        # value together. Keep stable_unique before each commuting operation
        # as the canonical order. A zero scale is excluded because it can
        # create duplicates that were absent before the map.
        stable_unique_commuting = {
            'double', 'scale_k', 'add_k', 'add_first', 'subtract_first',
            'keep_evens', 'keep_odds', 'keep_multiples_k',
            'keep_greater_than_first', 'keep_less_than_first',
            'sort_ascending', 'sort_descending',
        }
        for index in range(1, len(steps)):
            operation, unique = steps[index - 1:index + 1]
            if (unique.operation == 'stable_unique'
                    and operation.operation in stable_unique_commuting
                    and not (operation.operation == 'scale_k'
                             and operation.parameters['k'] == 0)):
                rewritten = list(steps)
                rewritten[index - 1:index + 1] = [unique, operation]
                return _semantic_key(rewritten)

        # Keep only identities we can prove from the sequence algebra.
        # Deduplication cannot change the first item that survives an
        # order-preserving map/filter followed by first selection.
        first_compatible = {
            'stable_unique', 'double', 'scale_k', 'add_k', 'add_first',
            'subtract_first', 'keep_evens', 'keep_odds',
            'keep_multiples_k', 'keep_greater_than_first',
            'keep_less_than_first', 'sort_ascending', 'sort_descending',
            'duplicate_each', 'repeat_each_k',
        }
        rewritten: list[Step] = []
        index = 0
        changed = False
        while index < len(steps):
            if steps[index].operation in ('first', 'last'):
                end = index + 1
                while (end < len(steps)
                       and steps[end].operation in ('duplicate_each',
                                                    'repeat_each_k')):
                    end += 1
                if (end > index + 1 and end < len(steps)
                        and steps[end].operation == 'stable_unique'):
                    rewritten.append(steps[index])
                    index = end + 1
                    changed = True
                    continue
            if (index + 2 < len(steps)
                    and steps[index].operation == 'stable_unique'
                    and steps[index + 1].operation == 'reverse'
                    and steps[index + 2].operation == 'last'):
                rewritten.append(Step('first', {}))
                index += 3
                changed = True
                continue
            if steps[index].operation == 'stable_unique':
                first_offset = next((offset for offset, item in
                                     enumerate(steps[index + 1:], 1)
                                     if item.operation == 'first'), None)
                if (first_offset is not None
                        and all(item.operation in first_compatible
                                for item in
                                steps[index + 1:index + first_offset])):
                    # Remove it only if first selection is reached without a
                    # reorder that could make a later duplicate matter.
                    index += 1
                    changed = True
                    continue
            if (index + 2 < len(steps)
                    and steps[index].operation == 'stable_unique'
                    and steps[index + 1].operation == 'rotate_left_k'
                    and steps[index + 1].parameters.get('k') == 1
                    and steps[index + 2].operation == 'last'):
                rewritten.append(Step('first', {}))
                index += 3
                changed = True
                continue
            if (index + 1 < len(steps)
                    and steps[index].operation == 'stable_unique'
                    and steps[index + 1].operation == 'first'):
                rewritten.append(Step('first', {}))
                index += 2
                changed = True
                continue
            if steps[index].operation == 'stable_unique':
                # Deduplication is idempotent, and uniform repetition creates
                # only adjacent equal copies. A following stable_unique
                # therefore erases that repetition exactly.
                if (rewritten
                        and rewritten[-1].operation == 'stable_unique'):
                    index += 1
                    changed = True
                    continue
                if (rewritten
                        and rewritten[-1].operation in {
                            'duplicate_each', 'repeat_each_k'}):
                    rewritten.pop()
                    rewritten.append(steps[index])
                    index += 1
                    changed = True
                    continue
                singleton = False
                for prior in reversed(steps[:index]):
                    if prior.operation in {'duplicate_each', 'repeat_each_k'}:
                        break
                    if prior.operation in {'first', 'last'}:
                        singleton = True
                        break
                if singleton:
                    index += 1
                    changed = True
                    continue
            rewritten.append(steps[index])
            index += 1
        if changed:
            return _semantic_key(rewritten)
        # Deduplication depends on the sequence's order and multiplicities.
        # Until the normal form models that interaction, only merge identical
        # syntax; do not infer equivalence with other programs from samples.
        return ('stable_unique_syntax', _procedure_key(steps))
    relative_positions = [index for index, step in enumerate(steps)
                          if step.operation in {
                              'keep_greater_than_first',
                              'keep_less_than_first'}]
    if len(relative_positions) == 1:
        relative_index = relative_positions[0]
        repeat_index = next((index for index in range(relative_index - 1, -1, -1)
                             if steps[index].operation in {
                                 'duplicate_each', 'repeat_each_k'}), None)
        if repeat_index is not None:
            repeat_step = steps[repeat_index]
            run_width = (2 if repeat_step.operation == 'duplicate_each'
                         else repeat_step.parameters['k'])
            between = steps[repeat_index + 1:relative_index]
            if (any(step.operation == 'rotate_left_k' for step in between)
                    and all(step.operation in {
                        'rotate_left_k', 'double', 'scale_k', 'add_k'
                    } for step in between)):
                rotation = sum(
                    step.parameters['k'] for step in between
                    if step.operation == 'rotate_left_k')
                # A partial rotation only moves copies of the relative
                # filter's first value across the list boundary. The strict
                # comparison removes those copies; retain only the whole-run
                # shift that selects which repeated value is first.
                aligned_rotation = (rotation // run_width) * run_width
                rewritten = list(steps[:repeat_index + 1])
                inserted_rotation = False
                for step in between:
                    if step.operation == 'rotate_left_k':
                        if not inserted_rotation and aligned_rotation:
                            rewritten.append(Step(
                                'rotate_left_k', {'k': aligned_rotation}))
                        inserted_rotation = True
                    else:
                        rewritten.append(step)
                rewritten.extend(steps[relative_index:])
                if _normalized_procedure_key(rewritten) != _procedure_key(steps):
                    return _semantic_key(rewritten)
    # Exact normal form for selecting an extremum from a modularly filtered
    # list. Track affine values through filters and sort direction so equivalent
    # programs such as "sort, filter, select, add" and "sort, filter, add,
    # select" share one key. The restricted operator family keeps the proof
    # exact; unsupported list operations retain their conservative syntax key.
    selector_positions = [index for index, step in enumerate(steps)
                          if step.operation in {'first', 'last'}]
    if len(selector_positions) == 1:
        selector_index = selector_positions[0]
        before, after = steps[:selector_index], steps[selector_index + 1:]
        sort_operations = {'sort_ascending', 'sort_descending'}
        modular_filters = {'keep_evens', 'keep_odds', 'keep_multiples_k'}
        affine_operations = {'double', 'scale_k', 'add_k'}
        if (any(step.operation in sort_operations for step in before)
                and all(step.operation in modular_filters | sort_operations
                        | affine_operations
                        for step in before)
                and all(step.operation in affine_operations for step in after)):
            value_scale, value_offset = 1, 0
            sequence_direction: int | None = None
            predicates: list[tuple[int, int, int, set[int]]] = []
            for step in before:
                operation = step.operation
                if operation in sort_operations:
                    value_direction = 1 if value_scale > 0 else -1
                    sort_direction = (1 if operation == 'sort_ascending'
                                      else -1)
                    sequence_direction = sort_direction * value_direction
                elif operation == 'keep_evens':
                    predicates.append((value_scale, value_offset, 2, {0}))
                elif operation == 'keep_odds':
                    predicates.append((value_scale, value_offset, 2, {1}))
                elif operation == 'keep_multiples_k':
                    predicates.append((value_scale, value_offset,
                                       step.parameters['k'], {0}))
                elif operation == 'double':
                    value_scale, value_offset = (
                        2 * value_scale, 2 * value_offset)
                    if sequence_direction is not None:
                        sequence_direction *= 1
                elif operation == 'scale_k':
                    factor = step.parameters['k']
                    value_scale, value_offset = (
                        factor * value_scale, factor * value_offset)
                elif operation == 'add_k':
                    value_offset += step.parameters['k']
            selector = steps[selector_index].operation
            is_minimum = ((sequence_direction > 0 and selector == 'first')
                          or (sequence_direction < 0 and selector == 'last'))
            if predicates:
                modulus = math.lcm(*(item[2] for item in predicates))
                allowed = {
                    value for value in range(modulus)
                    if all((scale * value + offset) % predicate_modulus in wanted
                           for scale, offset, predicate_modulus, wanted
                           in predicates)
                }
                modulus, residues = _canonical_residues(modulus, allowed)
            else:
                modulus, residues = 1, (0,)
            scale, offset = value_scale, value_offset
            for step in after:
                if step.operation == 'double':
                    scale, offset = 2 * scale, 2 * offset
                elif step.operation == 'scale_k':
                    factor = step.parameters['k']
                    scale, offset = factor * scale, factor * offset
                else:
                    offset += step.parameters['k']
            return ('filtered_extreme_affine',
                    'min' if is_minimum else 'max', modulus, residues,
                    scale, offset)
    deletion_positions = [index for index, step in enumerate(steps)
                          if step.operation in {'drop_first', 'drop_last'}]
    modular_filter_operations = {
        'keep_evens', 'keep_odds', 'keep_multiples_k'
    }
    affine_operations = {'double', 'scale_k', 'add_k'}
    if (len(deletion_positions) == 1
            and all(step.operation in modular_filter_operations | affine_operations
                    | {'drop_first', 'drop_last'} for step in steps)):
        deletion_index = deletion_positions[0]
        before_predicates: list[tuple[int, int, int, set[int]]] = []
        all_predicates: list[tuple[int, int, int, set[int]]] = []
        value_scale, value_offset = 1, 0

        def add_modular_predicate(step: Step) -> None:
            if step.operation == 'keep_evens':
                modulus, wanted = 2, {0}
            elif step.operation == 'keep_odds':
                modulus, wanted = 2, {1}
            else:
                modulus, wanted = step.parameters['k'], {0}
            predicate = (value_scale, value_offset, modulus, wanted)
            all_predicates.append(predicate)
            if index < deletion_index:
                before_predicates.append(predicate)

        for index, step in enumerate(steps):
            operation = step.operation
            if operation == 'drop_first' or operation == 'drop_last':
                continue
            if operation in modular_filter_operations:
                add_modular_predicate(step)
            elif operation == 'double':
                value_scale, value_offset = (
                    2 * value_scale, 2 * value_offset)
            elif operation == 'scale_k':
                factor = step.parameters['k']
                value_scale, value_offset = (
                    factor * value_scale, factor * value_offset)
            else:
                value_offset += step.parameters['k']

        def residue_signature(
            predicates: list[tuple[int, int, int, set[int]]],
        ) -> tuple[int, tuple[int, ...]]:
            if not predicates:
                return 1, (0,)
            period = math.lcm(*(item[2] for item in predicates))
            allowed = {
                value for value in range(period)
                if all((scale * value + offset) % modulus in wanted
                       for scale, offset, modulus, wanted in predicates)
            }
            return _canonical_residues(period, allowed)

        before_modulus, before_residues = residue_signature(before_predicates)
        total_modulus, total_residues = residue_signature(all_predicates)
        if not before_residues or not total_residues:
            return ('always_empty',)
        return ('endpoint_deleted_filtered_affine',
                steps[deletion_index].operation,
                before_modulus, before_residues,
                total_modulus, total_residues,
                value_scale, value_offset)

    if deletion_positions:
        # Preserve endpoint-deletion syntax except for exact repeated-run
        # identities: deleting one copy from a repeated endpoint cannot change
        # which value first/last selects, and a 2-copy singleton remains one.
        rewritten: list[Step] = []
        index = 0
        changed = False
        while index < len(steps):
            if index + 1 < len(steps):
                left, right = steps[index:index + 2]
                if (left.operation == 'rotate_left_k'
                        and right.operation == 'drop_last'):
                    offset = left.parameters['k'] - 1
                    if offset:
                        rewritten.append(Step('rotate_left_k', {'k': offset}))
                    rewritten.append(Step('drop_first', {}))
                    index += 2
                    changed = True
                    continue
            if steps[index].operation == 'drop_last':
                # Canonicalize a last deletion as a right rotation followed by
                # first deletion. This exposes the general rotate/delete law.
                rewritten.extend((Step('rotate_left_k', {'k': -1}),
                                  Step('drop_first', {})))
                index += 1
                changed = True
                continue
            if (index + 2 < len(steps)
                    and steps[index].operation == 'reverse'
                    and steps[index + 1].operation in {'drop_first', 'drop_last'}
                    and steps[index + 2].operation == 'reverse'):
                rewritten.append(Step(
                    'drop_last' if steps[index + 1].operation == 'drop_first'
                    else 'drop_first', {}))
                index += 3
                changed = True
                continue
            if index + 2 < len(steps):
                left, middle, right = steps[index:index + 3]
                left_repeated = (
                    left.operation == 'duplicate_each'
                    or left.operation == 'repeat_each_k'
                    and left.parameters.get('k', 0) >= 2)
                middle_repeated = (
                    middle.operation == 'duplicate_each'
                    or middle.operation == 'repeat_each_k'
                    and middle.parameters.get('k', 0) >= 2)
                two_copies = (
                    middle.operation == 'duplicate_each'
                    or middle.operation == 'repeat_each_k'
                    and middle.parameters.get('k') == 2)
                deletion = right.operation in {'drop_first', 'drop_last'}
                if (left.operation in {'first', 'last'} and middle_repeated
                        and two_copies
                        and deletion):
                    rewritten.append(left)
                    index += 3
                    changed = True
                    continue
                if (left_repeated and middle.operation in {'drop_first', 'drop_last'}
                        and right.operation in {'first', 'last'}):
                    rewritten.append(right)
                    index += 3
                    changed = True
                    continue
            rewritten.append(steps[index])
            index += 1
        if changed:
            return _semantic_key(rewritten)
        return ('endpoint_deletion_syntax', _procedure_key(steps))
    relational_names = {'keep_greater_than_first', 'keep_less_than_first'}
    relational_positions = [index for index, step in enumerate(steps)
                            if step.operation in relational_names]
    if (len(relational_positions) == 1
            and all(step.operation in relational_names | {
                'identity', 'first', 'last', 'duplicate_each',
                'repeat_each_k', 'double', 'scale_k', 'add_k',
                'add_first', 'subtract_first'} for step in steps)):
        relative_position = relational_positions[0]
        before = steps[:relative_position]
        after = steps[relative_position + 1:]
        # Exact normal form for one relative filter surrounded by ordinary
        # affine value maps and uniform repetition. Uniform translations do
        # not affect a comparison with the first value; repetition commutes
        # with both value maps and this stable element-wise filter.
        simple_relative_ops = {
            'double', 'scale_k', 'add_k', 'duplicate_each', 'repeat_each_k'
        }
        if all(step.operation in simple_relative_ops for step in before + after):
            before_scale = 1
            total_scale, total_offset, copies = 1, 0, 1
            relation = steps[relative_position].operation
            for position, step in enumerate(steps):
                operation = step.operation
                if operation == 'double':
                    factor, translation = 2, 0
                elif operation == 'scale_k':
                    factor, translation = step.parameters['k'], 0
                elif operation == 'add_k':
                    factor, translation = 1, step.parameters['k']
                else:
                    factor, translation = 1, 0
                if position < relative_position:
                    before_scale *= factor
                if operation in ('duplicate_each', 'repeat_each_k'):
                    copies *= (2 if operation == 'duplicate_each'
                               else step.parameters['k'])
                else:
                    total_scale = factor * total_scale
                    total_offset = factor * total_offset + translation
            if before_scale == 0:
                return ('always_empty',)
            if before_scale < 0:
                relation = ('keep_less_than_first'
                            if relation == 'keep_greater_than_first'
                            else 'keep_greater_than_first')
            return ('relative_filter_affine', relation, total_scale,
                    total_offset, copies)
        before_allowed = {'identity', 'double', 'scale_k', 'add_k',
                          'add_first', 'subtract_first', 'duplicate_each',
                          'repeat_each_k'}
        after_allowed = {'identity', 'first', 'last', 'duplicate_each',
                         'repeat_each_k'}
        selectors = [step.operation for step in after
                     if step.operation in {'first', 'last'}]
        if (not selectors
                or any(step.operation not in before_allowed for step in before)
                or any(step.operation not in after_allowed for step in after)):
            return _relational_fallback_key(steps)
        # Uniform affine transforms before the filter preserve relative order
        # when their value scale is positive and reverse it when negative.
        # Additive dependence on the first element is a shared translation, so
        # it also preserves pairwise order. Repetition leaves the selected
        # endpoint unchanged. A zero scale makes every value equal and filters
        # the whole list away.
        value_scale, first_weight, offset = 1, 0, 0
        for step in before:
            if step.operation == 'double':
                value_scale *= 2
                first_weight *= 2
                offset *= 2
            elif step.operation == 'scale_k':
                factor = step.parameters['k']
                value_scale *= factor
                first_weight *= factor
                offset *= factor
            elif step.operation == 'add_k':
                offset += step.parameters['k']
            elif step.operation == 'add_first':
                first_weight = value_scale + 2 * first_weight
                offset *= 2
            elif step.operation == 'subtract_first':
                first_weight = -value_scale
                offset = 0
        if value_scale == 0:
            return ('always_empty',)
        relation = steps[relative_position].operation
        if value_scale < 0:
            relation = ('keep_less_than_first'
                        if relation == 'keep_greater_than_first'
                        else 'keep_greater_than_first')
        # Endpoint operations after a strict relative filter have exact
        # semantics: retain the first or last surviving value, if any.
        selector_position = next(
            position for position in range(relative_position + 1, len(steps))
            if steps[position].operation in {'first', 'last'})
        output_copies = 1
        for step in steps[selector_position + 1:]:
            if step.operation == 'duplicate_each':
                output_copies *= 2
            elif step.operation == 'repeat_each_k':
                output_copies *= step.parameters['k']
        return ('relative_filter_endpoint', relation, selectors[0],
                value_scale, first_weight, offset, output_copies)
    positional_filter_ops = _POSITION_FILTER_OPERATIONS
    if any(step.operation in positional_filter_ops for step in steps):
        # The affine subset has an exact normal form: position selectors
        # reduce to one residue class, and value maps apply uniformly to its
        # retained elements. Other interactions keep their syntax.
        if _proven_always_empty(steps):
            return ('always_empty',)
        position_value_ops = _POSITION_AFFINE_OPERATIONS
        if all(step.operation in position_value_ops for step in steps):
            scale, offset = 1, 0
            stride, residue = 1, 0
            for step in steps:
                operation = step.operation
                if operation == 'double':
                    scale, offset = 2 * scale, 2 * offset
                elif operation == 'scale_k':
                    factor = step.parameters['k']
                    scale, offset = factor * scale, factor * offset
                elif operation == 'add_k':
                    offset += step.parameters['k']
                elif operation in positional_filter_ops:
                    # Re-indexing after each selector composes to one residue
                    # class over zero-based input indices. Positional strides
                    # select the last position in each k-sized block; the
                    # parity operations are the k=2 cases.
                    if operation == 'keep_even_positions':
                        period, selected_offset = 2, 1
                    elif operation == 'keep_odd_positions':
                        period, selected_offset = 2, 0
                    else:
                        period = step.parameters['k']
                        selected_offset = period - 1
                    residue += selected_offset * stride
                    stride *= period
            return ('affine_positional_filter', scale, offset, stride, residue)
        # Mixed value, relative, or ordering filters need a richer sequence
        # abstraction. Retain syntax until that interaction is proven.
        return ('positional_filter_syntax', _procedure_key(steps))

    if relational_positions:
        # These predicates depend on the current first value and change that
        # value set after filtering. Until the normal form tracks their
        # relational constraints, preserve syntax instead of merging programs.
        return _relational_fallback_key(steps)
    if _proven_always_empty(steps):
        return ('always_empty',)
    input_relative_operations = {
        'identity', 'double', 'scale_k', 'add_k',
        'add_first', 'subtract_first', 'duplicate_each', 'repeat_each_k',
        'keep_evens', 'keep_odds', 'keep_multiples_k',
    }
    # Exact rewrite for one subtract-first stage surrounded by rotations,
    # uniform scales, and one modular filter. Scales commute with rotations
    # and with subtract-first. A scale after the filter can move before it
    # exactly when it is invertible modulo that filter's modulus.
    affine_filter_operations = {
        'double', 'scale_k', 'rotate_left_k', 'subtract_first',
        'keep_evens', 'keep_odds', 'keep_multiples_k',
    }
    relative_indices = [index for index, step in enumerate(steps)
                        if step.operation == 'subtract_first']
    filter_indices = [index for index, step in enumerate(steps)
                      if step.operation in {
                          'keep_evens', 'keep_odds', 'keep_multiples_k'}]
    if (len(relative_indices) == 1 and len(filter_indices) == 1
            and any(step.operation in {'double', 'scale_k'} for step in steps)
            and all(step.operation in affine_filter_operations
                    for step in steps)):
        relative_index, filter_index = relative_indices[0], filter_indices[0]
        rotations = [step for step in steps
                     if step.operation == 'rotate_left_k']
        before_scales = [step for index, step in enumerate(steps)
                         if step.operation in {'double', 'scale_k'}
                         and index < filter_index]
        after_scales = [step for index, step in enumerate(steps)
                        if step.operation in {'double', 'scale_k'}
                        and index > filter_index]
        if (filter_index > relative_index
                and all(index < relative_index for index, step in enumerate(steps)
                        if step.operation == 'rotate_left_k')):
            def scale_product(scale_steps: list[Step]) -> int:
                result = 1
                for scale_step in scale_steps:
                    result *= (2 if scale_step.operation == 'double'
                               else scale_step.parameters['k'])
                return result

            before_scale = scale_product(before_scales)
            after_scale = scale_product(after_scales)
            filter_step = steps[filter_index]
            if filter_step.operation == 'keep_evens':
                modulus = 2
            elif filter_step.operation == 'keep_odds':
                modulus = 2
            else:
                modulus = filter_step.parameters['k']
            if math.gcd(after_scale, modulus) == 1:
                before_scale *= after_scale
                after_scale = 1
            rewritten = list(rotations) + [steps[relative_index]]
            if before_scale != 1:
                rewritten.append(Step('scale_k', {'k': before_scale}))
            rewritten.append(filter_step)
            if after_scale != 1:
                rewritten.append(Step('scale_k', {'k': after_scale}))
            if _normalized_procedure_key(rewritten) != _procedure_key(steps):
                return _semantic_key(rewritten)

    has_input_relative = any(
        step.operation in ('add_first', 'subtract_first') for step in steps)
    relative_positions = [index for index, step in enumerate(steps)
                          if step.operation in {'add_first', 'subtract_first'}]
    modular_filter_positions = [index for index, step in enumerate(steps)
                                if step.operation in {
                                    'keep_evens', 'keep_odds',
                                    'keep_multiples_k'}]
    if (relative_positions and modular_filter_positions
            and max(modular_filter_positions) < min(relative_positions)
            and all(step.operation in input_relative_operations for step in steps)):
        # Exact affine normal form for value-only filters followed by
        # first-relative arithmetic. The filters select which original values
        # survive; subsequent relative arithmetic is an affine function of a
        # surviving value and the first surviving value. Moving equivalent
        # affine arithmetic around add_first/subtract_first then collapses to
        # the same signature without changing which values pass the prefix.
        prefix_scale, prefix_offset, copies = 1, 0, 1
        predicates: list[tuple[int, int, int, set[int]]] = []
        first_relative = min(relative_positions)
        for step in steps[:first_relative]:
            operation = step.operation
            if operation == 'double':
                prefix_scale, prefix_offset = (
                    2 * prefix_scale, 2 * prefix_offset)
            elif operation == 'scale_k':
                factor = step.parameters['k']
                prefix_scale, prefix_offset = (
                    factor * prefix_scale, factor * prefix_offset)
            elif operation == 'add_k':
                prefix_offset += step.parameters['k']
            elif operation == 'duplicate_each':
                copies *= 2
            elif operation == 'repeat_each_k':
                copies *= step.parameters['k']
            elif operation in modular_filter_operations:
                if operation == 'keep_evens':
                    modulus, wanted = 2, {0}
                elif operation == 'keep_odds':
                    modulus, wanted = 2, {1}
                else:
                    modulus, wanted = step.parameters['k'], {0}
                predicates.append((prefix_scale, prefix_offset,
                                   modulus, wanted))

        scale, first_weight, offset = 1, 0, 0
        for step in steps[first_relative:]:
            operation = step.operation
            if operation == 'double':
                scale, first_weight, offset = (
                    2 * scale, 2 * first_weight, 2 * offset)
            elif operation == 'scale_k':
                factor = step.parameters['k']
                scale, first_weight, offset = (
                    factor * scale, factor * first_weight, factor * offset)
            elif operation == 'add_k':
                offset += step.parameters['k']
            elif operation == 'add_first':
                first_weight = scale + 2 * first_weight
                offset *= 2
            elif operation == 'subtract_first':
                first_weight = -scale
                offset = 0
            elif operation == 'duplicate_each':
                copies *= 2
            elif operation == 'repeat_each_k':
                copies *= step.parameters['k']

        suffix_scale, suffix_first_weight, suffix_offset = (
            scale, first_weight, offset)
        scale = suffix_scale * prefix_scale
        first_weight = suffix_first_weight * prefix_scale
        offset = ((suffix_scale + suffix_first_weight) * prefix_offset
                  + suffix_offset)
        if predicates:
            period = math.lcm(*(item[2] for item in predicates))
            if period <= 24:
                allowed = {
                    value for value in range(period)
                    if all((a * value + b) % modulus in wanted
                           for a, b, modulus, wanted in predicates)
                }
                modulus, residues = _canonical_residues(period, allowed)
                return ('filtered_input_relative_affine', scale,
                        first_weight, offset, copies, modulus, residues)
    # Exact normal form for one add-first surrounded by affine value changes
    # and rotations. Rotation commutes with element-wise affine operations,
    # while add-first depends on the first value at the rotation point. The
    # signature records the output rotation, the anchored input position, and
    # the resulting affine coefficients. This collapses equivalent programs
    # such as translating before add-first versus distributing that
    # translation after it, without equating different anchor positions.
    if (sum(step.operation == 'add_first' for step in steps) == 1
            and all(step.operation in {
                'identity', 'double', 'scale_k', 'add_k',
                'rotate_left_k', 'add_first'
            } for step in steps)):
        relative_index = next(index for index, step in enumerate(steps)
                              if step.operation == 'add_first')

        def affine_rotation(part: tuple[Step, ...]) -> tuple[int, int, int]:
            scale, offset, rotation = 1, 0, 0
            for item in part:
                operation = item.operation
                if operation == 'double':
                    scale, offset = 2 * scale, 2 * offset
                elif operation == 'scale_k':
                    factor = item.parameters['k']
                    scale, offset = factor * scale, factor * offset
                elif operation == 'add_k':
                    offset += item.parameters['k']
                elif operation == 'rotate_left_k':
                    rotation += item.parameters['k']
            return scale, offset, rotation

        before_scale, before_offset, before_rotation = affine_rotation(
            steps[:relative_index])
        after_scale, after_offset, after_rotation = affine_rotation(
            steps[relative_index + 1:])
        return (
            'rotated_add_first_affine',
            before_scale * after_scale,
            before_rotation + after_rotation,
            before_rotation,
            2 * before_offset * after_scale + after_offset,
        )
    endpoint_positions = [index for index, step in enumerate(steps)
                          if step.operation in {'first', 'last'}]
    input_relative_endpoint_ops = {
        'identity', 'double', 'scale_k', 'add_k',
        'add_first', 'subtract_first', 'duplicate_each', 'repeat_each_k',
    }
    if (has_input_relative and len(endpoint_positions) == 1
            and all(step.operation in input_relative_endpoint_ops
                    for step in steps[:endpoint_positions[0]])
            and all(step.operation in {'double', 'scale_k', 'add_k'}
                    for step in steps[endpoint_positions[0] + 1:])):
        endpoint_index = endpoint_positions[0]
        scale, first_weight, offset = 1, 0, 0
        for step in steps[:endpoint_index]:
            operation = step.operation
            if operation == 'double':
                scale, first_weight, offset = (
                    2 * scale, 2 * first_weight, 2 * offset)
            elif operation == 'scale_k':
                factor = step.parameters['k']
                scale, first_weight, offset = (
                    factor * scale, factor * first_weight, factor * offset)
            elif operation == 'add_k':
                offset += step.parameters['k']
            elif operation == 'add_first':
                first_weight = scale + 2 * first_weight
                offset *= 2
            elif operation == 'subtract_first':
                first_weight = -scale
                offset = 0
        selector = steps[endpoint_index].operation
        if selector == 'first':
            scale, first_weight = scale + first_weight, 0
        for step in steps[endpoint_index + 1:]:
            if step.operation == 'double':
                scale, first_weight, offset = (
                    2 * scale, 2 * first_weight, 2 * offset)
            elif step.operation == 'scale_k':
                factor = step.parameters['k']
                scale, first_weight, offset = (
                    factor * scale, factor * first_weight, factor * offset)
            else:
                offset += step.parameters['k']
        return ('input_relative_endpoint_affine', selector,
                scale, first_weight, offset)
    if has_input_relative and all(
            step.operation in input_relative_operations for step in steps):
        # Exact affine form relative to each original value x and the original
        # first value x0: a*x + b*x0 + c. This collapses algebraically
        # equivalent programs such as add-first then subtract-first, including
        # arbitrary surrounding scales and translations.
        scale, first_weight, offset, copies = 1, 0, 0, 1
        filters: list[tuple[int, int, int, int, set[int]]] = []
        filter_seen = False
        relative_after_filter = False
        for step in steps:
            operation = step.operation
            if operation == 'identity':
                continue
            if operation in ('add_first', 'subtract_first') and filter_seen:
                relative_after_filter = True
                break
            if operation == 'duplicate_each':
                copies *= 2
            elif operation == 'repeat_each_k':
                copies *= step.parameters['k']
            elif operation == 'add_k':
                offset += step.parameters['k']
            elif operation == 'add_first':
                first_weight = scale + 2 * first_weight
                offset *= 2
            elif operation == 'subtract_first':
                first_weight = -scale
                offset = 0
            elif operation in ('keep_evens', 'keep_odds',
                               'keep_multiples_k'):
                filter_seen = True
                if operation == 'keep_evens':
                    modulus, wanted = 2, {0}
                elif operation == 'keep_odds':
                    modulus, wanted = 2, {1}
                else:
                    modulus, wanted = step.parameters['k'], {0}
                filters.append((scale, first_weight, offset, modulus, wanted))
            else:
                factor = (2 if operation == 'double'
                          else step.parameters['k'])
                scale *= factor
                first_weight *= factor
                offset *= factor
        if not relative_after_filter:
            if not filters:
                return ('input_relative_affine_repeated', scale, first_weight,
                        offset, copies)
            combined_modulus = math.lcm(*(item[3] for item in filters))
            # Keep canonicalization work bounded for user-configured large
            # moduli. Syntax fallback is conservative and never equates
            # procedures without a proof.
            if combined_modulus <= 24:
                allowed = {
                    (value, first) for value in range(combined_modulus)
                    for first in range(combined_modulus)
                    if all((a * value + b * first + c) % modulus in wanted
                           for a, b, c, modulus, wanted in filters)
                }
                if not allowed:
                    return ('always_empty',)
                reduced_modulus = combined_modulus
                for candidate in range(1, combined_modulus + 1):
                    if combined_modulus % candidate:
                        continue
                    reduced = {(x, first) for x in range(candidate)
                               for first in range(candidate)
                               if (x, first) in allowed}
                    if all(((x, first) in allowed)
                           == ((x % candidate, first % candidate) in reduced)
                           for x in range(combined_modulus)
                           for first in range(combined_modulus)):
                        reduced_modulus = candidate
                        allowed = reduced
                        break
                all_residues = {
                    (x, first) for x in range(reduced_modulus)
                    for first in range(reduced_modulus)
                }
                if allowed == all_residues:
                    # Every possible transformed value/anchor pair passes
                    # these filters, so remove them and route through the
                    # canonical form used by the unfiltered program.
                    return _semantic_key(tuple(
                        step for step in steps
                        if step.operation not in modular_filter_operations))
                return ('input_relative_filtered_affine_repeated', scale,
                        first_weight, offset, copies, reduced_modulus,
                        tuple(sorted(allowed)))
        else:
            # A later relative operation refers to the first surviving item,
            # which is not necessarily the original x0.
            pass

    # When a list-level operation is interleaved with an input-relative rule,
    # retain syntax until the canonicalizer can prove the interaction.
    if any(step.operation in ('add_first', 'subtract_first') for step in steps):
        normalized: list[Step] = []
        for step in steps:
            if step.operation == 'identity':
                continue
            if step.operation == 'subtract_first' and normalized:
                previous = normalized[-1]
                if (previous.operation in ('add_first', 'subtract_first')
                        or previous.operation == 'add_k'):
                    # Uniform translation cancels when subtracting the
                    # transformed first value; the relative subtraction is
                    # also idempotent and absorbs adjacent add-first.
                    normalized.pop()
            elif step.operation == 'add_first' and normalized:
                if normalized[-1].operation == 'subtract_first':
                    # The first value after subtract-first is zero.
                    continue
            normalized.append(step)
        return ('input_relative_syntax', _procedure_key(normalized))
    scale, offset = 1, 0
    copies_per_value = 1
    order = 'original'
    rotation_offset = 0
    rotation_phase = 0
    rotation_interaction = False
    repeat_interaction = False
    eligible_modulus, eligible_residues = 1, {0}
    selected = None
    selected_modulus, selected_residues = 1, {0}

    for step in steps:
        operation = step.operation
        if operation == 'identity':
            pass
        elif operation == 'double':
            scale, offset = 2 * scale, 2 * offset
        elif operation == 'scale_k':
            k = step.parameters['k']
            scale, offset = k * scale, k * offset
        elif operation == 'add_k':
            offset += step.parameters['k']
        elif operation == 'rotate_left_k':
            if selected is None:
                # Keep the rotation in base-value units plus a phase within
                # each value's repeated run. Aligned rotations then canonicalize
                # across repetition (rotate k then repeat == repeat then
                # rotate k times the repetition count); a partial-run phase
                # remains explicit.
                base_shift, rotation_phase = divmod(
                    rotation_phase + step.parameters['k'], copies_per_value)
                rotation_offset += base_shift
        elif operation == 'duplicate_each':
            if selected is not None:
                copies_per_value *= 2
            else:
                if rotation_phase:
                    repeat_interaction = True
                copies_per_value *= 2
        elif operation == 'repeat_each_k':
            if selected is not None:
                copies_per_value *= step.parameters['k']
            else:
                if rotation_phase:
                    repeat_interaction = True
                copies_per_value *= step.parameters['k']
        elif operation in ('keep_evens', 'keep_odds', 'keep_multiples_k'):
            if operation == 'keep_evens':
                filter_modulus, wanted = 2, {0}
            elif operation == 'keep_odds':
                filter_modulus, wanted = 2, {1}
            else:
                filter_modulus, wanted = step.parameters['k'], {0}
            if selected is None:
                old_modulus, old_residues = eligible_modulus, eligible_residues
            else:
                old_modulus, old_residues = selected_modulus, selected_residues
            combined_modulus = math.lcm(old_modulus, filter_modulus)
            combined_residues = {
                value for value in range(combined_modulus)
                if value % old_modulus in old_residues
                and (scale * value + offset) % filter_modulus in wanted
            }
            canonical_modulus, canonical_residues = _canonical_residues(
                combined_modulus, combined_residues)
            if selected is None:
                # Rotation and filtering generally do not commute: a filter
                # after rotation acts on the same values, but its stable
                # subsequence is then cut at a different boundary. A filter
                # that adds no new value constraint is an exact no-op,
                # however, and must not make the key fall back to syntax.
                if ((rotation_offset or rotation_phase)
                        and (canonical_modulus != eligible_modulus
                             or set(canonical_residues) != eligible_residues)):
                    rotation_interaction = True
                eligible_modulus = canonical_modulus
                eligible_residues = set(canonical_residues)
            else:
                selected_modulus = canonical_modulus
                selected_residues = set(canonical_residues)
        elif selected is None and operation == 'reverse':
            order = {
                'original': 'reversed',
                'reversed': 'original',
                'ascending_original': 'descending_original',
                'descending_original': 'ascending_original',
            }[order]
            if rotation_phase:
                rotation_offset = -rotation_offset - 1
                rotation_phase = copies_per_value - rotation_phase
            else:
                rotation_offset = -rotation_offset
        elif selected is None and operation == 'sort_ascending':
            order = 'ascending_original' if scale > 0 else 'descending_original'
            rotation_offset = 0
            rotation_phase = 0
            rotation_interaction = False
        elif selected is None and operation == 'sort_descending':
            order = 'descending_original' if scale > 0 else 'ascending_original'
            rotation_offset = 0
            rotation_phase = 0
            rotation_interaction = False
        elif selected is None and operation in ('first', 'last'):
            take_first = (operation == 'first')
            if rotation_phase and order != 'original':
                rotation_interaction = True
            if (rotation_offset or rotation_phase) and order in ('original', 'reversed'):
                if eligible_modulus != 1 or eligible_residues != {0}:
                    # Selecting an endpoint after filtering and rotating
                    # depends on how many eligible values precede the cut.
                    rotation_interaction = True
                else:
                    if order == 'original':
                        # A partial rotation starts and ends inside the same
                        # repeated run. Both endpoints therefore select the
                        # run's original value at rotation_offset.
                        input_index = (rotation_offset if rotation_phase
                                       else rotation_offset - (0 if take_first else 1))
                    else:
                        input_index = -rotation_offset - (1 if take_first else 0)
                    if input_index == 0:
                        selected = 'first_input'
                    elif input_index == -1:
                        selected = 'last_input'
                    else:
                        selected = ('cyclic_input_index', input_index)
            elif rotation_offset and order in (
                    'ascending_original', 'descending_original'):
                selected = ('cyclic_sorted_rank', order, rotation_offset,
                            operation)
            elif order == 'original':
                selected = 'first_input' if take_first else 'last_input'
            elif order == 'reversed':
                selected = 'last_input' if take_first else 'first_input'
            elif order == 'ascending_original':
                selected = 'minimum' if take_first else 'maximum'
            else:  # descending
                selected = 'maximum' if take_first else 'minimum'
            selected_modulus = eligible_modulus
            selected_residues = set(eligible_residues)
            # Taking an endpoint discards all but one value, so prior uniform
            # repetition no longer changes the output sequence.
            copies_per_value = 1
            rotation_phase = 0
        elif selected is not None and operation in ('first', 'last'):
            # Repeated copies of the selected value still form a longer list;
            # another endpoint operation collapses that list back to one.
            copies_per_value = 1
            rotation_phase = 0
        elif operation in ('reverse', 'sort_ascending', 'sort_descending',
                           'rotate_left_k'):
            # Reordering or selecting an already singleton/empty sequence has
            # no further effect.
            pass
        else:
            raise ValueError(f'operation {operation!r} has no semantic summary')

    if not eligible_residues or (selected is not None and not selected_residues):
        return ('always_empty',)
    if rotation_interaction:
        return ('unreduced_rotation', _rotation_fallback_key(steps))
    if repeat_interaction:
        return ('unreduced_repeat', _rotation_fallback_key(steps))
    if selected is None:
        return ('sequence', scale, offset, copies_per_value, order,
                rotation_offset, rotation_phase, eligible_modulus,
                tuple(sorted(eligible_residues)))
    return ('selected', scale, offset, selected,
            eligible_modulus, tuple(sorted(eligible_residues)),
            selected_modulus, tuple(sorted(selected_residues)),
            copies_per_value)


def _available_cpus() -> int:
    """Return CPUs available to this process, respecting affinity limits."""
    process_count = getattr(os, 'process_cpu_count', None)
    if process_count is not None:
        count = process_count()
        if count:
            return count
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def _search_intermediate_group(task: tuple) -> list[tuple[Step, Step]]:
    """Pickle-safe worker: find second steps matching one intermediate state."""
    states, first_steps, steps, target = task
    matches = []
    for second in steps:
        for first in first_steps:
            if not _position_filter_extension_allowed(first, second):
                continue
            if all(tuple(_apply_step(second, state)) == target[i]
                   for i, state in enumerate(states)):
                matches.append((first, second))
    return matches


class CRMSModel:
    """Conservative case/rule memory for integer-list transformations.

    `teach` accumulates evidence for an exact instruction string. It commits a
    procedure of up to four steps only when exactly one behaviorally distinct candidate
    fits all examples.
    `predict` first uses exact associations, then conservative parameter,
    aligned positional, contrastive categorical-slot, analogical-frame,
    lexical, and learned sequence-composition evidence, followed by a gated
    VSA similarity fallback over grounded phrases. Unresolved or conflicting
    phrases elicit a request for examples rather than an uncalibrated guess.
    """

    FORMAT_VERSION = 1
    NO_FIT_RECORD_LIMIT = 100

    def __init__(self, memory_path: str | Path | None = None,
                 max_composition_depth: int = 2, max_add: int = 10,
                 max_workers: int | None = None,
                 parallel_min_work: int = 30_000,
                 max_scale: int = 5, max_modulus: int = 6,
                 vsa_alpha: float = 0.5, vsa_min_similarity: float = 0.30,
                 vsa_min_margin: float = 0.10, max_rotation: int = 4,
                 max_repeat: int = 4,
                 max_position_stride: int = 6,
                 max_search_expansions: int = 250_000,
                 enable_position_arithmetic: bool = False):
        if max_composition_depth not in (1, 2, 3, 4):
            raise ValueError('max_composition_depth must be 1, 2, 3, or 4')
        if max_add < 1:
            raise ValueError('max_add must be positive')
        if type(max_scale) is not int or max_scale < 3:
            raise ValueError('max_scale must be an integer of at least 3')
        if type(max_modulus) is not int or max_modulus < 3:
            raise ValueError('max_modulus must be an integer of at least 3')
        if type(max_rotation) is not int or max_rotation < 1:
            raise ValueError('max_rotation must be a positive integer')
        if type(max_repeat) is not int or max_repeat < 2:
            raise ValueError('max_repeat must be an integer of at least 2')
        if type(max_position_stride) is not int or max_position_stride < 3:
            raise ValueError('max_position_stride must be an integer of at least 3')
        if type(enable_position_arithmetic) is not bool:
            raise ValueError('enable_position_arithmetic must be a bool')
        if (type(vsa_alpha) not in (int, float)
                or not math.isfinite(vsa_alpha)
                or not 0 <= vsa_alpha <= 1):
            raise ValueError('vsa_alpha must be between 0 and 1')
        if (type(vsa_min_similarity) not in (int, float)
                or not math.isfinite(vsa_min_similarity)
                or not -1 <= vsa_min_similarity <= 1):
            raise ValueError('vsa_min_similarity must be finite and between -1 and 1')
        if (type(vsa_min_margin) not in (int, float)
                or not math.isfinite(vsa_min_margin)
                or not 0 <= vsa_min_margin <= 2):
            raise ValueError('vsa_min_margin must be finite and between 0 and 2')
        if max_workers is not None and max_workers < 1:
            raise ValueError('max_workers must be positive or None')
        if parallel_min_work < 0:
            raise ValueError('parallel_min_work cannot be negative')
        if (type(max_search_expansions) is not int
                or max_search_expansions < 1):
            raise ValueError('max_search_expansions must be a positive integer')
        self.memory_path = Path(memory_path) if memory_path is not None else None
        self.max_composition_depth = max_composition_depth
        self.max_add = max_add
        self.max_scale = max_scale
        self.max_modulus = max_modulus
        self.max_rotation = max_rotation
        self.max_repeat = max_repeat
        self.max_position_stride = max_position_stride
        self.enable_position_arithmetic = enable_position_arithmetic
        self.vsa_alpha = float(vsa_alpha)
        self.vsa_min_similarity = float(vsa_min_similarity)
        self.vsa_min_margin = float(vsa_min_margin)
        self._vsa_encoder = _VSAEncoder()
        self._vsa_phrase_cache: dict[
            str, tuple[tuple[int, int], tuple[int, int]]
        ] = {}
        self._vsa_phrase_tokens: dict[str, tuple[str, ...]] = {}
        self._vsa_phrase_counts: dict[str, Counter[str]] = {}
        self._vsa_phrase_behaviors: dict[str, tuple] = {}
        self._vsa_token_index: dict[str, set[str]] | None = None
        self._composition_connective_cache: dict[
            tuple[str, ...], tuple[tuple[tuple[str, str], ...], tuple[str, ...]]
        ] | None = None
        self._canonical_instruction_index: dict[str, tuple[str, ...]] | None = None
        self._lexical_feature_cache: tuple[dict, dict, dict] | None = None
        self._procedure_scaffold_cache: dict[int, list[dict[str, Any]]] = {}
        self.max_workers = max_workers or _available_cpus()
        self.parallel_min_work = parallel_min_work
        self.max_search_expansions = max_search_expansions
        self._last_search_complete = True
        self._last_search_expansions = 0
        self._steps = _step_space(
            max_add, max_scale, max_modulus, max_rotation, max_repeat,
            max_position_stride, enable_position_arithmetic)
        self._accepted_primitives: dict[tuple, dict[str, Any]] = {}
        self._accepted_primitive_artifacts: dict[
            tuple, dict[str, Any]] = {}
        self._examples: dict[str, list[tuple[list[int], list[int]]]] = {}
        self._procedures: dict[str, tuple[Step, ...]] = {}
        # Keep a bounded index of instructions whose latest complete search
        # found no procedure. Their demonstrations remain in ``_examples``.
        self._no_fit_records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # Complete version spaces are monotone under appended examples. Keep
        # them in memory so each teacher response can filter candidates rather
        # than enumerate the same bounded program grammar again.
        self._candidate_space_cache: OrderedDict[
            str, tuple[
                tuple,
                tuple[tuple[tuple[int, ...], tuple[int, ...]], ...],
                tuple[tuple[Step, ...], ...],
            ]
        ] = OrderedDict()
        self._ambiguity_probe_cache: dict[
            str, tuple[tuple, tuple, list[int], list[list[int]]]
        ] = {}
        self._aligned_phrase_cache: dict[int, tuple[dict, dict, dict]] = {}
        self._optional_span_cache: dict | None = None
        self._number_word_cache: dict[
            tuple[str, ...], tuple[int, set[str]]
        ] | None = None
        self._ordinal_number_phrase_cache: set[tuple[str, ...]] | None = None
        if self.memory_path and self.memory_path.exists():
            self.load()

    @staticmethod
    def _clean_instruction(instruction: str) -> str:
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError('instruction must be a non-empty string')
        return ' '.join(instruction.casefold().split())

    @staticmethod
    def _instruction_sequence(instruction: str) -> list[str]:
        # NFC makes canonically equivalent spellings (for example, a
        # precomposed accented letter and its base-plus-combining-mark form)
        # share lexical evidence without changing the stored surface phrase.
        return list(normalized_tokens(instruction, include_apostrophes=False))

    def _numeric_phrase_slots(
        self, instruction: str,
    ) -> tuple[str, tuple[int, ...], list[str]] | None:
        """Mask digits and example-grounded number phrases as numeric slots."""
        number_words = self._grounded_number_words()
        token_pattern = (r"(?<![\w.])(?:[+-]?\d+|\d+(?:st|nd|rd|th))(?![\w.])"
                         r"|[^\W\d_][\w]*")
        normalized = casefold_nfc(instruction)
        matches = list(re.finditer(token_pattern, normalized, flags=re.UNICODE))
        tokens = [match.group() for match in matches]
        ordered_number_phrases = sorted(
            number_words, key=lambda item: (-len(item), item))
        if not any(_numeric_instruction_value(token) is not None
                   or any(tokens[index:index + len(phrase)] == list(phrase)
                          for phrase in ordered_number_phrases)
                   for index, token in enumerate(tokens)):
            return None
        frame = []
        values = []
        sources = set()
        index = 0
        while index < len(tokens):
            token = tokens[index]
            numeric = _numeric_instruction_value(token)
            if numeric is not None:
                frame.append('<number>')
                values.append(numeric)
                index += 1
                continue
            phrase = next((phrase for phrase in ordered_number_phrases
                if tokens[index:index + len(phrase)] == list(phrase)), None)
            if phrase is not None:
                frame.append('<number>')
                value, evidence = number_words[phrase]
                values.append(value)
                sources.update(evidence)
            else:
                frame.append(token)
            index += len(phrase) if phrase is not None else 1
        return ' '.join(frame), tuple(values), sorted(sources)

    def _grounded_number_words(self) -> dict[tuple[str, ...], tuple[int, set[str]]]:
        """Learn number words and evidence-backed regular ordinal forms."""
        if self._number_word_cache is not None:
            return self._number_word_cache

        observations: dict[tuple[str, ...], dict[int, set[str]]] = {}
        cardinal_observations: dict[
            int, dict[str, set[str]]
        ] = {}
        ordinal_observations: dict[
            int, dict[str, set[str]]
        ] = {}
        grouped_entries: dict[
            tuple, list[tuple[str, tuple[Step, ...], list[str]]]
        ] = {}
        numeric_token_pattern = (
            r"(?<![\w.])(?:[+-]?\d+|\d+(?:st|nd|rd|th))(?![\w.])"
            r"|[^\W\d_][\w]*")
        for phrase, procedure in self._procedures.items():
            grouped_entries.setdefault(_semantic_key(procedure), []).append(
                (phrase, procedure, re.findall(
                    numeric_token_pattern,
                    casefold_nfc(phrase),
                    flags=re.UNICODE)))
        for entries in grouped_entries.values():
            for left in range(len(entries)):
                for right in range(left + 1, len(entries)):
                    left_phrase, left_procedure, left_words = entries[left]
                    right_phrase, _right_procedure, right_words = entries[right]
                    prefix = 0
                    while (prefix < min(len(left_words), len(right_words))
                           and left_words[prefix] == right_words[prefix]):
                        prefix += 1
                    suffix = 0
                    while (suffix < min(len(left_words) - prefix,
                                        len(right_words) - prefix)
                           and left_words[len(left_words) - suffix - 1]
                           == right_words[len(right_words) - suffix - 1]):
                        suffix += 1
                    left_end = len(left_words) - suffix
                    right_end = len(right_words) - suffix
                    spans = (tuple(left_words[prefix:left_end]),
                             tuple(right_words[prefix:right_end]))
                    numeric_spans = [span for span in spans
                                     if len(span) == 1
                                     and _numeric_instruction_value(span[0])
                                     is not None]
                    word_spans = [span for span in spans
                                  if span and all(token.isalpha() for token in span)]
                    if len(numeric_spans) != 1 or len(word_spans) != 1:
                        continue
                    value = _numeric_instruction_value(numeric_spans[0][0])
                    params = []
                    for step in left_procedure:
                        if step.operation == 'double':
                            params.append(2)
                        elif step.operation in ('add_k', 'scale_k',
                                                'keep_multiples_k',
                                                'rotate_left_k', 'repeat_each_k',
                                                'keep_every_kth_position'):
                            params.append(step.parameters['k'])
                    if len(params) != 1 or abs(params[0]) != abs(value):
                        continue
                    number_phrase = word_spans[0]
                    sources = {left_phrase, right_phrase}
                    observations.setdefault(number_phrase, {}).setdefault(
                        value, set()).update(sources)
                    numeric_token = numeric_spans[0][0]
                    if (len(number_phrase) == 1
                            and re.fullmatch(r"\d+(?:st|nd|rd|th)",
                                             numeric_token)):
                        ordinal_observations.setdefault(value, {}).setdefault(
                            number_phrase[0], set()).update(sources)
                    elif len(number_phrase) == 1:
                        cardinal_observations.setdefault(value, {}).setdefault(
                            number_phrase[0], set()).update(sources)

        learned: dict[tuple[str, ...], tuple[int, set[str]]] = {}
        for word, values in observations.items():
            if len(values) == 1:
                value, sources = next(iter(values.items()))
                learned[word] = (value, sources)

        # Infer regular single-token ordinal spelling changes only when at
        # least two distinct grounded values exhibit the same exact affix
        # substitution. Irregular forms such as three/third and five/fifth
        # remain lexical evidence unless separately taught.
        def affix_transform(source: str, target: str) -> tuple[str, str, str, str]:
            prefix = 0
            while (prefix < min(len(source), len(target))
                   and source[prefix] == target[prefix]):
                prefix += 1
            suffix = 0
            while (suffix < min(len(source) - prefix, len(target) - prefix)
                   and source[-suffix - 1] == target[-suffix - 1]):
                suffix += 1
            source_end = len(source) - suffix if suffix else len(source)
            target_end = len(target) - suffix if suffix else len(target)
            source_middle = source[prefix:source_end]
            target_middle = target[prefix:target_end]
            suffix_text = source[len(source) - suffix:] if suffix else ''
            if prefix == len(source) and not suffix:
                return ('<append>', '', target_middle, '')
            return (source[:prefix], source_middle, target_middle, suffix_text)

        transform_support: dict[
            tuple[str, str, str, str], dict[int, set[str]]
        ] = {}
        for value in cardinal_observations.keys() & ordinal_observations.keys():
            for cardinal, cardinal_sources in cardinal_observations[value].items():
                for ordinal, ordinal_sources in ordinal_observations[value].items():
                    transform = affix_transform(cardinal, ordinal)
                    if cardinal == ordinal:
                        continue
                    transform_support.setdefault(transform, {}).setdefault(
                        value, set()).update(cardinal_sources | ordinal_sources)

        generated_ordinals: dict[tuple[str, ...], dict[int, set[str]]] = {}
        for transform, supporting_values in transform_support.items():
            if len(supporting_values) < 2:
                continue
            prefix, source_middle, target_middle, suffix = transform
            for value, cardinal_words in cardinal_observations.items():
                for cardinal, cardinal_sources in cardinal_words.items():
                    if prefix == '<append>':
                        ordinal = cardinal + target_middle
                    else:
                        if (not cardinal.startswith(prefix)
                                or not cardinal.endswith(suffix)):
                            continue
                        middle_end = (len(cardinal) - len(suffix)
                                      if suffix else len(cardinal))
                        middle = cardinal[len(prefix):middle_end]
                        if middle != source_middle:
                            continue
                        ordinal = prefix + target_middle + suffix
                    sources = set(cardinal_sources)
                    for evidence in supporting_values.values():
                        sources.update(evidence)
                    generated_ordinals.setdefault((ordinal,), {}).setdefault(
                        value, set()).update(sources)

        for word, values in generated_ordinals.items():
            if len(values) != 1:
                continue
            value, sources = next(iter(values.items()))
            current = learned.get(word)
            if current is None:
                learned[word] = (value, sources)
        observed_ordinal_phrases = {
            (word,) for words in ordinal_observations.values() for word in words
        }
        self._ordinal_number_phrase_cache = (
            observed_ordinal_phrases | set(generated_ordinals))

        # Infer number composition only from directly grounded digit/word
        # pairs and repeated phrase structures. The bounded additive and
        # multiplicative rules below are not a built-in number-word vocabulary
        # or a general numeral parser.
        additive_support: dict[
            tuple[str, ...], dict[tuple[str, ...], set[str]]
        ] = {}
        for compound, (compound_value, compound_sources) in learned.items():
            for split in range(1, len(compound)):
                prefix, suffix = compound[:split], compound[split:]
                prefix_entry = learned.get(prefix)
                suffix_entry = learned.get(suffix)
                if (prefix_entry is None or suffix_entry is None
                        or prefix_entry[0] <= suffix_entry[0]
                        or prefix_entry[0] + suffix_entry[0] != compound_value):
                    continue
                additive_support.setdefault(prefix, {}).setdefault(
                    suffix, set()).update(
                        compound_sources | prefix_entry[1] | suffix_entry[1])

        composed: dict[tuple[str, ...], dict[int, set[str]]] = {}
        maximum_parameter = max(
            self.max_add, self.max_scale, self.max_rotation,
            self.max_repeat, self.max_modulus, self.max_position_stride)
        for prefix, suffix_examples in additive_support.items():
            if len(suffix_examples) < 2:
                continue
            base_value, base_sources = learned[prefix]
            for suffix, (suffix_value, suffix_sources) in learned.items():
                candidate = prefix + suffix
                value = base_value + suffix_value
                if (candidate in observations or candidate in learned
                        or base_value <= suffix_value
                        or value <= 0 or value > maximum_parameter):
                    continue
                sources = set(base_sources) | set(suffix_sources)
                sources.update(source for rows in suffix_examples.values()
                               for source in rows)
                composed.setdefault(candidate, {}).setdefault(
                    value, set()).update(sources)

        # Learn a multiplicative suffix (for example, "hundred") from at
        # least two directly grounded compounds with different, independently
        # grounded prefixes and one consistent factor. This does not seed any
        # number-word meanings: both the prefixes and the compounds still need
        # digit/word teaching pairs, and the factor is inferred from them.
        multiplicative_support: dict[
            tuple[str, ...], dict[int, dict[tuple[str, ...], set[str]]]
        ] = {}
        for compound, values in observations.items():
            if len(values) != 1:
                continue
            compound_value, compound_sources = next(iter(values.items()))
            for split in range(1, len(compound)):
                prefix, suffix = compound[:split], compound[split:]
                prefix_entry = learned.get(prefix)
                if prefix_entry is None or prefix_entry[0] <= 1:
                    continue
                if compound_value % prefix_entry[0]:
                    continue
                factor = compound_value // prefix_entry[0]
                if factor <= 1:
                    continue
                multiplicative_support.setdefault(suffix, {}).setdefault(
                    factor, {}).setdefault(prefix, set()).update(
                        compound_sources | prefix_entry[1])

        for suffix, factors in multiplicative_support.items():
            for factor, prefixes in factors.items():
                prefix_values = {learned[prefix][0] for prefix in prefixes}
                if len(prefixes) < 2 or len(prefix_values) < 2:
                    continue
                for prefix, (prefix_value, prefix_sources) in learned.items():
                    candidate = prefix + suffix
                    value = prefix_value * factor
                    if (candidate in observations or candidate in learned
                            or value <= 0 or value > maximum_parameter):
                        continue
                    sources = set(prefix_sources)
                    sources.update(source for rows in prefixes.values()
                                   for source in rows)
                    composed.setdefault(candidate, {}).setdefault(
                        value, set()).update(sources)

        # A longer additive construction (for example, "four hundred twenty
        # three") needs evidence that both phrase parts compose, not merely a
        # numeric coincidence from one compound. Admit a split only when two
        # distinct grounded prefixes and two distinct grounded suffixes form
        # a complete 2x2 grid of directly observed compounds with exact sums.
        available = dict(learned)
        for phrase, values in composed.items():
            if (phrase not in observations and len(values) == 1):
                value, sources = next(iter(values.items()))
                available[phrase] = (value, set(sources))
        addition_grids: dict[
            tuple[int, int], dict[
                tuple[tuple[str, ...], tuple[str, ...]], set[str]]
        ] = {}
        for compound, values in observations.items():
            if len(values) != 1:
                continue
            compound_value, compound_sources = next(iter(values.items()))
            for split in range(1, len(compound)):
                prefix, suffix = compound[:split], compound[split:]
                prefix_entry = available.get(prefix)
                suffix_entry = available.get(suffix)
                if (prefix_entry is None or suffix_entry is None
                        or prefix_entry[0] <= 0 or suffix_entry[0] <= 0
                        or prefix_entry[0] <= suffix_entry[0]
                        or prefix_entry[0] + suffix_entry[0] != compound_value):
                    continue
                key = (len(prefix), len(suffix))
                addition_grids.setdefault(key, {}).setdefault(
                    (prefix, suffix), set()).update(
                        compound_sources | prefix_entry[1] | suffix_entry[1])

        for (prefix_width, suffix_width), pairs in addition_grids.items():
            prefixes = sorted({prefix for prefix, _suffix in pairs})
            # Avoid quadratic expansion on an unusually large taught lexicon.
            suffix_count = len({suffix for _prefix, suffix in pairs})
            if len(prefixes) > 64 or suffix_count > 64:
                continue
            support_sources: set[str] = set()
            rectangle_count = 0
            prefix_suffixes: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
            for prefix, suffix in pairs:
                prefix_suffixes.setdefault(prefix, set()).add(suffix)
            for left_index, left_a in enumerate(prefixes):
                for left_b in prefixes[left_index + 1:]:
                    common_suffixes = sorted(
                        prefix_suffixes[left_a] & prefix_suffixes[left_b])
                    for right_a, right_b in combinations(common_suffixes, 2):
                        rectangle = ((left_a, right_a), (left_a, right_b),
                                     (left_b, right_a), (left_b, right_b))
                        for pair in rectangle:
                            support_sources.update(pairs[pair])
                        rectangle_count += 1
                        if rectangle_count >= 256:
                            break
                    if rectangle_count >= 256:
                        break
                if rectangle_count >= 256:
                    break
            if not rectangle_count:
                continue
            candidate_prefixes = sorted(
                phrase for phrase in available if len(phrase) == prefix_width)
            candidate_suffixes = sorted(
                phrase for phrase in available if len(phrase) == suffix_width)
            for prefix in candidate_prefixes:
                for suffix in candidate_suffixes:
                    prefix_entry = available[prefix]
                    suffix_entry = available[suffix]
                    if prefix_entry[0] <= suffix_entry[0]:
                        continue
                    candidate = prefix + suffix
                    value = prefix_entry[0] + suffix_entry[0]
                    if (candidate in observations or candidate in available
                            or value <= 0 or value > maximum_parameter):
                        continue
                    sources = (support_sources | prefix_entry[1]
                               | suffix_entry[1])
                    composed.setdefault(candidate, {}).setdefault(
                        value, set()).update(sources)

        # Learn optional "and" placement only from directly grounded numeral
        # pairs that differ by that single token. Two distinct values must
        # license the same token-count/boundary pattern before it is applied
        # to other grounded or composed number phrases of that shape.
        and_support: dict[tuple[int, int], dict[int, set[str]]] = {}
        for phrase, values in observations.items():
            if len(values) != 1 or phrase.count("and") != 1:
                continue
            value, sources = next(iter(values.items()))
            index = phrase.index("and")
            base = phrase[:index] + phrase[index + 1:]
            if not (0 < index < len(base)):
                continue
            base_values = observations.get(base, {})
            if base_values.get(value) is None:
                continue
            support_sources = set(sources)
            support_sources.update(base_values[value])
            and_support.setdefault((len(base), index), {}).setdefault(
                value, set()).update(support_sources)

        available = dict(learned)
        for phrase, values in composed.items():
            if phrase not in observations and len(values) == 1:
                value, sources = next(iter(values.items()))
                available[phrase] = (value, set(sources))
        for (base_width, index), values in and_support.items():
            if len(values) < 2:
                continue
            support_sources = set().union(*values.values())
            for base, (value, sources) in available.items():
                if len(base) != base_width or base in observations:
                    continue
                candidate = base[:index] + ("and",) + base[index:]
                if candidate in observations or candidate in available:
                    continue
                if value <= 0 or value > maximum_parameter:
                    continue
                composed.setdefault(candidate, {}).setdefault(value, set()).update(
                    support_sources | sources)

        # Infer a one-token sign prefix from directly grounded negative phrases
        # whose remaining number phrase is independently grounded to the
        # corresponding positive magnitude. Require two distinct values before
        # applying the learned prefix to another positive number phrase.
        sign_support: dict[str, dict[int, set[str]]] = {}
        for phrase, values in observations.items():
            if len(phrase) < 2 or len(values) != 1:
                continue
            value, sources = next(iter(values.items()))
            if value >= 0:
                continue
            positive_entry = available.get(phrase[1:])
            if (positive_entry is None
                    or positive_entry[0] != -value):
                continue
            sign_support.setdefault(phrase[0], {}).setdefault(
                value, set()).update(sources | positive_entry[1])

        for marker, negative_values in sign_support.items():
            if len(negative_values) < 2:
                continue
            support_sources = set().union(*negative_values.values())
            for base, (value, sources) in available.items():
                if value <= 0:
                    continue
                candidate = (marker,) + base
                if candidate in observations or candidate in available:
                    continue
                if value > maximum_parameter:
                    continue
                composed.setdefault(candidate, {}).setdefault(
                    -value, set()).update(support_sources | sources)
        for phrase, values in composed.items():
            if len(values) == 1:
                learned[phrase] = next(iter(values.items()))
        self._number_word_cache = learned
        return learned

    def grounded_cardinal_phrases(
            self) -> dict[tuple[str, ...], tuple[int, tuple[str, ...]]]:
        """Expose uniquely learned cardinal phrases with their teaching sources.

        The result excludes directly observed and induced ordinal forms. Values
        remain bounded by the operation-parameter evidence used by the number
        phrase learner; no built-in numeral vocabulary is consulted.
        """
        learned = self._grounded_number_words()
        ordinal_phrases = self._ordinal_number_phrase_cache or set()
        return {
            phrase: (value, tuple(sorted(sources)))
            for phrase, (value, sources) in learned.items()
            if phrase not in ordinal_phrases
            and not any(
                phrase[index:index + len(ordinal)] == ordinal
                for ordinal in ordinal_phrases
                for index in range(len(phrase) - len(ordinal) + 1))
        }

    def _retrieve_parameterized_procedure(
        self, instruction: str,
    ) -> tuple[tuple[Step, ...] | None, bool, list[str], str | None,
               list[dict[str, Any]]]:
        """Apply numeric phrase slots learned from grounded parameter values.

        No predefined number-word meanings are used. A template is eligible
        only when at least two distinct taught phrases have a grounded numeric
        frame and each numeric slot maps consistently, directly or by sign
        reversal, to a distinct varying procedure parameter. Supporting phrases
        may use different surface frames when their successful procedures share
        the same operation scaffold. Other parameters must remain fixed.
        """
        query_slots = self._numeric_phrase_slots(instruction)
        query_template, query_values, query_word_sources = (
            query_slots if query_slots is not None else (None, (), []))
        query_words = self._instruction_sequence(instruction)
        number_words = self._grounded_number_words()
        groups: dict[tuple, list[tuple[
            str, str, tuple[int, ...], tuple[Step, ...], tuple[int, ...],
            tuple[str, ...], tuple[int, ...],
        ]]] = {}
        grounded_parameter_frame = False
        grounded_parameter_sources: set[str] = set()
        ungrounded_parameter_sources: set[str] = set()
        ungrounded_parameter_templates: set[str] = set()

        def slot_parameter_assignments(
                literals: tuple[int, ...], parameters: tuple[int, ...]
                ) -> set[tuple[tuple[int, ...], tuple[int, ...]]]:
            """Map each observed number slot to one distinct procedure parameter."""
            assignments: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()

            def visit(slot: int, indices: tuple[int, ...],
                      signs: tuple[int, ...]) -> None:
                if slot == len(literals):
                    assignments.add((indices, signs))
                    return
                literal = literals[slot]
                for parameter_index, parameter in enumerate(parameters):
                    if parameter_index in indices:
                        continue
                    if literal == parameter:
                        visit(slot + 1, indices + (parameter_index,),
                              signs + (1,))
                    elif literal == -parameter:
                        visit(slot + 1, indices + (parameter_index,),
                              signs + (-1,))

            visit(0, (), ())
            return assignments

        def frame_role_evidence(
                entries: list[tuple[str, str, tuple[int, ...], tuple[Step, ...],
                                    tuple[int, ...], tuple[str, ...], tuple[int, ...]]]
                ) -> tuple[bool, list[dict[str, Any]]]:
            """Return positional role support used to compose a phrase frame."""
            if query_template is None or not entries:
                return False, []
            query_tokens = tuple(query_template.split())
            matching_entries = [entry for entry in entries
                                if entry[0] == query_template]
            direct_frame = bool(matching_entries)
            role_entries = matching_entries if direct_frame else entries
            if not direct_frame and any(
                    len(tuple(entry[0].split())) != len(query_tokens)
                    for entry in role_entries):
                return False, []
            role_sources: list[dict[str, set[str]]] = [
                {} for _token in query_tokens]
            for template, phrase, *_rest in role_entries:
                for index, token in enumerate(template.split()):
                    if token == '<number>':
                        continue
                    role_sources[index].setdefault(token, set()).add(phrase)
            evidence = [
                {'position': index, 'token': token,
                 'supporting_phrases': sorted(role_sources[index].get(token, set()))}
                for index, token in enumerate(query_tokens)
                if token != '<number>'
            ]
            if direct_frame:
                return True, evidence
            varying_roles = sum(
                len(values) > 1 for index, values in enumerate(role_sources)
                if query_tokens[index] != '<number>')
            supported = (
                varying_roles >= 2
                and all(token == '<number>'
                        or len(role_sources[index].get(token, set())) >= 2
                        for index, token in enumerate(query_tokens)))
            return supported, evidence

        for phrase, procedure in self._procedures.items():
            phrase_slots = self._numeric_phrase_slots(phrase)
            if phrase_slots is None:
                continue
            template, phrase_values, _phrase_word_sources = phrase_slots
            parameter_indices = []
            parameter_families = []
            inferred_values = []
            for index, step in enumerate(procedure):
                if step.operation == 'double':
                    family, value = 'scale_k', 2
                elif step.operation in ('add_k', 'scale_k',
                                        'keep_multiples_k',
                                        'rotate_left_k',
                                        'repeat_each_k',
                                        'keep_every_kth_position'):
                    family, value = step.operation, step.parameters.get('k')
                else:
                    continue
                parameter_indices.append(index)
                parameter_families.append(family)
                inferred_values.append(value)
            if not inferred_values:
                continue

            template_tokens = template.split()

            @lru_cache(maxsize=None)
            def match_template(template_index: int, query_index: int):
                if template_index == len(template_tokens):
                    return ((),) if query_index == len(query_words) else ()
                if template_tokens[template_index] != '<number>':
                    if (query_index >= len(query_words)
                            or template_tokens[template_index] != query_words[query_index]):
                        return ()
                    return match_template(template_index + 1, query_index + 1)
                results = []
                for end in range(query_index + 1, len(query_words) + 1):
                    span = tuple(query_words[query_index:end])
                    if not all(token.isalpha() for token in span):
                        break
                    for suffix in match_template(template_index + 1, end):
                        results.append((span,) + suffix)
                        if len(results) >= 2:
                            return tuple(results)
                return tuple(results)

            unknown_matches = match_template(0, 0)
            if (query_template != template and len(unknown_matches) == 1
                    and any(slot not in number_words
                            for slot in unknown_matches[0])):
                ungrounded_parameter_sources.add(phrase)
                ungrounded_parameter_templates.add(template)

            shape = tuple(
                (part.operation, tuple(sorted(
                    (name, value) for name, value in part.parameters.items()
                    if not (i in parameter_indices and name == 'k'))),
                 ('scale_k' if part.operation == 'double'
                  else 'keep_multiples_k' if part.operation == 'keep_multiples_k'
                  else 'repeat_each_k' if part.operation == 'repeat_each_k'
                  else part.operation))
                for i, part in enumerate(procedure))
            group = (shape, tuple(parameter_indices), tuple(parameter_families))
            groups.setdefault(group, []).append((
                template, phrase, phrase_values, procedure,
                tuple(parameter_indices), tuple(parameter_families),
                tuple(inferred_values)))

        candidates: dict[tuple, tuple[Step, ...]] = {}
        supporting_phrases: dict[tuple, list[str]] = {}
        candidate_templates: dict[tuple, str] = {}
        candidate_traces: dict[tuple, list[dict[str, Any]]] = {}
        validated_scaffold_groups: dict[tuple, str] | None = None

        def mdl_gated_scaffold(entries) -> str | None:
            nonlocal validated_scaffold_groups
            if validated_scaffold_groups is None:
                validated_scaffold_groups = {}
                for proposal in self.propose_procedure_scaffolds():
                    signature = tuple(
                        (step['operation'], tuple(sorted(step['parameters'])))
                        for step in proposal['descriptor'])
                    sources = frozenset(
                        proposal['supporting_instructions']
                        + proposal['held_out_instructions'])
                    validated_scaffold_groups[(signature, sources)] = (
                        proposal['artifact_id'])
            procedure = entries[0][3]
            signature = tuple(
                (step.operation, tuple(sorted(step.parameters)))
                for step in procedure)
            return validated_scaffold_groups.get(
                (signature, frozenset(entry[1] for entry in entries)))

        for group, entries in groups.items():
            _shape, parameter_indices, parameter_families = group
            matching_query_frames = [entry for entry in entries
                                     if entry[0] == query_template]
            scaffold_id = None
            if not matching_query_frames:
                scaffold_id = mdl_gated_scaffold(entries)
                if scaffold_id is None:
                    continue
            frame_supported, role_evidence = frame_role_evidence(entries)
            if not frame_supported:
                continue
            # A direct taught frame can ground the query immediately. A novel
            # frame reaches this point only after positional role support from
            # this same successful operation scaffold; all paths still need a
            # shared consistent numeric-slot mapping below.
            grounded_parameter_frame = True
            frame_sources = (matching_query_frames if matching_query_frames
                             else entries)
            grounded_parameter_sources.update(entry[1] for entry in frame_sources)
            if len(entries) < 2 or any(
                    len(entry[2]) != len(entries[0][2])
                    for entry in entries[1:]):
                continue

            mappings = slot_parameter_assignments(
                entries[0][2], entries[0][6])
            for entry in entries[1:]:
                mappings.intersection_update(slot_parameter_assignments(
                    entry[2], entry[6]))
            valid_mappings = []
            for mapped_indices, signs in mappings:
                mapped_set = set(mapped_indices)
                if any(len({entry[6][index] for entry in entries}) < 2
                       for index in mapped_indices):
                    continue
                if any(len({entry[6][index] for entry in entries}) != 1
                       for index in range(len(parameter_indices))
                       if index not in mapped_set):
                    continue
                valid_mappings.append((mapped_indices, signs))
            if not valid_mappings:
                continue

            for mapped_indices, signs in valid_mappings:
                query_parameters = [None] * len(parameter_indices)
                in_range = True
                for slot, (parameter_index, sign) in enumerate(
                        zip(mapped_indices, signs)):
                    value = sign * query_values[slot]
                    family = parameter_families[parameter_index]
                    if family == 'add_k':
                        in_range = in_range and 0 < abs(value) <= self.max_add
                    elif family == 'scale_k':
                        in_range = in_range and (
                            value == 0
                            or -self.max_scale <= value <= -1
                            or 2 <= value <= self.max_scale)
                    elif family == 'rotate_left_k':
                        in_range = in_range and (
                            -self.max_rotation <= value <= self.max_rotation
                            and value != 0)
                    elif family == 'repeat_each_k':
                        in_range = in_range and 2 <= value <= self.max_repeat
                    elif family == 'keep_every_kth_position':
                        in_range = in_range and 3 <= value <= self.max_position_stride
                    else:
                        in_range = in_range and 3 <= value <= self.max_modulus
                    query_parameters[parameter_index] = value
                if not in_range:
                    continue
                representative = entries[0][3]
                procedure = list(representative)
                for parameter_index, index in enumerate(parameter_indices):
                    value = (entries[0][6][parameter_index]
                             if query_parameters[parameter_index] is None
                             else query_parameters[parameter_index])
                    family = parameter_families[parameter_index]
                    if family == 'scale_k' and value == 2:
                        procedure[index] = Step('double', {})
                    else:
                        procedure[index] = Step(family, {'k': value})
                candidate = tuple(procedure)
                key = _semantic_key(candidate)
                candidates.setdefault(key, candidate)
                supporting_phrases.setdefault(key, [])
                supporting_phrases[key] = sorted(
                    set(supporting_phrases[key])
                    | {entry[1] for entry in entries})
                candidate_template = (
                    query_template if matching_query_frames
                    else f'procedure_scaffold_frame:{query_template}')
                previous_template = candidate_templates.get(key)
                if (previous_template is None
                        or (previous_template.startswith(
                            'procedure_scaffold_frame:')
                            and not candidate_template.startswith(
                                'procedure_scaffold_frame:'))):
                    candidate_templates[key] = candidate_template
                numeric_bindings = []
                for slot, (parameter_index, sign) in enumerate(
                        zip(mapped_indices, signs)):
                    numeric_bindings.append({
                        'slot': slot + 1,
                        'surface_value': query_values[slot],
                        'parameter_value': sign * query_values[slot],
                        'procedure_step': parameter_indices[parameter_index],
                        'operation': parameter_families[parameter_index],
                        'parameter': 'k',
                        'sign': sign,
                        'training_evidence': [
                            {'phrase': entry[1],
                             'surface_value': entry[2][slot],
                             'parameter_value': entry[6][parameter_index]}
                            for entry in entries
                        ],
                    })
                trace = {
                    'kind': 'parameterized_procedure_scaffold',
                    'scaffold_id': scaffold_id,
                    'frame_type': ('direct' if matching_query_frames
                                   else 'positional_recombination'),
                    'query_frame': query_template,
                    'operation_scaffold': [
                        {'step': index, 'operation': step.operation,
                         'parameters': dict(step.parameters)}
                        for index, step in enumerate(candidate)
                    ],
                    'role_evidence': role_evidence,
                    'numeric_bindings': numeric_bindings,
                    'supporting_phrases': sorted(
                        {entry[1] for entry in entries}),
                }
                candidate_traces.setdefault(key, []).append(trace)

        if ungrounded_parameter_sources:
            template = (next(iter(ungrounded_parameter_templates))
                        if len(ungrounded_parameter_templates) == 1
                        else '<multiple numeric frames>')
            return (None, True, sorted(ungrounded_parameter_sources), template, [])
        if query_slots is None:
            return None, False, [], None, []
        if len(candidates) == 1:
            key, procedure = next(iter(candidates.items()))
            sources = sorted(set(supporting_phrases[key]) | set(query_word_sources))
            return (procedure, False, sources, candidate_templates[key],
                    candidate_traces[key])
        if len(candidates) > 1:
            sources = {phrase for phrases in supporting_phrases.values()
                       for phrase in phrases}
            sources.update(query_word_sources)
            traces = [trace for records in candidate_traces.values()
                      for trace in records]
            return None, True, sorted(sources), query_template, traces
        if grounded_parameter_frame:
            return (None, True,
                    sorted(grounded_parameter_sources | set(query_word_sources)),
                    query_template, [])
        return None, False, [], None, []

    @staticmethod
    def _word_affix_edit(
        left: str, right: str,
    ) -> tuple[str, str, str, str] | None:
        """Describe a short, productive prefix or ending edit."""
        if len(left) == len(right):
            return None
        root, variant = (left, right) if len(left) < len(right) else (right, left)
        if variant.startswith(root):
            addition = variant[len(root):]
            if 1 <= len(addition) <= 2 and addition.isalpha():
                return root, 'suffix', '', addition
        if variant.endswith(root):
            addition = variant[:-len(root)]
            if 1 <= len(addition) <= 2 and addition.isalpha():
                return root, 'prefix', '', addition
        prefix_length = 0
        while (prefix_length < min(len(root), len(variant))
               and root[prefix_length] == variant[prefix_length]):
            prefix_length += 1
        if prefix_length < 2:
            return None
        old_affix = root[prefix_length:]
        new_affix = variant[prefix_length:]
        if (len(old_affix) > 2 or not 1 <= len(new_affix) <= 3
                or (old_affix and not old_affix.isalpha())
                or not new_affix.isalpha()):
            return None
        return root, 'suffix', old_affix, new_affix

    def _grounded_optional_spans(self) -> dict:
        """Find repeated same-rule contiguous deletions by token position."""
        if self._optional_span_cache is not None:
            return self._optional_span_cache

        groups: dict[tuple, list[tuple[str, list[str]]]] = {}
        for phrase, procedure in self._procedures.items():
            behavior = _semantic_key(procedure)
            groups.setdefault(behavior, []).append(
                (phrase, self._instruction_sequence(phrase)))

        observations: dict[tuple[tuple, int, tuple[str, ...]], dict[
            tuple[str, str], set[tuple[str, str]]]] = {}
        for entries in groups.values():
            for left in range(len(entries)):
                for right in range(left + 1, len(entries)):
                    left_phrase, left_words = entries[left]
                    right_phrase, right_words = entries[right]
                    if len(left_words) == len(right_words):
                        continue
                    if len(left_words) > len(right_words):
                        long_phrase, long_words = left_phrase, left_words
                        short_phrase, short_words = right_phrase, right_words
                    else:
                        long_phrase, long_words = right_phrase, right_words
                        short_phrase, short_words = left_phrase, left_words
                    behavior = _semantic_key(
                        self._procedures[long_phrase])
                    for start in range(len(long_words)):
                        for end in range(start + 1, len(long_words) + 1):
                            if long_words[:start] + long_words[end:] != short_words:
                                continue
                            span = tuple(long_words[start:end])
                            left_context = (long_words[start - 1]
                                            if start else '<start>')
                            right_context = (long_words[end]
                                             if end < len(long_words) else '<end>')
                            key = (behavior, start, span)
                            observations.setdefault(key, {}).setdefault(
                                (left_context, right_context), set()).add(
                                    (long_phrase, short_phrase))

        patterns = {}
        for key, contexts in observations.items():
            pairs = {pair for context_pairs in contexts.values()
                     for pair in context_pairs}
            # Require independent phrase-pair evidence in multiple lexical
            # contexts; one demonstrated span omission cannot license deletion.
            if len(contexts) >= 2 and len(pairs) >= 2:
                patterns[key] = (
                    set(contexts),
                    {phrase for pair in pairs for phrase in pair},
                )
        self._optional_span_cache = patterns
        return patterns

    def _aligned_phrase_index(self, length: int) -> tuple[dict, dict, dict]:
        cached = self._aligned_phrase_cache.get(length)
        if cached is not None:
            return cached

        groups: dict[tuple[int, tuple], list[tuple[
            str, tuple[Step, ...], list[str], tuple[str, ...]]]] = {}
        optional_spans = self._grounded_optional_spans()
        for phrase, procedure in self._procedures.items():
            words = self._instruction_sequence(phrase)
            behavior = _semantic_key(procedure)
            variants: dict[tuple[str, ...], set[str]] = {tuple(words): set()}
            for (pattern_behavior, index, span), pattern in optional_spans.items():
                if pattern_behavior != behavior:
                    continue
                end = index + len(span)
                if (end <= len(words) and len(words) - len(span) == length
                        and tuple(words[index:end]) == span):
                    shortened = tuple(words[:index] + words[end:])
                    variants.setdefault(shortened, set()).update(pattern[1])
                elif len(words) + len(span) == length and index <= len(words):
                    expanded = tuple(words[:index] + list(span) + words[index:])
                    variants.setdefault(expanded, set()).update(pattern[1])
            for variant, deletion_sources in variants.items():
                if len(variant) != length:
                    continue
                groups.setdefault((length, behavior), []).append(
                    (phrase, procedure, list(variant),
                     tuple(sorted(deletion_sources))))

        edit_roots: dict[tuple[int, int, str, str, str], set[str]] = {}
        edit_sources: dict[tuple[int, int, str, str, str], set[str]] = {}
        for (phrase_length, _behavior), entries in groups.items():
            for index in range(phrase_length):
                for left in range(len(entries)):
                    for right in range(left + 1, len(entries)):
                        if entries[left][0] == entries[right][0]:
                            continue
                        left_words = entries[left][2]
                        right_words = entries[right][2]
                        differences = [i for i, (a, b) in enumerate(
                            zip(left_words, right_words)) if a != b]
                        if differences != [index]:
                            continue
                        edit = self._word_affix_edit(
                            left_words[index], right_words[index])
                        if edit is None:
                            continue
                        root, side, old_affix, new_affix = edit
                        edit_key = (phrase_length, index, side, old_affix, new_affix)
                        edit_roots.setdefault(edit_key, set()).add(root)
                        edit_sources.setdefault(edit_key, set()).update(
                            (entries[left][0], entries[right][0]))

        cached = (groups, edit_roots, edit_sources)
        self._aligned_phrase_cache[length] = cached
        return cached

    def _invalidate_language_indexes(self) -> None:
        self._aligned_phrase_cache.clear()
        self._optional_span_cache = None
        self._procedure_scaffold_cache.clear()
        self._number_word_cache = None
        self._ordinal_number_phrase_cache = None
        self._lexical_feature_cache = None
        self._vsa_phrase_cache.clear()
        self._vsa_phrase_tokens.clear()
        self._vsa_phrase_counts.clear()
        self._vsa_phrase_behaviors.clear()
        self._vsa_token_index = None
        self._composition_connective_cache = None
        self._canonical_instruction_index = None

    def _canonical_instruction_sources(self) -> dict[str, tuple[str, ...]]:
        """Index taught phrases by Unicode-canonical instruction identity."""
        if self._canonical_instruction_index is None:
            grouped: dict[str, set[str]] = {}
            for phrase in set(self._examples) | set(self._procedures):
                grouped.setdefault(casefold_nfc(phrase), set()).add(phrase)
            self._canonical_instruction_index = {
                identity: tuple(sorted(phrases))
                for identity, phrases in grouped.items()
            }
        return self._canonical_instruction_index

    def _canonical_instruction_storage_key(self, key: str) -> str:
        """Reuse a unique stored spelling for canonically equivalent input."""
        matches = self._canonical_instruction_sources().get(
            casefold_nfc(key), ())
        if key in matches or len(matches) != 1:
            return key
        return matches[0]

    def _ensure_vsa_token_index(self) -> dict[str, set[str]]:
        if self._vsa_token_index is None:
            token_index: dict[str, set[str]] = {}
            behavior_by_procedure: dict[tuple, tuple] = {}
            for phrase in self._procedures:
                tokens = tuple(self._instruction_sequence(phrase))
                self._vsa_phrase_tokens[phrase] = tokens
                self._vsa_phrase_counts[phrase] = Counter(tokens)
                procedure = self._procedures[phrase]
                signature = tuple(
                    (step.operation, tuple(sorted(step.parameters.items())))
                    for step in procedure
                )
                behavior = behavior_by_procedure.get(signature)
                if behavior is None:
                    behavior = _semantic_key(procedure)
                    behavior_by_procedure[signature] = behavior
                self._vsa_phrase_behaviors[phrase] = behavior
                for token in set(tokens):
                    token_index.setdefault(token, set()).add(phrase)
            self._vsa_token_index = token_index
        return self._vsa_token_index

    def _retrieve_vsa_candidates(
        self, instruction: str,
    ) -> tuple[list[tuple[float, str, tuple[Step, ...]]], float | None, float | None]:
        """Rank behaviorally distinct phrases by dual VSA similarity.

        Random token vectors support similarity from shared tokens only; they
        do not encode synonym meaning. Query tokens must form an in-order
        subsequence of a candidate phrase, allowing omitted words but rejecting
        unexplained additions and reorderings. Both position-bound and
        order-invariant similarities are combined, and a score plus margin
        gate prevents an ungrounded nearest-neighbor guess.
        """
        query_tokens = self._instruction_sequence(instruction)
        if not query_tokens:
            return [], None, None
        query_counts = Counter(query_tokens)
        token_index = self._ensure_vsa_token_index()
        query_unique = set(query_counts)
        postings = [token_index.get(token) for token in query_unique]
        if not postings or any(posting is None for posting in postings):
            return [], None, None
        candidate_phrases = min(postings, key=len)
        if len(postings) > 1:
            # Every query token is required by the later multiplicity and
            # subsequence checks. Intersect even dense postings: the C-level
            # set operation can avoid a much larger Python candidate loop.
            candidate_phrases = candidate_phrases.intersection(
                *(posting for posting in postings if posting is not candidate_phrases)
            )
            if not candidate_phrases:
                return [], None, None
        query_position, query_order = self._vsa_encoder.encode_packed(query_tokens)
        scores: dict[tuple, tuple[float, str, tuple[Step, ...]]] = {}

        for phrase in candidate_phrases:
            procedure = self._procedures[phrase]
            phrase_tokens = self._vsa_phrase_tokens[phrase]
            phrase_counts = self._vsa_phrase_counts[phrase]
            if any(phrase_counts[token] < count
                   for token, count in query_counts.items()):
                continue
            phrase_positions = iter(phrase_tokens)
            if not all(any(observed == token for observed in phrase_positions)
                       for token in query_tokens):
                # The order-invariant vector is useful after omitted words,
                # while this symbolic gate prevents it from licensing a
                # reordered bag of otherwise familiar tokens.
                continue
            vectors = self._vsa_phrase_cache.get(phrase)
            if vectors is None:
                vectors = self._vsa_encoder.encode_packed(phrase_tokens)
                self._vsa_phrase_cache[phrase] = vectors
            phrase_position, phrase_order = vectors
            position_score = self._vsa_encoder.packed_similarity(
                query_position, phrase_position)
            order_score = self._vsa_encoder.packed_similarity(
                query_order, phrase_order)
            score = ((1 - self.vsa_alpha) * position_score
                     + self.vsa_alpha * order_score)
            behavior = self._vsa_phrase_behaviors[phrase]
            current = scores.get(behavior)
            if (current is None or score > current[0]
                    or (score == current[0] and phrase < current[1])):
                scores[behavior] = (score, phrase, procedure)

        if not scores:
            return [], None, None
        ranked = sorted(scores.values(), key=lambda item: (-item[0], item[1]))
        top_score = ranked[0][0]
        margin = top_score - ranked[1][0] if len(ranked) > 1 else 2.0
        return ranked, top_score, margin

    def _retrieve_vsa_procedure(
        self, instruction: str,
    ) -> tuple[tuple[Step, ...] | None, list[str], float | None, float | None]:
        """Retrieve a procedure only when similarity and margin gates pass."""
        ranked, top_score, margin = self._retrieve_vsa_candidates(instruction)
        if not ranked:
            return None, [], top_score, margin
        if (top_score < self.vsa_min_similarity
                or margin < self.vsa_min_margin):
            return None, [], top_score, margin
        return ranked[0][2], [ranked[0][1]], top_score, margin

    def _retrieve_aligned_phrase(
        self, instruction: str,
    ) -> tuple[tuple[Step, ...] | None, bool, list[str], str | None]:
        """Generalize grounded substitutions, affixes, and optional deletions.

        A rule can transfer to a new combination only when at least two
        distinct grounded phrases share its behavior and every query word is
        observed at that position, or licensed by a learned affix edit. A
        contiguous token-span deletion must be demonstrated in multiple
        same-rule contexts at the same position. No general synonym relation
        is stored.
        """
        query = self._instruction_sequence(instruction)
        if not query:
            return None, False, [], None
        groups, edit_roots, edit_sources = self._aligned_phrase_index(len(query))

        matches: dict[tuple, tuple[tuple[Step, ...], list[str], str]] = {}
        for (_length, behavior), entries in groups.items():
            if len({phrase for phrase, _, _, _ in entries}) < 2:
                continue
            columns = [set(entry[2][index] for entry in entries)
                       for index in range(len(query))]
            affix_support: list[dict[str, set[str]]] = [
                {} for _ in range(len(query))]
            affix_sources: list[dict[str, set[str]]] = [
                {} for _ in range(len(query))]
            for index in range(len(query)):
                for (length, edit_index, side, old_affix, new_affix), roots in edit_roots.items():
                    if length != len(query) or edit_index != index:
                        continue
                    if len(roots) < 2:
                        continue
                    for root in columns[index]:
                        if side == 'suffix':
                            if old_affix and not root.endswith(old_affix):
                                continue
                            derived = (root[:-len(old_affix)] + new_affix
                                       if old_affix else root + new_affix)
                        else:
                            if old_affix and not root.startswith(old_affix):
                                continue
                            derived = (new_affix + root[len(old_affix):]
                                       if old_affix else new_affix + root)
                        affix_support[index].setdefault(derived, set()).add(root)
                        affix_sources[index].setdefault(derived, set()).update(
                            edit_sources[(length, edit_index, side, old_affix, new_affix)])

            expanded_columns = [
                column | set(affix_support[index])
                for index, column in enumerate(columns)
            ]
            if not all(word in column for word, column in zip(query, expanded_columns)):
                continue
            position_evidence = True
            for index, column in enumerate(columns):
                if query[index] not in column:
                    # The form was licensed by an affix edit supported by at
                    # least two distinct stems in same-rule phrase contrasts.
                    if query[index] in affix_support[index]:
                        continue
                    position_evidence = False
                    break
                if len(column) == 1:
                    continue
                supported = False
                for left in range(len(entries)):
                    for right in range(left + 1, len(entries)):
                        left_words = entries[left][2]
                        right_words = entries[right][2]
                        if entries[left][0] == entries[right][0]:
                            continue
                        differences = [i for i, (a, b) in enumerate(
                            zip(left_words, right_words)) if a != b]
                        if (differences == [index]
                                and query[index] in (left_words[index], right_words[index])):
                            supported = True
                            break
                    if supported:
                        break
                if not supported:
                    position_evidence = False
                    break
            if not position_evidence:
                continue
            procedure = entries[0][1]
            evidence_phrases = {phrase for phrase, _, _, _ in entries}
            evidence_phrases.update(
                source for _, _, _, deletion_sources in entries
                for source in deletion_sources)
            for index, column in enumerate(columns):
                if query[index] not in column:
                    evidence_phrases.update(affix_sources[index][query[index]])
            sources = sorted(evidence_phrases)
            template = ' '.join(
                next(iter(expanded_columns[index]))
                if len(expanded_columns[index]) == 1
                else '{' + '|'.join(sorted(expanded_columns[index])) + '}'
                for index in range(len(query)))
            matches[behavior] = (procedure, sources, template)

        if len(matches) == 1:
            procedure, sources, template = next(iter(matches.values()))
            return procedure, False, sources, template
        if len(matches) > 1:
            return None, True, [], None
        return None, False, [], None

    def _retrieve_contrastive_slot(
        self, instruction: str,
    ) -> tuple[tuple[Step, ...] | None, bool, list[str], str | None]:
        """Transfer a categorical word slot whose values map to distinct rules.

        A slot value is usable only when the same indexed token maps to one
        procedure in at least two distinct taught phrases, and at least two
        values at that position map to different procedures. Every other query
        token must also occur at its position in a phrase supporting the
        selected procedure. This supports grounded recombination without
        assigning a general meaning to words such as ``first`` or ``last``.
        """
        query = tuple(self._instruction_sequence(instruction))
        if len(query) < 2:
            return None, False, [], None
        columns: list[dict[str, dict[tuple, set[str]]]] = [
            {} for _ in query
        ]
        procedures_by_behavior: dict[tuple, tuple[Step, ...]] = {}
        for phrase, procedure in self._procedures.items():
            words = tuple(self._instruction_sequence(phrase))
            if len(words) != len(query):
                continue
            behavior = _semantic_key(procedure)
            procedures_by_behavior[behavior] = procedure
            for index, word in enumerate(words):
                columns[index].setdefault(word, {}).setdefault(
                    behavior, set()).add(phrase)

        candidates: dict[tuple, tuple[tuple[Step, ...], set[str], str]] = {}
        conflict_sources: set[str] = set()
        for index, column in enumerate(columns):
            unique_values = {
                word: next(iter(behaviors.items()))
                for word, behaviors in column.items()
                if len(behaviors) == 1
                and len(next(iter(behaviors.values()))) >= 2
            }
            role_behaviors = {behavior for behavior, _phrases
                              in unique_values.values()}
            if len(role_behaviors) < 2:
                conflicting = column.get(query[index], {})
                if role_behaviors and len(conflicting) > 1:
                    conflict_sources.update(
                        phrase for phrases in conflicting.values()
                        for phrase in phrases)
                continue
            selected = unique_values.get(query[index])
            if selected is None:
                conflicting = column.get(query[index], {})
                if len(conflicting) > 1:
                    conflict_sources.update(
                        phrase for phrases in conflicting.values()
                        for phrase in phrases)
                continue
            behavior, _role_phrases = selected
            position_sources: set[str] = set()
            supported = True
            for query_index, word in enumerate(query):
                sources = columns[query_index].get(word, {}).get(behavior, set())
                if not sources:
                    supported = False
                    break
                position_sources.update(sources)
            if not supported or len(position_sources) < 2:
                continue
            template = (f"contrastive_slot:{index}="
                        + "|".join(sorted(unique_values)))
            current = candidates.get(behavior)
            if current is None:
                candidates[behavior] = (
                    procedures_by_behavior[behavior], position_sources, template)
            else:
                current[1].update(position_sources)
                if template < current[2]:
                    candidates[behavior] = (current[0], current[1], template)

        if len(candidates) == 1:
            procedure, sources, template = next(iter(candidates.values()))
            return procedure, False, sorted(sources), template
        if len(candidates) > 1 or conflict_sources:
            sources = set(conflict_sources)
            sources.update(phrase for _procedure, phrases, _template
                           in candidates.values() for phrase in phrases)
            return None, True, sorted(sources), None
        return None, False, [], None

    def _retrieve_analogical_frame(
        self, instruction: str,
    ) -> tuple[tuple[Step, ...] | None, bool, list[str], str | None]:
        """Complete a grounded positional frame across same-behavior cases.

        This is a discrete structural analogy, not a synonym model. The frame
        is token position; its role values are licensed only by independently
        taught phrases in one behaviorally equivalent procedure group. At
        least two positions must vary, and each queried role value must recur
        in two distinct phrases. Ordinary one-slot substitutions remain the
        responsibility of the stricter aligned-phrase route.
        """
        query = tuple(self._instruction_sequence(instruction))
        if len(query) < 2:
            return None, False, [], None

        matches: dict[tuple, tuple[tuple[Step, ...], list[str], str]] = {}
        groups, _edit_roots, _edit_sources = self._aligned_phrase_index(len(query))
        for (_length, behavior), entries in groups.items():
            distinct: dict[str, tuple[Step, ...]] = {}
            words_by_phrase: dict[str, set[tuple[str, ...]]] = {}
            for phrase, procedure, words, _deletion_sources in entries:
                distinct[phrase] = procedure
                words_by_phrase.setdefault(phrase, set()).add(tuple(words))
            if len(distinct) < 2:
                continue

            # An exact case is not an analogy. The normal exact route handles it.
            if any(query in variants for variants in words_by_phrase.values()):
                continue
            role_phrases: list[dict[str, set[str]]] = [
                {} for _ in query
            ]
            for phrase, variants in words_by_phrase.items():
                for words in variants:
                    if len(words) != len(query):
                        continue
                    for index, word in enumerate(words):
                        role_phrases[index].setdefault(word, set()).add(phrase)
            role_values = [set(values) for values in role_phrases]
            varying_roles = sum(len(values) > 1 for values in role_values)
            if (varying_roles < 2
                    or any(word not in role_values[index]
                           or len(role_phrases[index][word]) < 2
                           for index, word in enumerate(query))):
                continue

            procedure = next(iter(distinct.values()))
            sources = sorted(distinct)
            template = ' '.join(
                '{' + '|'.join(sorted(values)) + '}'
                if len(values) > 1 else next(iter(values))
                for values in role_values
            )
            matches[behavior] = (procedure, sources, template)

        if len(matches) == 1:
            procedure, sources, template = next(iter(matches.values()))
            return procedure, False, sources, f'analogy_frame:{template}'
        if len(matches) > 1:
            return None, True, [], None
        return None, False, [], None

    def _retrieve_grounded_procedure(
        self, instruction: str,
    ) -> tuple[tuple[Step, ...] | None, bool, dict[str, list[str]]]:
        """Retrieve a procedure only from repeated lexical feature evidence.

        A word or adjacent word pair is usable when it occurs in at least two
        distinct taught instruction associations. Associated procedures form
        candidate sets that are intersected. This is a small lexical memory,
        not a semantic model: unseen synonyms do not match, and empty or
        non-unique intersections cause abstention. The bool reports conflicting
        lexical evidence.
        """
        feature_phrases, feature_procedures, procedure_by_key = (
            self._ensure_lexical_feature_index())

        constraints: list[set[tuple]] = []
        words = self._instruction_sequence(instruction)
        features = {('token', token) for token in words}
        features.update(('bigram', left, right)
                        for left, right in zip(words, words[1:]))
        for feature in features:
            procedures = feature_procedures.get(feature, set())
            if feature[0] == 'token' and not procedures:
                # Unknown words could carry an instruction modifier (for
                # example, negation); never silently discard them.
                return None, False, {}
            if (feature[0] == 'bigram'
                    and len(feature_phrases.get(feature, set())) < 2):
                # A familiar bag of words in a novel order is not enough to
                # ground a procedure. Aligned positional transfer runs before
                # this lexical route and handles independently contrasted
                # substitutions without treating arbitrary word order as safe.
                return None, False, {}
            if len(feature_phrases.get(feature, set())) >= 2:
                constraints.append(procedures)

        if not constraints:
            return None, False, {}
        candidates = set.intersection(*(set(items) for items in constraints))
        if len(candidates) != 1:
            return None, True, {}
        evidence = {}
        for feature in features:
            if len(feature_phrases.get(feature, set())) < 2:
                continue
            label = (f'token:{feature[1]}' if feature[0] == 'token'
                     else f'bigram:{feature[1]} {feature[2]}')
            evidence[label] = sorted(feature_phrases[feature])
        return procedure_by_key[next(iter(candidates))], False, evidence

    def _diagnose_language_gaps(self, instruction: str) -> dict[str, list[str]]:
        """Report lexical evidence missing for a query without guessing meaning."""
        feature_phrases, feature_procedures, procedure_by_key = (
            self._ensure_lexical_feature_index())

        words = self._instruction_sequence(instruction)
        unknown_tokens = sorted(
            word for word in set(words)
            if not feature_phrases.get(('token', word)))
        weak_bigrams = sorted(
            f'{left} {right}' for left, right in set(zip(words, words[1:]))
            if len(feature_phrases.get(('bigram', left, right), ())) < 2
        )
        under_supported_tokens = sorted(
            word for word in set(words) - set(unknown_tokens)
            if len(feature_phrases.get(('token', word), ())) < 2
        )
        def conflicting_features(kind: str, features: set[tuple[str, ...]]) -> list[str]:
            conflicts = []
            for feature in sorted(features):
                behaviors = feature_procedures.get(feature, set())
                if len(behaviors) < 2:
                    continue
                labels = []
                for behavior in sorted(behaviors):
                    procedure = procedure_by_key[behavior]
                    labels.append(json.dumps(
                        _procedure_dict(procedure), sort_keys=True,
                        separators=(',', ':')))
                conflicts.append(f"{' '.join(feature[1:])}: "
                                 + ' versus '.join(labels))
            return conflicts

        conflicting_tokens = conflicting_features(
            'token', {('token', word) for word in set(words)})
        conflicting_bigrams = conflicting_features(
            'bigram', {('bigram', left, right)
                       for left, right in zip(words, words[1:])})
        gaps: dict[str, list[str]] = {}
        if unknown_tokens:
            gaps['unknown_tokens'] = unknown_tokens
        if under_supported_tokens:
            gaps['under_supported_tokens'] = under_supported_tokens
        if conflicting_tokens:
            gaps['conflicting_tokens'] = conflicting_tokens
        if conflicting_bigrams:
            gaps['conflicting_bigrams'] = conflicting_bigrams
        if weak_bigrams:
            gaps['weak_bigrams'] = weak_bigrams
        return gaps

    def _ensure_lexical_feature_index(self) -> tuple[dict, dict, dict]:
        """Build phrase, behavior and procedure postings once per memory state."""
        if self._lexical_feature_cache is None:
            feature_phrases: dict[tuple[str, ...], set[str]] = {}
            feature_procedures: dict[tuple[str, ...], set[tuple]] = {}
            procedure_by_key: dict[tuple, tuple[Step, ...]] = {}
            for phrase, procedure in self._procedures.items():
                behavior = _semantic_key(procedure)
                procedure_by_key[behavior] = procedure
                words = self._instruction_sequence(phrase)
                features = {('token', token) for token in words}
                features.update(('bigram', left, right)
                                for left, right in zip(words, words[1:]))
                for feature in features:
                    feature_phrases.setdefault(feature, set()).add(phrase)
                    feature_procedures.setdefault(feature, set()).add(behavior)
            self._lexical_feature_cache = (
                feature_phrases, feature_procedures, procedure_by_key)
        return self._lexical_feature_cache

    def _retrieve_rule_prior(
        self, instruction: str,
    ) -> tuple[tuple[Step, ...] | None, list[str]]:
        """Find one procedure already grounded in the instruction memory."""
        instruction = self._canonical_instruction_storage_key(
            self._clean_instruction(instruction))
        exact = self._procedures.get(instruction)
        if exact is not None:
            return exact, [instruction]

        parameterized, conflict, sources, _template, _trace = (
            self._retrieve_parameterized_procedure(instruction)
        )
        if parameterized is not None:
            return parameterized, sources
        if conflict:
            return None, []

        aligned, conflict, sources, _template = self._retrieve_aligned_phrase(instruction)
        if aligned is not None:
            return aligned, sources
        if conflict:
            return None, []

        contrastive, conflict, sources, _template = (
            self._retrieve_contrastive_slot(instruction))
        if contrastive is not None:
            return contrastive, sources
        if conflict:
            return None, []

        analogous, conflict, sources, _template = self._retrieve_analogical_frame(instruction)
        if analogous is not None:
            return analogous, sources
        if conflict:
            return None, []

        lexical, conflict, evidence = self._retrieve_grounded_procedure(instruction)
        if lexical is not None:
            return lexical, sorted({source for phrases in evidence.values()
                                   for source in phrases})
        if conflict:
            return None, []

        vsa, sources, _score, _margin = self._retrieve_vsa_procedure(instruction)
        return vsa, sources

    def _grounded_composition_connectives(
        self,
    ) -> dict[tuple[str, ...], tuple[tuple[tuple[str, str], ...], tuple[str, ...]]]:
        """Infer sequence connectives from compounds whose components are taught.

        A connective is licensed only after two distinct grounded component
        phrase pairs compose to the demonstrated compound behavior.
        """
        if self._composition_connective_cache is None:
            support: dict[
                tuple[str, ...], dict[tuple[str, str], set[str]]
            ] = {}
            for compound_phrase, compound_procedure in self._procedures.items():
                words = self._instruction_sequence(compound_phrase)
                if len(words) < 3:
                    continue
                compound_behavior = _semantic_key(compound_procedure)
                for left_end in range(1, len(words) - 1):
                    left_phrase = ' '.join(words[:left_end])
                    left_procedure = self._procedures.get(left_phrase)
                    if left_procedure is None:
                        continue
                    for right_start in range(left_end + 1, len(words)):
                        right_phrase = ' '.join(words[right_start:])
                        right_procedure = self._procedures.get(right_phrase)
                        if right_procedure is None:
                            continue
                        if _semantic_key(left_procedure + right_procedure) != compound_behavior:
                            continue
                        connective = tuple(words[left_end:right_start])
                        support.setdefault(connective, {}).setdefault(
                            (left_phrase, right_phrase), set()).add(compound_phrase)

            self._composition_connective_cache = {
                connective: (
                    tuple(sorted(contexts)),
                    tuple(sorted({phrase for sources in contexts.values()
                                  for phrase in sources})),
                )
                for connective, contexts in support.items()
                if len(contexts) >= 2
            }
        return self._composition_connective_cache

    def _retrieve_learned_composition(
        self, instruction: str,
    ) -> tuple[tuple[Step, ...] | None, bool, list[str], str | None]:
        """Compose up to four grounded instruction spans through a learned connective."""
        words = self._instruction_sequence(instruction)
        matches: dict[tuple, tuple[tuple[Step, ...], set[str], str]] = {}
        for connective, (_contexts, connective_sources) in (
                self._grounded_composition_connectives().items()):
            width = len(connective)
            boundaries = [
                start for start in range(1, len(words) - width)
                if tuple(words[start:start + width]) == connective
            ]
            if len(boundaries) > 12:
                # Keep separator parsing bounded even for pathological input.
                continue
            # A learned binary sequential connective can be applied
            # associatively to a bounded chain. Every clause still has to
            # retrieve its own grounded procedure; the connective alone never
            # licenses an unknown component.
            for separator_count in range(1, min(3, len(boundaries)) + 1):
                for separators in combinations(boundaries, separator_count):
                    clauses: list[str] = []
                    cursor = 0
                    valid = True
                    for start in separators:
                        if start < cursor:
                            valid = False
                            break
                        clauses.append(' '.join(words[cursor:start]))
                        cursor = start + width
                    if not valid:
                        continue
                    clauses.append(' '.join(words[cursor:]))
                    if len(clauses) > 4 or any(not clause for clause in clauses):
                        continue

                    resolved = [self._retrieve_rule_prior(clause)
                                for clause in clauses]
                    if any(procedure is None for procedure, _sources in resolved):
                        continue
                    procedure = tuple(
                        step for clause_procedure, _sources in resolved
                        for step in clause_procedure
                    )
                    behavior = _semantic_key(procedure)
                    sources = set(connective_sources)
                    for _clause_procedure, clause_sources in resolved:
                        sources.update(clause_sources)
                    template = f"learned_sequence:{' '.join(connective)}"
                    current = matches.get(behavior)
                    if current is None:
                        matches[behavior] = (procedure, sources, template)
                    else:
                        current[1].update(sources)
                        procedure_key = (len(procedure), _procedure_key(procedure))
                        current_key = (len(current[0]), _procedure_key(current[0]))
                        if procedure_key < current_key:
                            matches[behavior] = (procedure, current[1], current[2])

        if len(matches) == 1:
            procedure, sources, template = next(iter(matches.values()))
            return procedure, False, sorted(sources), template
        if len(matches) > 1:
            return None, True, [], None
        return None, False, [], None

    @staticmethod
    def _clean_values(values: Iterable[int]) -> list[int]:
        cleaned = list(values)
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in cleaned):
            raise TypeError('CRMS currently accepts integer lists only')
        return cleaned

    def _infer(self, examples: list[tuple[list[int], list[int]]]) -> list[tuple[Step, ...]]:
        """Search on CPU while reusing equivalent intermediate states.

        For two-step search, first-step outputs are computed once per rule and
        grouped by their joint result on all examples. Each distinct group is
        then passed through each possible second rule once. Fitting programs
        are grouped by an exact semantic summary for the built-in operation
        algebra, so syntactic variants with identical behavior do not create
        false ambiguity.
        """
        self._last_search_complete = True
        self._last_search_expansions = 0
        if self.max_composition_depth >= 3:
            return self._infer_composed(examples)

        fitting: list[tuple[Step, ...]] = []
        target = tuple(tuple(y) for _, y in examples)
        intermediate_groups: dict[tuple, tuple[list[list[int]], list[Step]]] = {}
        relational_filters = {'keep_greater_than_first',
                              'keep_less_than_first'}

        for first in self._steps:
            if self._last_search_expansions >= self.max_search_expansions:
                self._last_search_complete = False
                break
            self._last_search_expansions += 1
            states = [_apply_step(first, x) for x, _ in examples]
            signature = tuple(tuple(state) for state in states)
            if signature == target:
                fitting.append((first,))
            if self.max_composition_depth == 2:
                if first.operation in relational_filters:
                    # Relational filters can safely feed endpoint selection;
                    # other continuations remain outside the exact summary.
                    for terminal in self._steps:
                        if terminal.operation not in {'first', 'last'}:
                            continue
                        if self._last_search_expansions >= self.max_search_expansions:
                            self._last_search_complete = False
                            break
                        self._last_search_expansions += 1
                        if all(tuple(_apply_step(terminal, state)) == expected
                               for state, expected in zip(states, target)):
                            fitting.append((first, terminal))
                    if not self._last_search_complete:
                        break
                    continue
                if signature not in intermediate_groups:
                    intermediate_groups[signature] = (states, [])
                intermediate_groups[signature][1].append(first)

        if self.max_composition_depth == 2:
            groups = list(intermediate_groups.values())
            work = sum(
                sum(_position_filter_extension_allowed(first, second)
                    for first in first_steps for second in self._steps)
                for _states, first_steps in groups)
            if self._last_search_expansions + work > self.max_search_expansions:
                self._last_search_complete = False
            if not self._last_search_complete:
                unique: dict[tuple, tuple[Step, ...]] = {}
                for procedure in fitting:
                    behavior = _semantic_key(procedure)
                    current = unique.get(behavior)
                    rank = (len(procedure), _procedure_key(procedure))
                    if current is None or rank < (len(current), _procedure_key(current)):
                        unique[behavior] = procedure
                return list(unique.values())
            self._last_search_expansions += work
            if self.max_workers > 1 and work >= self.parallel_min_work:
                tasks = [(states, first_steps, self._steps, target)
                         for states, first_steps in groups]
                with ProcessPoolExecutor(max_workers=self.max_workers) as pool:
                    for matches in pool.map(_search_intermediate_group, tasks,
                                            chunksize=max(1, len(tasks) // (self.max_workers * 4))):
                        fitting.extend(matches)
            else:
                for states, first_steps in groups:
                    fitting.extend(_search_intermediate_group(
                        (states, first_steps, self._steps, target)))
        # Collapse procedures with identical behavior. Prefer the shortest,
        # then lexicographically stable encoding as the displayed procedure.
        unique: dict[tuple, tuple[Step, ...]] = {}
        for procedure in fitting:
            behavior = _semantic_key(procedure)
            current = unique.get(behavior)
            rank = (len(procedure), _procedure_key(procedure))
            if current is None or rank < (len(current), _procedure_key(current)):
                unique[behavior] = procedure
        return list(unique.values())

    def _infer_composed(
        self, examples: list[tuple[list[int], list[int]]],
    ) -> list[tuple[Step, ...]]:
        """Breadth-first search behaviors while sharing observed state signatures.

        Distinct programs can produce the same outputs on the supplied examples
        while still representing different behaviors on unseen inputs. Keep all
        such program behaviors for ambiguity checking, but store each observed
        state signature once and apply each next operation once per signature.
        """
        target = tuple(tuple(y) for _, y in examples)
        initial_states = tuple(tuple(x) for x, _ in examples)
        identity = _semantic_key(())
        state_pool = [initial_states]
        frontier: dict[int, list[tuple[tuple[Step, ...], tuple]]] = {
            0: [((), identity)]
        }
        # Keep the empty program as a search starting point, but do not count
        # it as a candidate: a non-empty identity program (for example,
        # reverse twice) must remain learnable from identity demonstrations.
        visited: set[tuple[tuple, tuple[bool, bool, bool]]] = set()
        fitting: dict[tuple, tuple[Step, ...]] = {}
        expansions = 0
        exhausted = False
        can_sum = any(step.operation == 'sum_values' for step in self._steps)

        for _depth in range(1, self.max_composition_depth + 1):
            next_state_pool: list[tuple[tuple[int, ...], ...]] = []
            next_state_ids: dict[tuple[tuple[int, ...], ...], int] = {}
            next_frontier: dict[
                int, list[tuple[tuple[Step, ...], tuple]]
            ] = {}
            for state_id, prefixes in frontier.items():
                states = state_pool[state_id]
                # These constraints depend only on a prefix and can be reused
                # for every operation considered at this state.
                procedure_metadata = [
                    (procedure, behavior,
                     _sequence_extension_signature(procedure))
                    for procedure, behavior in prefixes
                ]
                for step in self._steps:
                    eligible_procedures = []
                    for procedure, behavior, signature in procedure_metadata:
                        extended_signature = _extend_search_signature(
                            signature, step)
                        if extended_signature is not None:
                            eligible_procedures.append((
                                procedure, behavior, extended_signature))
                    if not eligible_procedures:
                        continue
                    output_states = tuple(
                        tuple(_apply_step(step, state)) for state in states
                    )
                    next_state_id = next_state_ids.get(output_states)
                    if next_state_id is None:
                        next_state_id = len(next_state_pool)
                        next_state_ids[output_states] = next_state_id
                        next_state_pool.append(output_states)
                    fits = output_states == target
                    steps_after = self.max_composition_depth - _depth
                    can_still_fit = fits or (
                        steps_after > 0
                        and all(_list_length_can_reach(
                            len(state), len(expected), steps_after,
                            self.max_repeat, can_sum=can_sum)
                            for state, expected in zip(output_states, target))
                    )
                    # The work limit measures distinct semantic search states,
                    # after exact canonicalization and a sound length bound,
                    # not syntactic extensions or prefixes that cannot reach
                    # any demonstrated output shape. Deduplicate before
                    # charging the budget so exact rewrites reduce search work.
                    extensions: list[
                        tuple[tuple[Step, ...], tuple,
                              tuple[bool, bool, bool]]
                    ] = []
                    batch_behaviors: set[
                        tuple[tuple, tuple[bool, bool, bool]]] = set()
                    for procedure, parent_behavior, signature in eligible_procedures:
                        extended = procedure + (step,)
                        behavior = _semantic_key(extended)
                        # The same extensional behavior can have different
                        # legal continuations under the bounded grammar (for
                        # example, positional-filter prefixes). Preserve one
                        # representative per behavior and extension state.
                        search_state = (
                            behavior, signature)
                        if search_state in visited or search_state in batch_behaviors:
                            continue
                        batch_behaviors.add(search_state)
                        if not can_still_fit:
                            # This behavior cannot reach the demonstrated
                            # output lengths under any remaining suffix.
                            visited.add(search_state)
                            continue
                        extensions.append((extended, search_state, signature))
                    if expansions + len(extensions) > self.max_search_expansions:
                        exhausted = True
                        break
                    expansions += len(extensions)
                    for extended, search_state, signature in extensions:
                        visited.add(search_state)
                        behavior = search_state[0]
                        if fits:
                            fitting[behavior] = extended
                        if _depth == self.max_composition_depth:
                            continue
                        # The extension signature already limits any step
                        # after a first-relative filter to endpoint operations.
                        # Keep the filter-ending prefix available so it can
                        # acquire its allowed endpoint step on the next depth.
                        next_frontier.setdefault(next_state_id, []).append(
                            (extended, behavior))
                if exhausted:
                    break
            if exhausted:
                break
            state_pool = next_state_pool
            frontier = next_frontier
        self._last_search_complete = not exhausted
        self._last_search_expansions = expansions
        return list(fitting.values())

    def _propose_out_of_range_rules(
        self, examples: list[tuple[list[int], list[int]]],
    ) -> list[tuple[Step, ...]]:
        """Suggest simple exact fits just outside configured parameter ranges.

        Suggestions are explanatory only: `teach` never commits them. Every
        proposal must reproduce every supplied pair exactly, and a caller
        should seek additional/held-out evidence before extending the library.
        """
        proposals: dict[tuple, tuple[Step, ...]] = {}

        differences = [y - x for inputs, outputs in examples
                       for x, y in zip(inputs, outputs)]
        if (all(len(inputs) == len(outputs) for inputs, outputs in examples)
                and differences and len(set(differences)) == 1):
            k = differences[0]
            if k and abs(k) > self.max_add:
                procedure = (Step('add_k', {'k': k}),)
                proposals[_procedure_key(procedure)] = procedure

        ratios: set[int] = set()
        scale_fits = True
        has_scale_information = False
        for inputs, outputs in examples:
            if len(inputs) != len(outputs):
                scale_fits = False
                break
            for x, y in zip(inputs, outputs):
                if x == 0:
                    if y != 0:
                        scale_fits = False
                        break
                    continue
                if y % x:
                    scale_fits = False
                    break
                has_scale_information = True
                ratios.add(y // x)
            if not scale_fits:
                break
        if scale_fits and has_scale_information and len(ratios) == 1:
            k = next(iter(ratios))
            in_range = (-self.max_scale <= k <= -1
                        or 2 <= k <= self.max_scale)
            if k != 0 and k != 1 and not in_range:
                procedure = (Step('scale_k', {'k': k}),)
                proposals[_procedure_key(procedure)] = procedure

        # A modulus is grounded only when the demonstrations retain a
        # nonzero value and remove at least one input value. Search a bounded
        # interval above the configured grammar limit; every proposal must
        # reproduce all examples exactly.
        nonzero_outputs = [abs(value) for _inputs, outputs in examples
                           for value in outputs if value != 0]
        filtered_any = any(inputs != outputs for inputs, outputs in examples)
        if nonzero_outputs and filtered_any:
            modulus_limit = min(
                min(nonzero_outputs), self.max_modulus + 32)
            for modulus in range(self.max_modulus + 1, modulus_limit + 1):
                procedure = (Step('keep_multiples_k', {'k': modulus}),)
                if all(_apply_procedure(procedure, inputs) == outputs
                       for inputs, outputs in examples):
                    proposals[_procedure_key(procedure)] = procedure

        repeat_counts: set[int] = set()
        repeat_fits = True
        for inputs, outputs in examples:
            if not inputs:
                if outputs:
                    repeat_fits = False
                    break
                continue
            if len(outputs) % len(inputs):
                repeat_fits = False
                break
            count = len(outputs) // len(inputs)
            if count < 2 or outputs != [value for value in inputs
                                        for _ in range(count)]:
                repeat_fits = False
                break
            repeat_counts.add(count)
        if repeat_fits and len(repeat_counts) == 1:
            count = next(iter(repeat_counts))
            if count > self.max_repeat:
                procedure = (Step('repeat_each_k', {'k': count}),)
                proposals[_procedure_key(procedure)] = procedure

        # Rotation is periodic in each input length. Search only a bounded
        # neighborhood beyond the configured range and retain every exact fit
        # there; multiple residues remain advisory alternatives, not intent.
        maximum_length = max((len(inputs) for inputs, _outputs in examples),
                             default=0)
        rotation_margin = min(32, max(4, 2 * maximum_length))
        rotation_limit = self.max_rotation + rotation_margin
        for k in range(-rotation_limit, rotation_limit + 1):
            if k == 0 or abs(k) <= self.max_rotation:
                continue
            procedure = (Step('rotate_left_k', {'k': k}),)
            if all(_apply_procedure(procedure, inputs) == outputs
                   for inputs, outputs in examples):
                proposals[_procedure_key(procedure)] = procedure

        return [proposals[key] for key in sorted(proposals)]

    def _propose_next_depth_rules(
        self, examples: list[tuple[list[int], list[int]]],
    ) -> list[tuple[Step, ...]]:
        """Find exact advisory fits one step beyond the configured depth.

        Search state and configuration are restored afterward. Incomplete
        searches produce no proposals, and this method never commits a rule.
        """
        if self.max_composition_depth >= 4:
            return []
        prior_depth = self.max_composition_depth
        prior_complete = self._last_search_complete
        prior_expansions = self._last_search_expansions
        try:
            self.max_composition_depth = prior_depth + 1
            proposals = self._infer(examples)
            complete = self._last_search_complete
        finally:
            self.max_composition_depth = prior_depth
            self._last_search_complete = prior_complete
            self._last_search_expansions = prior_expansions
        if not complete:
            return []
        return [procedure for procedure in proposals
                if len(procedure) == prior_depth + 1]

    def _candidate_space_signature(self) -> tuple:
        return (self.max_composition_depth, self.max_search_expansions,
                tuple((step.operation, tuple(sorted(step.parameters.items())))
                      for step in self._steps))

    def _candidate_space_signature_record(self) -> dict[str, Any]:
        return {
            'max_composition_depth': self.max_composition_depth,
            'max_search_expansions': self.max_search_expansions,
            'steps': [{'operation': step.operation,
                       'parameters': dict(step.parameters)}
                      for step in self._steps],
        }

    def _candidate_space_for_examples(
        self, instruction: str,
        examples: list[tuple[list[int], list[int]]],
    ) -> list[tuple[Step, ...]]:
        """Search once, then filter a complete version space incrementally."""
        signature = self._candidate_space_signature()
        snapshot = tuple((tuple(inputs), tuple(outputs))
                         for inputs, outputs in examples)
        cached = self._candidate_space_cache.get(instruction)
        if (cached is not None and cached[0] == signature
                and len(cached[1]) <= len(snapshot)
                and snapshot[:len(cached[1])] == cached[1]):
            self._candidate_space_cache.move_to_end(instruction)
            prior_examples, prior_candidates = cached[1], cached[2]
            additions = snapshot[len(prior_examples):]
            candidates = [procedure for procedure in prior_candidates
                          if all(_apply_procedure(procedure, list(inputs))
                                 == list(outputs)
                                 for inputs, outputs in additions)]
            self._last_search_complete = True
            self._last_search_expansions = 0
            if len(candidates) <= _CANDIDATE_CACHE_MAX_PROCEDURES:
                self._candidate_space_cache[instruction] = (
                    signature, snapshot, tuple(candidates))
                self._candidate_space_cache.move_to_end(instruction)
            else:
                self._candidate_space_cache.pop(instruction, None)
            return candidates

        candidates = self._infer(examples)
        if (self._last_search_complete
                and len(candidates) <= _CANDIDATE_CACHE_MAX_PROCEDURES):
            self._candidate_space_cache[instruction] = (
                signature, snapshot, tuple(candidates))
            self._candidate_space_cache.move_to_end(instruction)
            while len(self._candidate_space_cache) > _CANDIDATE_CACHE_MAX_INSTRUCTIONS:
                self._candidate_space_cache.popitem(last=False)
        else:
            self._candidate_space_cache.pop(instruction, None)
        return candidates

    def _mixed_position_filter_candidates(
        self, examples: list[tuple[list[int], list[int]]],
    ) -> list[tuple[Step, ...]]:
        """Check the small two-step value-filter/position-filter family.

        This family stays outside general composition search because it grows
        the broader version space. When examples include a non-empty output,
        check it directly so a rule excluded by that gate cannot be displaced
        by a narrower, falsely unique candidate.
        """
        if (self.max_composition_depth < 2
                or not any(outputs for _inputs, outputs in examples)):
            return []
        positional = (Step('keep_even_positions', {}),
                      Step('keep_odd_positions', {}))
        candidates = {}
        family = [
            (Step('keep_multiples_k', {'k': modulus}), position)
            for modulus in range(3, self.max_modulus + 1)
            for position in positional
        ]
        family.extend((position, Step('keep_multiples_k', {'k': modulus}))
                      for modulus in range(3, self.max_modulus + 1)
                      for position in positional)
        work = 2 * len(family) * len(examples)
        if self._last_search_expansions + work > self.max_search_expansions:
            self._last_search_complete = False
            self._last_search_expansions = self.max_search_expansions
            return []
        self._last_search_expansions += work
        for procedure in family:
            if all(_apply_procedure(procedure, inputs) == outputs
                   for inputs, outputs in examples):
                candidates[_semantic_key(procedure)] = procedure
        return [candidates[key] for key in sorted(candidates)]

    def teach(self, instruction: str,
              examples: Iterable[tuple[Iterable[int], Iterable[int]]],
              *, replace: bool = False,
              _use_language_prior: bool = True) -> LearnResult:
        """Add demonstrations, infer a procedure, and store only a unique fit.

        Each example is `(input_values, expected_output_values)`. If evidence
        is ambiguous or outside the rule library, no rule is committed.
        """
        key = self._canonical_instruction_storage_key(
            self._clean_instruction(instruction))
        supplied = [(self._clean_values(x), self._clean_values(y)) for x, y in examples]
        if not supplied:
            return LearnResult('need_examples', key, 0, 0,
                               request='Please provide an input list and its intended output.')
        if replace:
            self._examples[key] = []
            self._procedures.pop(key, None)
            self._no_fit_records.pop(key, None)
            self._candidate_space_cache.pop(key, None)
            self._ambiguity_probe_cache.pop(key, None)
            self._invalidate_language_indexes()
        prior, prior_sources = (
            self._retrieve_rule_prior(key) if _use_language_prior else (None, []))
        evidence = self._examples.setdefault(key, [])
        evidence.extend(supplied)
        candidates = self._candidate_space_for_examples(key, evidence)
        if self._last_search_complete:
            known_behaviors = {_semantic_key(procedure) for procedure in candidates}
            candidates.extend(
                procedure for procedure in self._mixed_position_filter_candidates(evidence)
                if _semantic_key(procedure) not in known_behaviors)
        if not self._last_search_complete:
            self._procedures.pop(key, None)
            self._no_fit_records.pop(key, None)
            self._ambiguity_probe_cache.pop(key, None)
            self._invalidate_language_indexes()
            self._save_if_configured()
            return LearnResult(
                'search_incomplete', key, len(evidence), len(candidates),
                request=('The bounded procedure search reached its work limit. '
                         'No result was committed; increase the search budget '
                         'or provide examples that narrow the candidate space.'),
                message=(f'Search stopped after {self._last_search_expansions} '
                         f'expansions (limit {self.max_search_expansions}) '
                         'before all procedures within the configured depth '
                         'were evaluated.'),
                search_complete=False,
                search_expansions=self._last_search_expansions)
        prior_used = False
        if len(candidates) > 1 and prior is not None:
            prior_behavior = _semantic_key(prior)
            grounded_candidates = [candidate for candidate in candidates
                                   if _semantic_key(candidate) == prior_behavior]
            if grounded_candidates:
                candidates = grounded_candidates
                prior_used = True
        if len(candidates) == 1:
            self._procedures[key] = candidates[0]
            self._no_fit_records.pop(key, None)
            self._ambiguity_probe_cache.pop(key, None)
            self._invalidate_language_indexes()
            self._save_if_configured()
            return LearnResult('learned', key, len(evidence), 1,
                               procedure=_procedure_dict(candidates[0]),
                               message=(
                                   'Examples fit one procedure after grounded language evidence narrowed the candidates.'
                                   if prior_used else
                                   'One procedure fits all stored examples.'
                               ),
                               evidence_phrases=sorted(set(prior_sources))
                               if prior_used else None)
        self._procedures.pop(key, None)
        self._no_fit_records.pop(key, None)
        self._invalidate_language_indexes()
        self._save_if_configured()
        if candidates:
            probe, outputs = _contrastive_probe(candidates)
            snapshot = tuple((tuple(inputs), tuple(outputs))
                             for inputs, outputs in evidence)
            if probe is not None and outputs is not None:
                self._ambiguity_probe_cache[key] = (
                    self._candidate_space_signature(), snapshot,
                    list(probe), [list(output) for output in outputs])
            else:
                self._ambiguity_probe_cache.pop(key, None)
            while len(self._ambiguity_probe_cache) > _CANDIDATE_CACHE_MAX_INSTRUCTIONS:
                self._ambiguity_probe_cache.pop(next(iter(self._ambiguity_probe_cache)))
            if probe is None:
                request = ('Please provide another example where the remaining '
                           'candidate procedures produce different outputs.')
            else:
                request = (f'Please provide the intended output for input {probe}. '
                           f'{_format_candidate_outputs(outputs)}')
            return LearnResult('need_more_examples', key, len(evidence), len(candidates),
                               request=request,
                               message='Several behaviorally distinct procedures still fit; nothing was committed.',
                               contrastive_input=probe,
                               candidate_outputs=outputs,
                               candidate_procedures=[_procedure_dict(proc) for proc in candidates])
        out_of_range_proposals = self._propose_out_of_range_rules(evidence)
        proposals_by_key = {
            _procedure_key(procedure): procedure
            for procedure in out_of_range_proposals
        }
        proposals_by_key.update({
            _procedure_key(procedure): procedure
            for procedure in self._propose_next_depth_rules(evidence)
        })
        proposals = [proposals_by_key[key]
                     for key in sorted(proposals_by_key)]
        self._ambiguity_probe_cache.pop(key, None)
        proposal_probe = None
        proposal_outputs = None
        if 1 < len(proposals) <= 64:
            proposal_probe, proposal_outputs = _contrastive_probe(proposals)
        if proposal_probe is not None and proposal_outputs is not None:
            request = (
                f'These advisory procedures fit the examples but are not learned. '
                f'Please provide the intended output for input {proposal_probe}. '
                f'{_format_candidate_outputs(proposal_outputs)}')
        else:
            request = (
                'Please check the examples, or widen the configured '
                'operation/parameter bounds if the behavior is outside them.')
        self._remember_no_fit(key, evidence)
        self._save_if_configured()
        return LearnResult('no_fit', key, len(evidence), 0,
                           request=request,
                           message=('No procedure within the configured depth and operation '
                                    'library fits all examples.' +
                                    (' Exact examples suggest an out-of-range parameterized '
                                     'candidate; it has not been learned and needs more evidence.'
                                     if out_of_range_proposals else '') +
                                    (' A deeper exact procedure is also suggested; increase '
                                     'the configured search depth and validate it before use.'
                                     if any(len(item) > self.max_composition_depth
                                            for item in proposals) else '')),
                           proposed_procedures=[_procedure_dict(procedure)
                                                for procedure in proposals] or None,
                           contrastive_input=proposal_probe,
                           candidate_outputs=proposal_outputs)

    def retry(self, instruction: str) -> LearnResult:
        """Re-run synthesis over stored demonstrations under current bounds."""
        key = self._canonical_instruction_storage_key(
            self._clean_instruction(instruction))
        examples = self._examples.get(key)
        if not examples:
            return LearnResult(
                'need_examples', key, 0, 0,
                request='There are no stored demonstrations for this instruction.')
        snapshot = [(list(inputs), list(outputs))
                    for inputs, outputs in examples]
        return self.teach(key, snapshot, replace=True)

    def predict(self, instruction: str, values: Iterable[int]) -> Prediction:
        key = self._clean_instruction(instruction)
        requested_key = key
        xs = self._clean_values(values)
        canonical_sources = self._canonical_instruction_sources().get(
            casefold_nfc(key), ())
        if len(canonical_sources) > 1:
            canonical_procedures = [self._procedures.get(phrase)
                                    for phrase in canonical_sources]
            behaviors = {_semantic_key(procedure)
                         for procedure in canonical_procedures
                         if procedure is not None}
            if (any(procedure is None for procedure in canonical_procedures)
                    or len(behaviors) != 1):
                has_examples = any(phrase in self._examples
                                   for phrase in canonical_sources)
                return Prediction(
                    'need_more_examples' if has_examples else 'need_examples',
                    None, requested_key,
                    request=('Canonically equivalent instruction spellings have '
                             'conflicting or unresolved learned rules. Please '
                             'clarify the intended rule or resolve the stored examples.'),
                    message=('Equivalent Unicode spellings map to multiple '
                             'learned or unresolved procedures; no rule was selected.'),
                    evidence_phrases=list(canonical_sources))
            if key not in canonical_sources:
                key = canonical_sources[0]
        elif canonical_sources:
            # Preserve the original stored spelling while letting its
            # canonically equivalent query reach the exact phrase association.
            key = canonical_sources[0]
        procedure = self._procedures.get(key)
        if procedure is not None:
            return Prediction('ok', _apply_procedure(procedure, xs), requested_key,
                              procedure=_procedure_dict(procedure),
                              message='Applied the stored procedure.',
                              evidence_phrases=list(canonical_sources or (key,)),
                              matched_tokens=[],
                              matched_bigrams=[], matched_templates=[])
        if key in self._examples:
            cached_probe = self._ambiguity_probe_cache.get(key)
            snapshot = tuple((tuple(inputs), tuple(outputs))
                             for inputs, outputs in self._examples[key])
            if (cached_probe is not None
                    and cached_probe[0] == self._candidate_space_signature()
                    and cached_probe[1] == snapshot):
                probe, outputs = cached_probe[2], cached_probe[3]
                return Prediction(
                    'need_more_examples', None, requested_key,
                    request=(f'Please provide the intended output for input {probe}. '
                             f'{_format_candidate_outputs(outputs)}'),
                    message=('Stored examples remain ambiguous; this contrastive '
                             'input separates the remaining procedures.'),
                    evidence_phrases=list(canonical_sources or (key,)),
                    contrastive_input=list(probe),
                    candidate_outputs=[list(output) for output in outputs])
            request = ('Please provide a contrastive example for this instruction; '
                       'its stored demonstrations do not identify one procedure.')
            return Prediction('need_more_examples', None, requested_key, request=request,
                              message='Stored examples remain ambiguous or do not fit the rule library.')

        # Composition is explicit syntax. Each part can use an exact taught
        # phrase or lexical associations grounded by multiple demonstrations.
        parts = [part.strip() for part in key.split(', then ')]
        explicit_composed = None
        explicit_sources: list[str] = []
        explicit_matched_tokens: set[str] = set()
        explicit_matched_bigrams: set[str] = set()
        explicit_matched_templates: set[str] = set()
        explicit_retrieval_evidence: list[dict[str, Any]] = []
        if len(parts) > 1 and all(parts):
            resolved = []
            missing = None
            lexical_conflict = False
            evidence_phrases = []
            matched_tokens = set()
            matched_bigrams = set()
            matched_templates = set()
            retrieval_evidence = []
            for part in parts:
                part_procedure = self._procedures.get(part)
                if part_procedure is not None:
                    evidence_phrases.append(part)
                elif part not in self._examples:
                    (part_parameterized, part_parameter_conflict,
                     part_parameter_sources, part_parameter_template,
                     part_parameter_evidence) = (
                        self._retrieve_parameterized_procedure(part))
                    (part_aligned, part_aligned_conflict, part_aligned_sources,
                     part_aligned_template) = self._retrieve_aligned_phrase(part)
                    (part_contrastive, part_contrastive_conflict,
                     part_contrastive_sources, part_contrastive_template) = (
                        self._retrieve_contrastive_slot(part))
                    (part_analogous, part_analogy_conflict,
                     part_analogy_sources, part_analogy_template) = (
                        self._retrieve_analogical_frame(part))
                    (part_learned, part_lexical_conflict,
                     part_lexical_evidence) = self._retrieve_grounded_procedure(part)
                    (part_vsa_ranked, part_vsa_score, part_vsa_margin) = (
                        self._retrieve_vsa_candidates(part))
                    part_vsa = None
                    part_vsa_sources = []
                    if (part_vsa_ranked
                            and part_vsa_score >= self.vsa_min_similarity
                            and part_vsa_margin >= self.vsa_min_margin):
                        part_vsa, part_vsa_source = (
                            part_vsa_ranked[0][2], part_vsa_ranked[0][1])
                        part_vsa_sources = [part_vsa_source]

                    part_candidates = [candidate for candidate in (
                        part_parameterized, part_aligned, part_contrastive,
                        part_analogous, part_learned, part_vsa)
                        if candidate is not None]
                    part_behaviors = {_semantic_key(candidate)
                                      for candidate in part_candidates}
                    if len(part_behaviors) > 1:
                        lexical_conflict = True
                    else:
                        lexical_conflict = lexical_conflict or any((
                            part_parameter_conflict, part_aligned_conflict,
                            part_contrastive_conflict, part_analogy_conflict,
                            part_lexical_conflict))
                        if (part_parameterized is not None):
                            part_procedure = part_parameterized
                            evidence_phrases.extend(part_parameter_sources)
                            matched_templates.add(part_parameter_template)
                            retrieval_evidence.extend(part_parameter_evidence)
                        elif not part_parameter_conflict and part_aligned is not None:
                            part_procedure = part_aligned
                            evidence_phrases.extend(part_aligned_sources)
                            matched_templates.add(part_aligned_template)
                        elif (not part_parameter_conflict and not part_aligned_conflict
                              and part_contrastive is not None):
                            part_procedure = part_contrastive
                            evidence_phrases.extend(part_contrastive_sources)
                            matched_templates.add(part_contrastive_template)
                        elif (not part_parameter_conflict and not part_aligned_conflict
                              and not part_contrastive_conflict
                              and part_analogous is not None):
                            part_procedure = part_analogous
                            evidence_phrases.extend(part_analogy_sources)
                            matched_templates.add(part_analogy_template)
                        elif (not part_parameter_conflict and not part_aligned_conflict
                              and not part_contrastive_conflict
                              and not part_analogy_conflict and part_learned is not None):
                            part_procedure = part_learned
                            for sources in part_lexical_evidence.values():
                                evidence_phrases.extend(sources)
                            matched_tokens.update(
                                label[len('token:'):] for label in part_lexical_evidence
                                if label.startswith('token:'))
                            matched_bigrams.update(
                                label[len('bigram:'):] for label in part_lexical_evidence
                                if label.startswith('bigram:'))
                        elif (not part_parameter_conflict and not part_aligned_conflict
                              and not part_contrastive_conflict
                              and not part_analogy_conflict and not part_lexical_conflict
                              and part_vsa is not None):
                            part_procedure = part_vsa
                            evidence_phrases.extend(part_vsa_sources)
                            matched_templates.add(
                                f'vsa:alpha={self.vsa_alpha:g},score={part_vsa_score:.3f}')
                if part_procedure is None:
                    missing = part
                    break
                resolved.append(part_procedure)
            if missing is None:
                explicit_composed = tuple(
                    step for part_procedure in resolved
                    for step in part_procedure)
                explicit_sources = sorted(set(evidence_phrases))
                explicit_matched_tokens = matched_tokens
                explicit_matched_bigrams = matched_bigrams
                explicit_matched_templates = matched_templates
                explicit_retrieval_evidence = retrieval_evidence
            examples = self._examples.get(missing, [])
            if missing is not None:
                request = (f'Please provide an input list and its intended output for '
                           f'the instruction part: {missing!r}.')
                return Prediction('need_more_examples' if examples else 'need_examples',
                                  None, key, request=request,
                                  message=(f'Learned lexical or positional evidence does not identify one procedure for {missing!r}.'
                                           if lexical_conflict else
                                           f'No grounded procedure is available for {missing!r}.'))

        composed, composition_conflict, composition_sources, composition_template = (
            self._retrieve_learned_composition(key)
        )

        # Evaluate every grounded route for a novel phrase before allowing
        # dispatch order to choose among them. A high-priority route may be
        # locally well-supported while a second independent route supports a
        # different behavior; that is evidence to ask, not a reason to guess.
        (parameterized, parameter_conflict, parameter_sources,
         parameter_template, parameter_evidence) = (
            self._retrieve_parameterized_procedure(key)
            if key not in self._examples and not composition_conflict
            else (None, composition_conflict, [], None, [])
        )
        aligned, aligned_conflict, aligned_sources, aligned_template = (
            self._retrieve_aligned_phrase(key)
            if key not in self._examples
            else (None, False, [], None)
        )
        contrastive, contrastive_conflict, contrastive_sources, contrastive_template = (
            self._retrieve_contrastive_slot(key)
            if key not in self._examples
            else (None, False, [], None)
        )
        analogous, analogy_conflict, analogy_sources, analogy_template = (
            self._retrieve_analogical_frame(key)
            if key not in self._examples
            else (None, False, [], None)
        )
        learned, lexical_conflict, lexical_evidence = (
            self._retrieve_grounded_procedure(key)
            if key not in self._examples
            else (None, False, {})
        )
        vsa_ranked, vsa_score, vsa_margin = self._retrieve_vsa_candidates(key)
        vsa_procedure = None
        vsa_sources = []
        if (vsa_ranked and vsa_score >= self.vsa_min_similarity
                and vsa_margin >= self.vsa_min_margin):
            vsa_procedure, vsa_source = vsa_ranked[0][2], vsa_ranked[0][1]
            vsa_sources = [vsa_source]

        route_candidates = [
            (name, procedure, sources, template)
            for name, procedure, sources, template in (
                ('explicit sequence composition', explicit_composed,
                 explicit_sources, 'explicit_sequence:comma_then'
                 if explicit_composed is not None else None),
                ('learned composition', composed, composition_sources,
                 composition_template),
                ('numeric parameter', parameterized, parameter_sources, parameter_template),
                ('aligned phrase', aligned, aligned_sources, aligned_template),
                ('contrastive slot', contrastive, contrastive_sources, contrastive_template),
                ('positional analogy', analogous, analogy_sources, analogy_template),
                ('lexical features', learned,
                 sorted({source for sources in lexical_evidence.values()
                         for source in sources}), None),
                ('VSA fallback', vsa_procedure, vsa_sources,
                 f'vsa:alpha={self.vsa_alpha:g}' if vsa_procedure else None),
            ) if procedure is not None
        ]
        route_behaviors: dict[tuple, tuple[str, tuple[Step, ...]]] = {}
        for name, candidate, _sources, _template in route_candidates:
            behavior = _semantic_key(candidate)
            route_behaviors.setdefault(behavior, (name, candidate))
        if len(route_behaviors) > 1:
            candidates = [entry[1] for entry in route_behaviors.values()]
            probe, outputs = _contrastive_probe(candidates) if len(candidates) > 1 else (None, None)
            sources = sorted({source for _, _, route_sources, _ in route_candidates
                              for source in route_sources})
            templates = sorted({template for _, _, _, template in route_candidates
                                if template})
            candidate_routes_by_behavior: dict[tuple, dict[str, Any]] = {}
            for name, candidate, route_sources, template in route_candidates:
                behavior = _semantic_key(candidate)
                alternative = candidate_routes_by_behavior.setdefault(
                    behavior,
                    {'procedure': _procedure_dict(candidate), 'routes': [],
                     'probe_output': (_apply_procedure(candidate, probe)
                                      if probe is not None else None)})
                alternative['routes'].append({
                    'name': name,
                    'evidence_phrases': sorted(set(route_sources)),
                    'matched_template': template,
                })
            candidate_routes = list(candidate_routes_by_behavior.values())
            for alternative in candidate_routes:
                alternative['routes'].sort(
                    key=lambda route: (route['name'], route['evidence_phrases'],
                                       route['matched_template'] or ''))
            if probe is not None and outputs is not None:
                request = (f'Grounded retrieval routes support competing rules. '
                           f'Please provide the intended output for input {probe}. '
                           f'{_format_candidate_outputs(outputs)}')
            else:
                request = ('Grounded retrieval evidence is ambiguous. Please provide '
                           'an input and its intended output for this instruction.')
            return Prediction(
                'need_more_examples' if key in self._examples else 'need_examples',
                None, key, request=request,
                message=('Independent grounded retrieval routes disagree or remain '
                         'ambiguous; no route was selected.'),
                evidence_phrases=sources,
                matched_templates=templates,
                retrieval_evidence=(parameter_evidence or None),
                contrastive_input=probe,
                candidate_outputs=outputs,
                candidate_routes=candidate_routes,
            )

        if composition_conflict and route_candidates:
            return Prediction(
                'need_more_examples' if key in self._examples else 'need_examples',
                None, key,
                request=(
                    'The learned sequence-composition route has unresolved '
                    'competing parses. Please provide '
                    'an input list and the intended output before this instruction '
                    'can be applied.'),
                message=('The composition route is internally ambiguous; no '
                         'other route was selected to override it.'),
                evidence_phrases=sorted({
                    source for _, _, sources, _ in route_candidates
                    for source in sources}),
                matched_templates=sorted({
                    template for _, _, _, template in route_candidates
                    if template}),
            )

        if composed is not None:
            return Prediction(
                'ok', _apply_procedure(composed, xs), key,
                procedure=_procedure_dict(composed),
                message='Composed grounded instruction spans using a learned sequence connective.',
                evidence_phrases=composition_sources,
                matched_tokens=[], matched_bigrams=[],
                matched_templates=[composition_template],
            )

        if explicit_composed is not None:
            return Prediction(
                'ok', _apply_procedure(explicit_composed, xs), key,
                procedure=_procedure_dict(explicit_composed),
                message='Applied procedures grounded by learned instruction phrases.',
                evidence_phrases=explicit_sources,
                matched_tokens=sorted(explicit_matched_tokens),
                matched_bigrams=sorted(explicit_matched_bigrams),
                matched_templates=sorted(explicit_matched_templates),
                retrieval_evidence=explicit_retrieval_evidence or None,
            )

        # Exact phrases were checked above. For a novel phrase, reuse a rule
        # only if repeated lexical evidence leaves exactly one procedure in the
        # intersection of the query's candidate sets.
        if parameterized is not None:
            return Prediction('ok', _apply_procedure(parameterized, xs), key,
                              procedure=_procedure_dict(parameterized),
                              message='Applied a numeric parameter grounded by a learned phrase template.',
                              evidence_phrases=parameter_sources,
                              matched_tokens=[], matched_bigrams=[],
                              matched_templates=[parameter_template],
                              retrieval_evidence=parameter_evidence)

        if aligned is not None:
            return Prediction('ok', _apply_procedure(aligned, xs), key,
                              procedure=_procedure_dict(aligned),
                              message='Applied a procedure from an aligned, example-grounded phrase pattern.',
                              evidence_phrases=aligned_sources,
                              matched_tokens=[], matched_bigrams=[],
                              matched_templates=[aligned_template])

        if contrastive is not None:
            return Prediction(
                'ok', _apply_procedure(contrastive, xs), key,
                procedure=_procedure_dict(contrastive),
                message='Applied a rule from a contrastive, example-grounded word slot.',
                evidence_phrases=contrastive_sources,
                matched_tokens=[], matched_bigrams=[],
                matched_templates=[contrastive_template])

        if analogous is not None:
            return Prediction('ok', _apply_procedure(analogous, xs), key,
                              procedure=_procedure_dict(analogous),
                              message=('Applied a procedure through a positional analogy '
                                       'grounded by behaviorally equivalent cases.'),
                              evidence_phrases=analogy_sources,
                              matched_tokens=[], matched_bigrams=[],
                              matched_templates=[analogy_template])

        if learned is not None:
            return Prediction('ok', _apply_procedure(learned, xs), key,
                              procedure=_procedure_dict(learned),
                              message='Applied a procedure grounded by shared words and word pairs.',
                              evidence_phrases=sorted({source for sources in lexical_evidence.values()
                                                       for source in sources}),
                              matched_tokens=sorted(
                                  label[len('token:'):] for label in lexical_evidence
                                  if label.startswith('token:')),
                              matched_bigrams=sorted(
                                  label[len('bigram:'):] for label in lexical_evidence
                                  if label.startswith('bigram:')),
                              matched_templates=[])

        if not (lexical_conflict or parameter_conflict or aligned_conflict
                or contrastive_conflict or analogy_conflict):
            if vsa_procedure is not None:
                return Prediction(
                    'ok', _apply_procedure(vsa_procedure, xs), key,
                    procedure=_procedure_dict(vsa_procedure),
                    message=(f'Applied a case-grounded procedure by VSA similarity '
                             f'(score={vsa_score:.3f}, margin={vsa_margin:.3f}).'),
                    evidence_phrases=vsa_sources,
                    matched_tokens=sorted(set(self._instruction_sequence(key))),
                    matched_bigrams=[],
                    matched_templates=[f'vsa:alpha={self.vsa_alpha:g}'],
                    retrieval_score=vsa_score,
                    retrieval_margin=vsa_margin,
                )

        examples = self._examples.get(key, [])
        contrastive_input = None
        candidate_outputs = None
        if (vsa_score is not None and vsa_margin is not None
                and len(vsa_ranked) > 1
                and (vsa_score < self.vsa_min_similarity
                     or vsa_margin < self.vsa_min_margin)):
            contrastive_input, candidate_outputs = _contrastive_probe(
                [vsa_ranked[0][2], vsa_ranked[1][2]])
        if contrastive_input is not None and candidate_outputs is not None:
            request = (f'Please provide the intended output for input {contrastive_input}. '
                       f'{_format_candidate_outputs(candidate_outputs)}')
            message = ('Grounded evidence leaves competing interpretations; this '
                       'probe separates the closest case-grounded candidates.')
        else:
            language_gaps = self._diagnose_language_gaps(key)
            unknown_tokens = language_gaps.get('unknown_tokens', [])
            weak_bigrams = language_gaps.get('weak_bigrams', [])
            under_supported = language_gaps.get('under_supported_tokens', [])
            conflicting_tokens = language_gaps.get('conflicting_tokens', [])
            conflicting_bigrams = language_gaps.get('conflicting_bigrams', [])
            if parameter_conflict and parameter_template:
                request = (
                    f'The numeric phrase frame {parameter_template!r} is grounded, '
                    'but its slot values do not identify one in-range procedure. '
                    'Please provide an additional input/output example that resolves '
                    'the slot, using a value within the configured range.'
                )
            elif unknown_tokens:
                request = (
                    f'I have no taught phrase evidence for token(s) '
                    f'{unknown_tokens}. Please provide an input list and the '
                    'intended output for this instruction.'
                )
            elif weak_bigrams:
                request = (
                    f'The adjacent token pair(s) {weak_bigrams} lack repeated '
                    'grounded phrase evidence. Please provide an input list and '
                    'the intended output for this instruction.'
                )
            elif under_supported:
                request = (
                    f'Token(s) {under_supported} appear in fewer than two '
                    'distinct taught phrases. Please provide an input list and '
                    'the intended output for this instruction.'
                )
            elif conflicting_tokens or conflicting_bigrams:
                conflicts = conflicting_tokens + conflicting_bigrams
                request = (
                    'The learned language evidence conflicts: '
                    + '; '.join(conflicts)
                    + '. Please provide an input/output example that distinguishes '
                    'the intended rule.'
                )
            else:
                request = ('Please provide an input list and its intended output. '
                           'If the rule remains ambiguous, I will request a contrastive example.')
            message = ('Grounded lexical, positional, or parameter evidence does not identify one procedure; please provide examples.'
                       if lexical_conflict or parameter_conflict or aligned_conflict
                       or analogy_conflict else
                       'No uniquely learned procedure is available for this instruction.')
        if contrastive_input is not None and candidate_outputs is not None:
            language_gaps = self._diagnose_language_gaps(key)
            conflicts = (language_gaps.get('conflicting_tokens', [])
                         + language_gaps.get('conflicting_bigrams', []))
            if conflicts:
                request += (' Learned language evidence conflicts: '
                            + '; '.join(conflicts) + '.')
        return Prediction('need_examples' if not examples else 'need_more_examples',
                          None, key, request=request,
                          message=message,
                          evidence_phrases=(parameter_sources
                                            if parameter_conflict else None),
                          matched_templates=([parameter_template]
                                             if parameter_conflict
                                             and parameter_template else None),
                          retrieval_score=vsa_score,
                          retrieval_margin=vsa_margin,
                          contrastive_input=contrastive_input,
                          candidate_outputs=candidate_outputs,
                          language_gaps=language_gaps)

    def forget(self, instruction: str) -> bool:
        """Remove one instruction association and its demonstrations."""
        key = self._canonical_instruction_storage_key(
            self._clean_instruction(instruction))
        existed = key in self._examples or key in self._procedures
        self._examples.pop(key, None)
        self._procedures.pop(key, None)
        self._no_fit_records.pop(key, None)
        self._ambiguity_probe_cache.pop(key, None)
        self._candidate_space_cache.pop(key, None)
        self._invalidate_language_indexes()
        self._save_if_configured()
        return existed

    def list_rules(self) -> dict[str, list[dict[str, Any]]]:
        return {phrase: _procedure_dict(proc) for phrase, proc in sorted(self._procedures.items())}

    def propose_procedure_scaffolds(
            self, *, minimum_supporting_phrases: int = 3
            ) -> list[dict[str, Any]]:
        """Report repeated operation scaffolds across successful phrase rules.

        This is a structural analysis only: it neither changes retrieval nor
        claims that parameter slots can be transferred to new language. One
        phrase is held out deterministically; proposals require at least one
        numeric parameter to vary across the training phrases and the held-out
        procedure to share the same operation/key structure.
        """
        if (type(minimum_supporting_phrases) is not int
                or minimum_supporting_phrases < 3):
            raise ValueError('minimum_supporting_phrases must be at least three')
        cached = self._procedure_scaffold_cache.get(
            minimum_supporting_phrases)
        if cached is not None:
            return copy.deepcopy(cached)

        from crms_primitive_discovery import (
            _phrase_bits, _positive_bits, _signed_integer_bits,
        )

        integer_code = 'gamma'
        operation_width = max(1, (len(OPERATIONS) - 1).bit_length())

        def procedure_bits(procedure: tuple[Step, ...]) -> int:
            bits = _positive_bits(len(procedure) + 1, integer_code)
            for step in procedure:
                bits += operation_width
                bits += _positive_bits(len(step.parameters) + 1, integer_code)
                for name, value in sorted(step.parameters.items()):
                    bits += _phrase_bits(name, integer_code)
                    bits += _signed_integer_bits(value, integer_code)
            return bits

        groups: dict[tuple, list[tuple[str, tuple[Step, ...]]]] = {}
        for phrase, procedure in self._procedures.items():
            if len(procedure) < 2:
                continue
            if not self._examples.get(phrase):
                continue
            if any(type(value) is not int
                   for step in procedure for value in step.parameters.values()):
                continue
            structure = tuple(
                (step.operation, tuple(sorted(step.parameters)))
                for step in procedure)
            groups.setdefault(structure, []).append((phrase, procedure))

        proposals = []
        for structure, members in sorted(groups.items(), key=lambda item: repr(item[0])):
            members.sort(key=lambda item: item[0])
            if len(members) < minimum_supporting_phrases:
                continue
            held_out_member = max(
                members,
                key=lambda item: hashlib.sha256(
                    item[0].encode('utf-8')).digest())
            held_out = [held_out_member]
            training = [member for member in members
                        if member[0] != held_out_member[0]]
            if len(training) < 2:
                continue
            varying_slots = []
            slot_map: dict[tuple[int, str], str] = {}
            for step_index, (_operation, keys) in enumerate(structure):
                for key in keys:
                    values = {procedure[step_index].parameters[key]
                              for _phrase, procedure in training}
                    if len(values) > 1:
                        slot_name = f'step{step_index}.{key}'
                        varying_slots.append(slot_name)
                        slot_map[(step_index, key)] = slot_name
            if not varying_slots:
                continue
            descriptor = [
                {'operation': operation,
                 'parameters': {key: (
                     {'slot': slot_map[(index, key)]}
                     if (index, key) in slot_map
                     else training[0][1][index].parameters[key])
                                for key in keys}}
                for index, (operation, keys) in enumerate(structure)
            ]
            # Compare only learned procedure records: phrase labels and their
            # demonstrations are unchanged by factoring and therefore cancel
            # from both sides of this two-part code-length estimate.
            baseline_bits = _positive_bits(len(training) + 1, integer_code)
            for _phrase, procedure in training:
                baseline_bits += procedure_bits(procedure)

            schema_bits = _positive_bits(len(structure) + 1, integer_code)
            for index, (operation, keys) in enumerate(structure):
                schema_bits += operation_width
                schema_bits += _positive_bits(len(keys) + 1, integer_code)
                for key in keys:
                    schema_bits += _phrase_bits(key, integer_code)
                    schema_bits += 1  # fixed literal or parameter-slot tag
                    if (index, key) in slot_map:
                        schema_bits += _positive_bits(
                            varying_slots.index(slot_map[(index, key)]) + 1,
                            integer_code)
                    else:
                        schema_bits += _signed_integer_bits(
                            training[0][1][index].parameters[key], integer_code)
            association_bits = _positive_bits(len(training) + 1, integer_code)
            association_bits += len(training)  # one schema link per phrase
            slot_value_bits = sum(
                _signed_integer_bits(procedure[index].parameters[key], integer_code)
                for _phrase, procedure in training
                for slot in varying_slots
                for index, key in [slot.removeprefix('step').split('.', 1)]
                for index in [int(index)]
            )
            candidate_bits = schema_bits + association_bits + slot_value_bits
            if candidate_bits >= baseline_bits:
                continue

            held_out_phrase, held_out_procedure = held_out[0]
            held_out_valid = (
                tuple((step.operation, tuple(sorted(step.parameters)))
                      for step in held_out_procedure) == structure)
            if held_out_valid:
                instantiated = tuple(
                    Step(operation, {
                        key: (held_out_procedure[index].parameters[key]
                              if (index, key) in slot_map
                              else training[0][1][index].parameters[key])
                        for key in keys
                    })
                    for index, (operation, keys) in enumerate(structure))
                held_out_valid = all(
                    _apply_procedure(instantiated, inputs) == outputs
                    for inputs, outputs in self._examples[held_out_phrase])
            if not held_out_valid:
                continue
            lineage = []
            for role, (phrase, procedure) in (
                    [('training', member) for member in training]
                    + [('held_out', member) for member in held_out]):
                source_payload = {
                    'phrase': phrase,
                    'procedure': _procedure_dict(procedure),
                    'examples': self._examples[phrase],
                }
                source_bytes = json.dumps(
                    source_payload, sort_keys=True,
                    separators=(',', ':')).encode('utf-8')
                lineage.append({
                    'phrase': phrase,
                    'role': role,
                    'procedure': _procedure_dict(procedure),
                    'example_count': len(self._examples[phrase]),
                    'fingerprint': hashlib.sha256(source_bytes).hexdigest(),
                })
            artifact_payload = {
                'artifact_version': 1,
                'descriptor': descriptor,
                'source_fingerprints': [
                    {'phrase': item['phrase'], 'role': item['role'],
                     'fingerprint': item['fingerprint']}
                    for item in lineage],
                'minimum_supporting_phrases': minimum_supporting_phrases,
                'description_length_code': 'procedure-gamma-v1',
                'description_length_bits_baseline': baseline_bits,
                'description_length_bits_candidate': candidate_bits,
                'validation_policy': 'heldout-reconstruction-v1',
            }
            artifact_id = 'procedure-scaffold-v1-' + hashlib.sha256(
                json.dumps(artifact_payload, sort_keys=True,
                           separators=(',', ':')).encode('utf-8')).hexdigest()
            proposals.append({
                'kind': 'procedure_scaffold',
                'artifact_id': artifact_id,
                'artifact_version': 1,
                'descriptor': descriptor,
                'supporting_instructions': [phrase for phrase, _ in training],
                'held_out_instructions': [phrase for phrase, _ in held_out],
                'varying_parameter_slots': varying_slots,
                'description_length_bits_baseline': baseline_bits,
                'description_length_bits_candidate': candidate_bits,
                'description_length_gain_bits': baseline_bits - candidate_bits,
                'description_length_code': 'procedure-gamma-v1',
                'mdl_gate_passed': True,
                'training_parameter_values': {
                    slot: [procedure[index].parameters[key]
                           for _phrase, procedure in training]
                    for slot in varying_slots
                    for index, key in [slot.removeprefix('step').split('.', 1)]
                    for index in [int(index)]
                },
                'held_out_valid': True,
                'held_out_validation_examples': len(
                    self._examples[held_out_phrase]),
                'lineage': lineage,
                'validation_scope': (
                    'instantiate the proposed scaffold with held-out slot values '
                    'and reconstruct all held-out phrase demonstrations'),
                'report_only': True,
            })
        self._procedure_scaffold_cache[minimum_supporting_phrases] = (
            copy.deepcopy(proposals))
        return proposals

    def retrieve_procedure_scaffold(
            self, artifact_id: str, *, minimum_supporting_phrases: int = 3
            ) -> dict[str, Any] | None:
        """Retrieve a scaffold only while its current evidence still validates.

        Scaffold IDs are content-addressed references, not durable records.
        Re-derive the eligible proposals from current successes and return an
        exact ID match. If a source changed, was forgotten, or no longer passes
        held-out reconstruction and MDL, the old reference resolves to None.
        """
        if not isinstance(artifact_id, str):
            raise TypeError('artifact_id must be a string')
        if not artifact_id.startswith('procedure-scaffold-v1-'):
            return None
        for proposal in self.propose_procedure_scaffolds(
                minimum_supporting_phrases=minimum_supporting_phrases):
            if proposal['artifact_id'] == artifact_id:
                return copy.deepcopy(proposal)
        return None

    def no_fit_cases(self) -> list[dict[str, Any]]:
        """Return bounded, persisted records of complete searches with no fit."""
        return [copy.deepcopy(record)
                for record in self._no_fit_records.values()]

    def propose_primitive_candidates(
            self, *, minimum_supporting_phrases: int = 2,
            integer_code: str = 'gamma') -> list[dict[str, Any]]:
        """Return held-out-checked, report-only proposals from no-fit cases."""
        from crms_primitive_discovery import propose_window_binary_primitives
        from crms_expression_discovery import propose_window_expression_primitives

        records = [record for record in self.no_fit_cases()
                   if record.get('candidate_space_signature')
                   == self._candidate_space_signature_record()]
        proposals = propose_window_binary_primitives(
            records, minimum_supporting_phrases=minimum_supporting_phrases,
            integer_code=integer_code)
        proposals.extend(propose_window_expression_primitives(
            records, minimum_supporting_phrases=minimum_supporting_phrases,
            integer_code=integer_code))
        records_by_phrase = {record['instruction']: record for record in records}
        step_choices_before = len(self._steps)
        search_depth = self.max_composition_depth
        raw_sequences_before = sum(
            step_choices_before ** depth
            for depth in range(1, search_depth + 1))
        raw_sequences_after = sum(
            (step_choices_before + 1) ** depth
            for depth in range(1, search_depth + 1))
        for proposal in proposals:
            lineage = []
            for phrase in proposal['supporting_instructions']:
                record = records_by_phrase[phrase]
                split = record['proposal_split']
                encode = lambda example: json.dumps(
                    example, sort_keys=True, separators=(',', ':'))
                training_examples = sorted(
                    (record['examples'][index]
                     for index in split['training_indices']), key=encode)
                held_out_examples = sorted(
                    (record['examples'][index]
                     for index in split['held_out_indices']), key=encode)
                source_payload = {
                    'instruction': phrase,
                    'candidate_space_signature': record[
                        'candidate_space_signature'],
                    'search_bounds': record['search_bounds'],
                    'training_examples': training_examples,
                    'held_out_examples': held_out_examples,
                }
                fingerprint = hashlib.sha256(json.dumps(
                    source_payload, sort_keys=True,
                    separators=(',', ':')).encode('utf-8')).hexdigest()
                lineage.append({
                    'instruction': phrase,
                    'training_examples': len(training_examples),
                    'held_out_examples': len(held_out_examples),
                    'fingerprint': fingerprint,
                    'evidence_fingerprint': _phrase_example_fingerprint(
                        phrase, record['examples']),
                })
            proposal.update({
                'kind': 'primitive_proposal',
                'artifact_version': 1,
                'artifact_id': _primitive_proposal_artifact_id(
                    proposal['descriptor'], lineage,
                    minimum_supporting_phrases=minimum_supporting_phrases,
                    integer_code=proposal['integer_code'],
                    baseline_bits=proposal['description_length_bits_baseline'],
                    candidate_bits=proposal['description_length_bits_candidate']),
                'minimum_supporting_phrases': minimum_supporting_phrases,
                'split_policy': 'sha256-example-v1',
                'validation_policy': 'training-mdl-heldout-v1',
                'lineage': lineage,
                'report_only': True,
                'search_cost_estimate': {
                    'max_composition_depth': search_depth,
                    'step_choices_before': step_choices_before,
                    'step_choices_after_acceptance': step_choices_before + 1,
                    'raw_procedure_sequences_before': raw_sequences_before,
                    'raw_procedure_sequences_after': raw_sequences_after,
                    'raw_sequence_growth_upper_bound': (
                        raw_sequences_after - raw_sequences_before),
                    'metric': 'unpruned_step_sequences',
                    'runtime_prediction': False,
                },
            })
        return proposals

    def retrieve_primitive_proposal(
            self, artifact_id: str, *, minimum_supporting_phrases: int = 2,
            integer_code: str = 'gamma') -> dict[str, Any] | None:
        """Resolve a primitive proposal only against current supporting evidence."""
        if not isinstance(artifact_id, str):
            raise TypeError('artifact_id must be a string')
        if not artifact_id.startswith('primitive-proposal-v1-'):
            return None
        for proposal in self.propose_primitive_candidates(
                minimum_supporting_phrases=minimum_supporting_phrases,
                integer_code=integer_code):
            if proposal['artifact_id'] == artifact_id:
                return copy.deepcopy(proposal)
        return None

    def accepted_primitive_candidates(self) -> list[dict[str, Any]]:
        """Return explicitly accepted primitive schemas in stable order."""
        return [copy.deepcopy(self._accepted_primitives[key])
                for key in sorted(self._accepted_primitives, key=repr)]

    def accepted_primitive_artifacts(self) -> list[dict[str, Any]]:
        """Return accepted primitive evidence artifacts, when provenance exists."""
        return [copy.deepcopy(self._accepted_primitive_artifacts[key])
                for key in sorted(self._accepted_primitive_artifacts, key=repr)]

    def audit_accepted_primitive_artifacts(self) -> list[dict[str, Any]]:
        """Report whether each accepted artifact's source examples still exist."""
        results = []
        for artifact in self.accepted_primitive_artifacts():
            changed_sources = []
            for source in artifact['lineage']:
                phrase = source['instruction']
                examples = self._examples.get(phrase)
                expected_fingerprint = source.get('evidence_fingerprint')
                if (examples is None or expected_fingerprint is None
                        or _phrase_example_fingerprint(
                            phrase, examples) != expected_fingerprint):
                    changed_sources.append(phrase)
            results.append({
                'artifact_id': artifact['artifact_id'],
                'descriptor': copy.deepcopy(artifact['descriptor']),
                'evidence_status': 'current' if not changed_sources else 'stale',
                'changed_sources': changed_sources,
            })
        return results

    def accept_primitive_candidate(
            self, descriptor: dict[str, Any], *, artifact_id: str | None = None
            ) -> bool:
        """Accept one current held-out/MDL-gated proposal into this model.

        Acceptance adds one parameterized operation instance to the bounded
        search grammar; it does not commit phrase-to-rule associations. Call
        ``retry`` on demonstrations to synthesize those associations.
        """
        step = _primitive_step_from_descriptor(descriptor)
        canonical_descriptor = _primitive_descriptor_from_step(step)
        step_key = _procedure_key((step,))
        if step_key in self._accepted_primitives:
            return False
        available = [proposal for proposal in self.propose_primitive_candidates()
                     if proposal.get('held_out_valid')
                     and proposal.get('mdl_gate_passed')
                     and (artifact_id is None
                          or proposal.get('artifact_id') == artifact_id)]
        descriptor_key = json.dumps(canonical_descriptor, sort_keys=True)
        selected = next((proposal for proposal in available
                         if json.dumps(proposal['descriptor'], sort_keys=True)
                         == descriptor_key), None)
        if selected is None:
            if artifact_id is not None:
                raise ValueError(
                    'primitive proposal artifact is stale or no longer validated')
            raise ValueError('primitive is not a current validated proposal')
        self._accepted_primitives[step_key] = canonical_descriptor
        self._accepted_primitive_artifacts[step_key] = copy.deepcopy(
            selected)
        self._steps.append(step)
        self._candidate_space_cache.clear()
        self._ambiguity_probe_cache.clear()
        self._invalidate_language_indexes()
        self._save_if_configured()
        return True

    def accept_primitive_proposal(self, artifact_id: str) -> bool:
        """Accept exactly one currently valid proposal identified by its ID."""
        proposal = self.retrieve_primitive_proposal(artifact_id)
        if proposal is None:
            raise ValueError(
                'primitive proposal artifact is stale or no longer validated')
        return self.accept_primitive_candidate(
            proposal['descriptor'], artifact_id=artifact_id)

    def learn_primitive_proposal(
            self, artifact_id: str, *, max_pending_rechecks: int = 0
            ) -> dict[str, Any]:
        """Atomically accept a validated primitive and learn its supported phrases.

        The candidate is applied to an isolated copy. Every phrase in the
        proposal must synthesize successfully and reproduce all recorded
        demonstrations before the updated grammar and phrase rules are
        committed to this model. Any failure leaves this model unchanged.
        """
        proposal = self.retrieve_primitive_proposal(artifact_id)
        if proposal is None:
            raise ValueError(
                'primitive proposal artifact is stale or no longer validated')
        if (type(max_pending_rechecks) is not int
                or not 0 <= max_pending_rechecks <= 20):
            raise ValueError('max_pending_rechecks must be an integer from 0 to 20')
        if not proposal.get('held_out_valid') or not proposal.get('mdl_gate_passed'):
            raise ValueError('primitive proposal did not pass its validation gates')

        committed_path = self.memory_path
        candidate = copy.deepcopy(self)
        candidate.memory_path = None
        candidate.accept_primitive_proposal(artifact_id)
        primitive_step = _primitive_step_from_descriptor(proposal['descriptor'])
        learned_phrases = []
        mechanical_probes: dict[str, list[dict[str, Any]]] = {}
        for phrase in proposal['supporting_instructions']:
            examples = candidate._examples.get(phrase)
            if not examples:
                raise ValueError(
                    f'primitive proposal has no retained examples for {phrase!r}')
            original_examples = [(list(inputs), list(outputs))
                                 for inputs, outputs in examples]
            probes: list[dict[str, Any]] = []
            learned = None
            for _ in range(9):
                learned = candidate.retry(phrase)
                if learned.status == 'learned':
                    break
                probe = learned.contrastive_input
                if (learned.status != 'need_more_examples'
                        or probe is None
                        or any(inputs == probe for inputs, _ in candidate._examples[phrase])):
                    raise ValueError(
                        f'validated primitive did not synthesize {phrase!r}: '
                        f'{learned.status}')
                # This label comes from the accepted primitive's explicit
                # executable semantics. Keep it separate from supplied
                # demonstrations so it cannot masquerade as external evidence.
                output = _apply_procedure((primitive_step,), list(probe))
                candidate._examples[phrase].append((list(probe), output))
                probes.append({
                    'input': list(probe),
                    'output': list(output),
                    'source': 'contrastive_probe_labeled_by_validated_primitive',
                    'proposal_artifact_id': artifact_id,
                })
            if learned is None or learned.status != 'learned':
                raise ValueError(
                    f'validated primitive exceeded the contrastive-probe limit '
                    f'for {phrase!r}')
            for inputs, expected in examples:
                if any(item['input'] == inputs for item in probes):
                    continue
                predicted = candidate.predict(phrase, inputs)
                if (predicted.status != 'ok'
                        or predicted.output != expected):
                    raise ValueError(
                        f'primitive failed demonstration replay for {phrase!r}')
            candidate._examples[phrase] = original_examples
            candidate._candidate_space_cache.pop(phrase, None)
            candidate._ambiguity_probe_cache.pop(phrase, None)
            candidate._invalidate_language_indexes()
            if probes:
                mechanical_probes[phrase] = probes
            learned_phrases.append(phrase)

        if mechanical_probes:
            step_key = _procedure_key((primitive_step,))
            accepted_artifact = candidate._accepted_primitive_artifacts[step_key]
            accepted_artifact['mechanical_disambiguation_probes'] = copy.deepcopy(
                mechanical_probes)

        supporting = set(proposal['supporting_instructions'])
        pending_phrases = [record['instruction']
                           for record in candidate.no_fit_cases()
                           if record['instruction'] not in supporting]
        rechecked_phrases = []
        newly_learned_phrases = []
        for phrase in pending_phrases[:max_pending_rechecks]:
            retried = candidate.retry(phrase)
            rechecked_phrases.append(phrase)
            if retried.status == 'learned':
                newly_learned_phrases.append(phrase)

        candidate.memory_path = committed_path
        if committed_path is not None:
            candidate.save()
        self.__dict__.clear()
        self.__dict__.update(candidate.__dict__)
        return {
            'artifact_id': artifact_id,
            'descriptor': copy.deepcopy(proposal['descriptor']),
            'learned_phrases': learned_phrases,
            'replayed_examples': sum(
                len(self._examples[phrase]) for phrase in learned_phrases),
            'rechecked_phrases': rechecked_phrases,
            'newly_learned_phrases': newly_learned_phrases,
            'mechanical_disambiguation_probes': copy.deepcopy(mechanical_probes),
            'status': 'learned',
        }

    def learn_best_primitive_proposal(
            self, *, max_pending_rechecks: int = 8
            ) -> dict[str, Any] | None:
        """Mechanically select and learn the strongest current primitive proposal.

        Selection is bounded to one proposal per call. It ranks only candidates
        that passed the independent held-out and training MDL gates, favoring
        larger measured compression gains, broader phrase support, then lower
        estimated grammar growth. The chosen candidate still passes through
        transactional example replay in ``learn_primitive_proposal``.
        """
        if (type(max_pending_rechecks) is not int
                or not 0 <= max_pending_rechecks <= 20):
            raise ValueError('max_pending_rechecks must be an integer from 0 to 20')
        proposals = [proposal for proposal in self.propose_primitive_candidates()
                     if proposal.get('held_out_valid') is True
                     and proposal.get('mdl_gate_passed') is True]
        proposals.sort(key=lambda proposal: (
            -proposal.get('description_length_gain_bits', 0),
            -len(proposal.get('supporting_instructions', ())),
            proposal.get('search_cost_estimate', {}).get(
                'raw_sequence_growth_upper_bound', 0),
            proposal.get('artifact_id', '')))
        for proposal in proposals:
            try:
                return self.learn_primitive_proposal(
                    proposal['artifact_id'],
                    max_pending_rechecks=max_pending_rechecks)
            except ValueError:
                # A rejected candidate leaves the active model untouched;
                # another current proposal may still pass replay.
                continue
        return None

    def revoke_primitive_candidate(self, descriptor: dict[str, Any]) -> bool:
        """Remove one accepted primitive when no committed rule depends on it."""
        step = _primitive_step_from_descriptor(descriptor)
        step_key = _procedure_key((step,))
        if step_key not in self._accepted_primitives:
            return False
        dependents = sorted(
            phrase for phrase, procedure in self._procedures.items()
            if any(_procedure_key((item,)) == step_key for item in procedure))
        if dependents:
            raise ValueError(
                'primitive is used by committed rules; forget or replace these '
                'instructions first: ' + ', '.join(dependents))
        del self._accepted_primitives[step_key]
        self._accepted_primitive_artifacts.pop(step_key, None)
        self._steps = [item for item in self._steps
                       if _procedure_key((item,)) != step_key]
        self._candidate_space_cache.clear()
        self._ambiguity_probe_cache.clear()
        self._invalidate_language_indexes()
        self._save_if_configured()
        return True

    def _remember_no_fit(self, instruction: str,
                         examples: list[tuple[list[int], list[int]]]) -> None:
        record = {
            "instruction": instruction,
            "examples": [[list(inputs), list(outputs)]
                         for inputs, outputs in examples],
            "proposal_split": _proposal_split_indices(examples),
            "candidate_space_signature":
                self._candidate_space_signature_record(),
            "search_bounds": {
                "max_composition_depth": self.max_composition_depth,
                "max_add": self.max_add,
                "max_scale": self.max_scale,
                "max_modulus": self.max_modulus,
                "max_rotation": self.max_rotation,
                "max_repeat": self.max_repeat,
                "max_position_stride": self.max_position_stride,
                "max_search_expansions": self.max_search_expansions,
            },
        }
        self._no_fit_records.pop(instruction, None)
        self._no_fit_records[instruction] = record
        while len(self._no_fit_records) > self.NO_FIT_RECORD_LIMIT:
            self._no_fit_records.popitem(last=False)

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path is not None else self.memory_path
        if target is None:
            raise ValueError('provide a path or configure memory_path')
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'format_version': self.FORMAT_VERSION,
            'max_composition_depth': self.max_composition_depth,
            'max_add': self.max_add,
            'max_scale': self.max_scale,
            'max_modulus': self.max_modulus,
            'max_rotation': self.max_rotation,
            'max_repeat': self.max_repeat,
            'max_position_stride': self.max_position_stride,
            'enable_position_arithmetic': self.enable_position_arithmetic,
            'max_search_expansions': self.max_search_expansions,
            'vsa_alpha': self.vsa_alpha,
            'vsa_min_similarity': self.vsa_min_similarity,
            'vsa_min_margin': self.vsa_min_margin,
            'examples': {phrase: examples for phrase, examples in self._examples.items()},
            'procedures': {phrase: _procedure_dict(proc)
                           for phrase, proc in self._procedures.items()},
            'accepted_primitives': self.accepted_primitive_candidates(),
            'accepted_primitive_artifacts': self.accepted_primitive_artifacts(),
            'no_fit_cases': list(self._no_fit_records.values()),
        }
        if target.suffix.casefold() in {'.sqlite', '.sqlite3', '.db'}:
            _write_rule_database(target, payload)
        else:
            target.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    def _decode_procedure(
            self, steps: Any, *, bounds: dict[str, int] | None = None,
            max_depth: int | None = None) -> tuple[Step, ...]:
        bounds = bounds or {
            'max_add': self.max_add, 'max_scale': self.max_scale,
            'max_modulus': self.max_modulus, 'max_rotation': self.max_rotation,
            'max_repeat': self.max_repeat,
            'max_position_stride': self.max_position_stride,
        }
        max_depth = self.max_composition_depth if max_depth is None else max_depth
        if not isinstance(steps, list) or not 1 <= len(steps) <= max_depth:
            raise ValueError('stored procedure has an invalid number of steps')
        procedure = []
        for raw_step in steps:
            if not isinstance(raw_step, dict):
                raise ValueError('stored procedure step must be an object')
            operation = raw_step.get('operation')
            parameters = raw_step.get('parameters', {})
            if (not isinstance(operation, str) or operation not in OPERATIONS
                    or not isinstance(parameters, dict)):
                raise ValueError('stored procedure has an invalid operation or parameters')
            if operation == 'add_position' and not self.enable_position_arithmetic:
                raise ValueError(
                    'stored add_position requires enable_position_arithmetic=True')
            if operation == 'add_k':
                k = parameters.get('k')
                if (set(parameters) != {'k'} or type(k) is not int or k == 0
                        or abs(k) > bounds['max_add']):
                    raise ValueError('stored add_k step has invalid parameters')
            elif operation == 'scale_k':
                k = parameters.get('k')
                if (set(parameters) != {'k'} or type(k) is not int
                        or k in (1, 2)
                        or abs(k) > bounds['max_scale']):
                    raise ValueError('stored scale_k step has invalid parameters')
            elif operation == 'keep_multiples_k':
                k = parameters.get('k')
                if (set(parameters) != {'k'} or type(k) is not int
                        or not 3 <= k <= bounds['max_modulus']):
                    raise ValueError('stored keep_multiples_k step has invalid parameters')
            elif operation == 'rotate_left_k':
                k = parameters.get('k')
                if (set(parameters) != {'k'} or type(k) is not int or k == 0
                        or abs(k) > bounds['max_rotation']):
                    raise ValueError('stored rotate_left_k step has invalid parameters')
            elif operation == 'repeat_each_k':
                k = parameters.get('k')
                if (set(parameters) != {'k'} or type(k) is not int
                        or not 2 <= k <= bounds['max_repeat']):
                    raise ValueError('stored repeat_each_k step has invalid parameters')
            elif operation == 'keep_every_kth_position':
                k = parameters.get('k')
                if (set(parameters) != {'k'} or type(k) is not int
                        or not 3 <= k <= bounds['max_position_stride']):
                    raise ValueError('stored positional-stride step has invalid parameters')
            elif operation == 'map_window_binary':
                expected = {'operator_id', 'window_width', 'left_offset',
                            'right_offset', 'stride'}
                operator_id = parameters.get('operator_id')
                width = parameters.get('window_width')
                left = parameters.get('left_offset')
                right = parameters.get('right_offset')
                stride = parameters.get('stride')
                if (set(parameters) != expected
                        or type(operator_id) is not int
                        or not 0 <= operator_id < len(_WINDOW_BINARY_OPERATORS)
                        or type(width) is not int or width not in (2, 3)
                        or type(left) is not int or not 0 <= left < width
                        or type(right) is not int or not 0 <= right < width
                        or type(stride) is not int or not 1 <= stride <= width):
                    raise ValueError('stored window-binary step has invalid parameters')
            elif operation == 'map_window_expression':
                expected = {'expression_code', 'stride'}
                expected_width = expected | {'window_width'}
                code, stride = parameters.get('expression_code'), parameters.get('stride')
                if (set(parameters) not in (expected, expected_width)
                        or type(code) is not int
                        or type(stride) is not int or not 1 <= stride <= 3):
                    raise ValueError('stored window-expression step has invalid parameters')
                width = _window_expression_width(code)
                if parameters.get('window_width', width) != width:
                    raise ValueError('stored window-expression width does not match its variables')
            elif parameters:
                raise ValueError(f'stored {operation} step cannot have parameters')
            if operation == 'duplicate_each':
                # Read v1 memories written before repetition became a
                # parameterized family, then keep the in-memory form canonical.
                operation, parameters = 'repeat_each_k', {'k': 2}
            procedure.append(Step(operation, dict(parameters)))
        return tuple(procedure)

    def load(self, path: str | Path | None = None) -> None:
        target = Path(path) if path is not None else self.memory_path
        if target is None:
            raise ValueError('provide a path or configure memory_path')
        payload = (_rule_database_payload(target)
                   if target.suffix.casefold() in {'.sqlite', '.sqlite3', '.db'}
                   else json.loads(target.read_text(encoding='utf-8')))
        if not isinstance(payload, dict) or payload.get('format_version') != self.FORMAT_VERSION:
            raise ValueError('unsupported CRMS memory format version')
        stored_depth = payload.get('max_composition_depth')
        stored_scale = payload.get('max_scale', self.max_scale)
        if stored_scale is None:
            stored_scale = self.max_scale
        stored_position_arithmetic = payload.get(
            'enable_position_arithmetic', False)
        if (type(stored_position_arithmetic) is not bool
                or stored_position_arithmetic != self.enable_position_arithmetic):
            raise ValueError(
                'memory position-arithmetic setting differs; initialize with matching setting')
        stored_bounds = {
            'max_add': payload.get('max_add'),
            'max_scale': stored_scale,
            'max_modulus': payload.get('max_modulus', self.max_modulus),
            'max_rotation': payload.get('max_rotation', self.max_rotation),
            'max_repeat': payload.get('max_repeat', self.max_repeat),
            'max_position_stride': payload.get(
                'max_position_stride', self.max_position_stride),
        }
        configured_bounds = {
            'max_add': self.max_add, 'max_scale': self.max_scale,
            'max_modulus': self.max_modulus, 'max_rotation': self.max_rotation,
            'max_repeat': self.max_repeat,
            'max_position_stride': self.max_position_stride,
        }
        minimum_bounds = {
            'max_add': 1, 'max_scale': 3, 'max_modulus': 3,
            'max_rotation': 1, 'max_repeat': 2, 'max_position_stride': 3,
        }
        if (type(stored_depth) is not int
                or stored_depth < 1
                or stored_depth > self.max_composition_depth
                or any(type(stored) is not int
                       or stored < minimum_bounds[name]
                       or stored > configured_bounds[name]
                       for name, stored in stored_bounds.items())):
            raise ValueError(
                'memory search bounds exceed this configuration; initialize with equal or wider bounds')
        stored_search_budget = payload.get(
            'max_search_expansions', self.max_search_expansions)
        if (type(stored_search_budget) is not int or stored_search_budget < 1
                or stored_search_budget > self.max_search_expansions):
            raise ValueError(
                'memory search budget exceeds this configuration; initialize with an equal or wider budget')
        for name, configured in (
            ('vsa_alpha', self.vsa_alpha),
            ('vsa_min_similarity', self.vsa_min_similarity),
            ('vsa_min_margin', self.vsa_min_margin),
        ):
            stored = payload.get(name, configured)
            if stored != configured:
                raise ValueError(f'memory {name} differs; initialize with matching retrieval settings')
        raw_examples = payload.get('examples', {})
        raw_procedures = payload.get('procedures', {})
        raw_accepted_primitives = payload.get('accepted_primitives', [])
        raw_accepted_primitive_artifacts = payload.get(
            'accepted_primitive_artifacts', [])
        raw_no_fit_cases = payload.get('no_fit_cases', [])
        if not isinstance(raw_examples, dict) or not isinstance(raw_procedures, dict):
            raise ValueError('stored examples and procedures must be objects')
        if (not isinstance(raw_accepted_primitives, list)
                or len(raw_accepted_primitives) > 64):
            raise ValueError('stored accepted primitive list is malformed or oversized')
        if (not isinstance(raw_accepted_primitive_artifacts, list)
                or len(raw_accepted_primitive_artifacts) > 64):
            raise ValueError(
                'stored accepted primitive artifact list is malformed or oversized')
        if (not isinstance(raw_no_fit_cases, list)
                or len(raw_no_fit_cases) > self.NO_FIT_RECORD_LIMIT):
            raise ValueError('stored no-fit case archive is malformed or oversized')

        accepted_steps_by_key = {}
        for descriptor in raw_accepted_primitives:
            step = _primitive_step_from_descriptor(descriptor)
            canonical = _primitive_descriptor_from_step(step)
            key = _procedure_key((step,))
            if key in accepted_steps_by_key:
                raise ValueError('stored accepted primitive is duplicated')
            accepted_steps_by_key[key] = (step, canonical)

        accepted_artifacts_by_key = {}
        for artifact in raw_accepted_primitive_artifacts:
            if not isinstance(artifact, dict):
                raise ValueError('stored accepted primitive artifact is malformed')
            descriptor = artifact.get('descriptor')
            step = _primitive_step_from_descriptor(descriptor)
            canonical = _primitive_descriptor_from_step(step)
            key = _procedure_key((step,))
            if (key not in accepted_steps_by_key
                    or accepted_steps_by_key[key][1] != canonical
                    or key in accepted_artifacts_by_key):
                raise ValueError(
                    'stored accepted primitive artifact has no unique accepted schema')
            lineage = artifact.get('lineage')
            supporting = artifact.get('supporting_instructions')
            if (artifact.get('kind') != 'primitive_proposal'
                    or artifact.get('artifact_version') != 1
                    or artifact.get('report_only') is not True
                    or artifact.get('split_policy') != 'sha256-example-v1'
                    or artifact.get('validation_policy')
                        != 'training-mdl-heldout-v1'
                    or not isinstance(lineage, list) or len(lineage) < 2
                    or not isinstance(supporting, list)
                    or any(not isinstance(item, dict)
                           or set(item) not in ({
                               'instruction', 'training_examples',
                               'held_out_examples', 'fingerprint'}, {
                               'instruction', 'training_examples',
                               'held_out_examples', 'fingerprint',
                               'evidence_fingerprint'})
                           or not isinstance(item['instruction'], str)
                           or type(item['training_examples']) is not int
                           or item['training_examples'] < 2
                           or type(item['held_out_examples']) is not int
                           or item['held_out_examples'] < 1
                           or not isinstance(item['fingerprint'], str)
                           or len(item['fingerprint']) != 64
                           or any(char not in '0123456789abcdef'
                                  for char in item['fingerprint'])
                           or ('evidence_fingerprint' in item
                               and (not isinstance(item['evidence_fingerprint'], str)
                                    or len(item['evidence_fingerprint']) != 64
                                    or any(char not in '0123456789abcdef'
                                           for char in item['evidence_fingerprint'])))
                           for item in lineage)
                    or supporting != [item['instruction'] for item in lineage]
                    or len(set(supporting)) != len(supporting)
                    or artifact.get('held_out_valid') is not True
                    or artifact.get('mdl_gate_passed') is not True
                    or type(artifact.get('minimum_supporting_phrases')) is not int
                    or artifact['minimum_supporting_phrases'] < 2
                    or artifact['minimum_supporting_phrases'] > len(lineage)
                    or artifact.get('integer_code') not in {'gamma', 'delta'}
                    or type(artifact.get('description_length_bits_baseline')) is not int
                    or type(artifact.get('description_length_bits_candidate')) is not int
                    or artifact['description_length_bits_baseline'] <=
                        artifact['description_length_bits_candidate']):
                raise ValueError('stored accepted primitive artifact is invalid')
            expected_artifact_id = _primitive_proposal_artifact_id(
                canonical, lineage,
                minimum_supporting_phrases=artifact['minimum_supporting_phrases'],
                integer_code=artifact['integer_code'],
                baseline_bits=artifact['description_length_bits_baseline'],
                candidate_bits=artifact['description_length_bits_candidate'])
            if artifact.get('artifact_id') != expected_artifact_id:
                raise ValueError('stored accepted primitive artifact ID is invalid')
            accepted_artifacts_by_key[key] = copy.deepcopy(artifact)

        examples_by_phrase = {}
        for phrase, examples in raw_examples.items():
            if self._clean_instruction(phrase) != phrase or not isinstance(examples, list):
                raise ValueError('stored example association has an invalid phrase or examples')
            parsed = []
            for example in examples:
                if not isinstance(example, list) or len(example) != 2:
                    raise ValueError('stored example must contain input and output lists')
                parsed.append((self._clean_values(example[0]), self._clean_values(example[1])))
            examples_by_phrase[phrase] = parsed

        procedures_by_phrase = {}
        for phrase, raw_steps in raw_procedures.items():
            if self._clean_instruction(phrase) != phrase:
                raise ValueError('stored procedure phrase is not normalized')
            procedure = self._decode_procedure(
                raw_steps, bounds=stored_bounds, max_depth=stored_depth)
            if any(step.operation in {'map_window_binary', 'map_window_expression'}
                   and _procedure_key((step,)) not in accepted_steps_by_key
                   for step in procedure):
                raise ValueError('stored rule uses an unaccepted primitive')
            evidence = examples_by_phrase.get(phrase)
            if not evidence or any(_apply_procedure(procedure, x) != y for x, y in evidence):
                raise ValueError('stored procedure does not fit its stored examples')
            procedures_by_phrase[phrase] = procedure

        no_fit_by_phrase: OrderedDict[str, dict[str, Any]] = OrderedDict()
        expected_bound_names = {
            'max_composition_depth', 'max_add', 'max_scale', 'max_modulus',
            'max_rotation', 'max_repeat', 'max_position_stride',
            'max_search_expansions',
        }
        for record in raw_no_fit_cases:
            if not isinstance(record, dict):
                raise ValueError('stored no-fit record must be an object')
            phrase = record.get('instruction')
            if (not isinstance(phrase, str)
                    or self._clean_instruction(phrase) != phrase
                    or phrase not in examples_by_phrase
                    or phrase in procedures_by_phrase
                    or phrase in no_fit_by_phrase):
                raise ValueError('stored no-fit record has an invalid instruction')
            raw_record_examples = record.get('examples')
            if not isinstance(raw_record_examples, list):
                raise ValueError('stored no-fit record examples are malformed')
            parsed_record_examples = []
            for example in raw_record_examples:
                if not isinstance(example, list) or len(example) != 2:
                    raise ValueError('stored no-fit example is malformed')
                parsed_record_examples.append((
                    self._clean_values(example[0]),
                    self._clean_values(example[1])))
            if parsed_record_examples != examples_by_phrase[phrase]:
                raise ValueError('stored no-fit record differs from its demonstrations')
            proposal_split = record.get('proposal_split')
            if (proposal_split is not None
                    and (not isinstance(proposal_split, dict)
                         or set(proposal_split) != {
                             'training_indices', 'held_out_indices'})):
                raise ValueError('stored no-fit proposal split is malformed')
            example_count = len(parsed_record_examples)
            expected_split = _proposal_split_indices(parsed_record_examples)
            legacy_split = {
                'training_indices': (list(range(example_count - 1))
                                    if example_count >= 3
                                    else list(range(example_count))),
                'held_out_indices': ([example_count - 1]
                                     if example_count >= 3 else []),
            }
            if proposal_split is None:
                proposal_split = expected_split
            expected_training_indices = expected_split['training_indices']
            expected_held_out_indices = expected_split['held_out_indices']
            if (any(not isinstance(proposal_split.get(name), list)
                    or any(type(index) is not int
                           for index in proposal_split[name])
                    for name in ('training_indices', 'held_out_indices'))
                    or proposal_split not in (expected_split, legacy_split)):
                raise ValueError('stored no-fit proposal split is invalid')
            raw_record_bounds = record.get('search_bounds')
            if (not isinstance(raw_record_bounds, dict)
                    or set(raw_record_bounds) != expected_bound_names):
                raise ValueError('stored no-fit search bounds are malformed')
            record_bounds = raw_record_bounds
            if (any(type(value) is not int or value < 1
                    for value in record_bounds.values())
                    or record_bounds['max_composition_depth'] > stored_depth
                    or record_bounds['max_add'] > stored_bounds['max_add']
                    or record_bounds['max_scale'] > stored_bounds['max_scale']
                    or record_bounds['max_modulus'] > stored_bounds['max_modulus']
                    or record_bounds['max_rotation'] > stored_bounds['max_rotation']
                    or record_bounds['max_repeat'] > stored_bounds['max_repeat']
                    or record_bounds['max_position_stride']
                    > stored_bounds['max_position_stride']
                    or record_bounds['max_search_expansions']
                    > stored_search_budget):
                raise ValueError('stored no-fit search bounds exceed memory bounds')
            raw_signature = record.get('candidate_space_signature')
            if raw_signature is not None:
                if (not isinstance(raw_signature, dict)
                        or set(raw_signature) != {
                            'max_composition_depth', 'max_search_expansions', 'steps'}
                        or type(raw_signature['max_composition_depth']) is not int
                        or type(raw_signature['max_search_expansions']) is not int
                        or not isinstance(raw_signature['steps'], list)
                        or not 1 <= raw_signature['max_composition_depth'] <= stored_depth
                        or not 1 <= raw_signature['max_search_expansions']
                        <= stored_search_budget):
                    raise ValueError('stored no-fit candidate-space signature is malformed')
                for signature_step in raw_signature['steps']:
                    if (not isinstance(signature_step, dict)
                            or set(signature_step) != {'operation', 'parameters'}
                            or signature_step['operation'] not in OPERATIONS
                            or not isinstance(signature_step['parameters'], dict)
                            or any(type(value) is not int
                                   for value in signature_step['parameters'].values())):
                        raise ValueError('stored no-fit candidate-space step is malformed')
            no_fit_by_phrase[phrase] = {
                'instruction': phrase,
                'examples': [[list(inputs), list(outputs)]
                             for inputs, outputs in parsed_record_examples],
                'proposal_split': {
                    'training_indices': expected_training_indices,
                    'held_out_indices': expected_held_out_indices,
                },
                'candidate_space_signature': copy.deepcopy(raw_signature),
                'search_bounds': dict(record_bounds),
            }

        # Replace live memory only after every persisted association validates.
        self._examples = examples_by_phrase
        self._procedures = procedures_by_phrase
        self._accepted_primitives = {
            key: descriptor
            for key, (_step, descriptor) in accepted_steps_by_key.items()
        }
        self._accepted_primitive_artifacts = accepted_artifacts_by_key
        base_steps = [step for step in self._steps
                      if step.operation not in {'map_window_binary',
                                                'map_window_expression'}]
        self._steps = base_steps + [
            step for step, _descriptor in accepted_steps_by_key.values()]
        self._no_fit_records = no_fit_by_phrase
        self._candidate_space_cache.clear()
        self._ambiguity_probe_cache.clear()
        self._invalidate_language_indexes()

    def _save_if_configured(self) -> None:
        if self.memory_path is not None:
            self.save()


def _demo() -> None:
    model = CRMSModel()
    phrase = 'apply doubling twice'
    print(model.predict(phrase, [1, 2]))
    learned = model.teach(phrase, [([1, 2], [4, 8]), ([3, -1], [12, -4])])
    print(learned)
    print(model.predict(phrase, [5, 2]))


if __name__ == '__main__':
    _demo()
