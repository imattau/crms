"""Default pattern resources: an in-memory store seeded from the visible seed file.

Used where no packaged model supplies pattern memory yet (generation clarity
pass, `/compose` intake). The result is cached for the process.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from crms_pattern_memory import PatternMemory


@lru_cache(maxsize=1)
def seeded_resources() -> tuple[Any, tuple, dict, tuple]:
    """(language, specs, params, rewrites) from the seed file."""
    memory = PatternMemory(":memory:")
    memory.seed()
    resources = (memory.language(), tuple(memory.specs()), memory.params(),
                 tuple(memory.rewrites()))
    memory.close()
    return resources
