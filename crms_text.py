"""Small deterministic text-normalization helpers shared by CRMS subsystems."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator


class TokenMatch:
    """Normalized token value with offsets into the untouched source text."""

    __slots__ = ('_value', '_start', '_end')

    def __init__(self, value: str, start: int, end: int) -> None:
        self._value = value
        self._start = start
        self._end = end

    def group(self, index: int = 0) -> str:
        if index != 0:
            raise IndexError('token match has only group 0')
        return self._value

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end


def casefold_nfc(text: str) -> str:
    """Case-fold text and compose canonically equivalent Unicode sequences."""
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    return unicodedata.normalize('NFC', text.casefold())


def iter_word_matches(text: str, *, include_apostrophes: bool = True
                      ) -> Iterator[TokenMatch]:
    """Yield word tokens with exact source offsets and bounded extra memory.

    Unicode combining marks stay attached to the preceding letter, including
    decomposed accents that Python's built-in word character class omits.
    """
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    result = []
    start: int | None = None
    for index, character in enumerate(text):
        category = unicodedata.category(character)
        is_word = (character == '_' or category[0] in {'L', 'N', 'M'}
                   or (include_apostrophes and character == "'"))
        if is_word:
            if start is None:
                start = index
        elif start is not None:
            yield TokenMatch(casefold_nfc(text[start:index]), start, index)
            start = None
    if start is not None:
        yield TokenMatch(casefold_nfc(text[start:]), start, len(text))


def word_matches(text: str, *, include_apostrophes: bool = True
                  ) -> list[TokenMatch]:
    """Tokenize words while retaining exact source offsets."""
    return list(iter_word_matches(
        text, include_apostrophes=include_apostrophes))


def tokens(text: str, *, include_apostrophes: bool = True) -> tuple[str, ...]:
    """Return searchable word tokens with canonical Unicode normalization."""
    return tuple(match.group() for match in word_matches(
        text, include_apostrophes=include_apostrophes))
