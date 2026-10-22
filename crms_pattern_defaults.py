"""Default pattern resources.

Without an installed model the resources come from the visible seed file loaded into memory.
A release ships its own pattern database (`patterns.sqlite`, see `crms_pattern_pack.py`); the chat
points this module at it with `use_pattern_db`, and every consumer (relation specs, intent rules,
gate policy, word rarity) then reads the installed tables instead of the seed.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sqlite3
from typing import Any

from crms_pattern_memory import PatternMemory

_INSTALLED: Path | None = None


def installed_path() -> Path | None:
    return _INSTALLED


def use_pattern_db(path: str | Path | None) -> None:
    """Read pattern resources from an installed pattern database (None goes back to the seed)."""
    global _INSTALLED
    _INSTALLED = Path(path).expanduser().resolve() if path else None
    seeded_resources.cache_clear()
    seeded_policy.cache_clear()
    for module_name, function in (("crms_intent_rules", "_family"), ("crms_word_rarity", "_load")):
        import sys
        module = sys.modules.get(module_name)
        if module is not None:
            getattr(module, function).cache_clear()


def open_memory() -> PatternMemory:
    """A private in-memory pattern memory: a copy of the installed database, or the seed."""
    memory = PatternMemory(":memory:")
    if _INSTALLED is not None:
        source = sqlite3.connect(f"file:{_INSTALLED}?mode=ro", uri=True)
        try:
            source.backup(memory.connection)
        finally:
            source.close()
        memory.connection.row_factory = sqlite3.Row
    else:
        memory.seed()
    return memory


@lru_cache(maxsize=1)
def seeded_resources() -> tuple[Any, tuple, dict, tuple]:
    """(language, specs, params, rewrites) from the installed database or the seed file."""
    memory = open_memory()
    resources = (memory.language(), tuple(memory.specs()), memory.params(),
                 tuple(memory.rewrites()))
    memory.close()
    return resources


@lru_cache(maxsize=1)
def seeded_policy() -> dict[str, dict[str, Any]]:
    """Quote-evidence gate policy (``pat_gate_policy``) from the installed database or the seed."""
    memory = open_memory()
    policy = memory.gate_policy()
    memory.close()
    return policy
