"""Check NFC normalization supports grounded lexical language transfer."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


EXAMPLES = [([1, 2, 3], [3, 2, 1]), ([8, -4, 0], [0, -4, 8])]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    composed = 'café'
    decomposed = 'cafe\u0301'
    require(composed != decomposed, 'fixture spellings are not distinct')
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    require(model._instruction_sequence(composed)
            == model._instruction_sequence(decomposed),
            'canonically equivalent spellings have different lexical tokens')

    phrase = 'reverse café list'
    result = model.teach(phrase, EXAMPLES)
    require(result.status == 'learned',
            f'grounded source phrase did not learn: {result}')

    query = 'reverse cafe\u0301 list'
    prediction = model.predict(query, [9, 2, -1])
    require(prediction.status == 'ok'
            and prediction.output == [-1, 2, 9]
            and prediction.evidence_phrases == [phrase]
            and not prediction.matched_templates
            and prediction.retrieval_score is None,
            f'Unicode-equivalent exact phrase lookup failed: {prediction}')

    unknown = model.predict('reverse cafe\u0301 vegetables', [9, 2, -1])
    require(unknown.status != 'ok',
            'Unicode normalization licensed an unsupported content word')

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'unicode-memory.json'
        persisted = CRMSModel(path, max_composition_depth=1, max_workers=1)
        persisted.teach(phrase, EXAMPLES)
        persisted.save()
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        restored_prediction = restored.predict(query, [9, 2, -1])
        require(restored_prediction.status == 'ok'
                and restored_prediction.output == [-1, 2, 9]
                and not restored_prediction.matched_templates,
                f'NFC transfer failed after reload: {restored_prediction}')

    conflicted = CRMSModel(max_composition_depth=1, max_workers=1)
    require(conflicted.teach(
        'reverse café list', EXAMPLES).status == 'learned',
        'composed-spelling conflict fixture did not learn')
    sort_examples = [([1, 3, 2], [1, 2, 3]), ([8, -4, 0], [-4, 0, 8])]
    conflicting_teach = conflicted.teach(
        'reverse cafe\u0301 list', sort_examples)
    require(conflicting_teach.status == 'no_fit'
            and len(conflicted._examples) == 1
            and len(conflicted._examples['reverse café list']) == 4,
            'canonically equivalent teaching did not merge into one phrase')
    conflicting_query = conflicted.predict(
        'reverse café list', [9, 2, -1])
    require(conflicting_query.status == 'need_more_examples'
            and conflicting_query.output is None,
            'conflicting canonical spellings selected one procedure')
    require(conflicted.forget('reverse cafe\u0301 list')
            and conflicted.predict('reverse café list', [9, 2, -1]).status
            == 'need_examples',
            'forget did not resolve a canonically equivalent phrase key')

    print('Unicode-canonical lexical transfer: PASS')
    print('composed/decomposed exact phrase identity, conflict abstention, '
          'unknown-token handling, and persistence: PASS')


if __name__ == '__main__':
    main()
