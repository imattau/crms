"""Check safe incremental filtering of learned procedure version spaces."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel


def main() -> None:
    phrase = "add one to every value"
    first = ([1, -2], [2, -1])
    second = ([4, 3], [5, 4])
    model = CRMSModel(max_composition_depth=1, max_workers=1)

    initial = model.teach(phrase, [first])
    if initial.status != "need_more_examples" or initial.candidate_count < 2:
        raise SystemExit(f"first example did not retain an ambiguous version space: {initial}")
    initial_work = model._last_search_expansions
    if initial_work <= 0:
        raise SystemExit("initial version-space search did not record search work")

    incremental = model.teach(phrase, [second])
    if (incremental.status != "learned"
            or model._last_search_expansions != 0):
        raise SystemExit(
            "appended example did not resolve the cached version space without re-search: "
            f"{incremental}, expansions={model._last_search_expansions}")

    batch = CRMSModel(max_composition_depth=1, max_workers=1)
    reference = batch.teach(phrase, [first, second])
    if (reference.status != incremental.status
            or reference.procedure != incremental.procedure):
        raise SystemExit(f"incremental filtering differed from fresh search: {incremental} / {reference}")

    replaced = model.teach(phrase, [first], replace=True)
    if replaced.status != "need_more_examples" or model._last_search_expansions <= 0:
        raise SystemExit("replace=True reused a stale candidate version space")
    if not model.forget(phrase):
        raise SystemExit("forget did not remove the instruction")
    after_forget = model.teach(phrase, [first])
    if model._last_search_expansions <= 0:
        raise SystemExit("forgotten instruction reused a stale candidate version space")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        loaded = restored.teach(phrase, [second])
        if restored._last_search_expansions <= 0:
            raise SystemExit("loaded memory unexpectedly restored a transient search cache")
        if loaded.status not in {"learned", "need_more_examples"}:
            raise SystemExit(f"loaded demonstrations produced an invalid result: {loaded}")

    bounded = CRMSModel(max_composition_depth=1, max_workers=1)
    for index in range(20):
        bounded.teach(f"cache capacity example {index}", [([1, 2], [1, 2])])
    if len(bounded._candidate_space_cache) != 16:
        raise SystemExit("transient candidate cache exceeded or missed its entry cap")
    if "cache capacity example 0" in bounded._candidate_space_cache:
        raise SystemExit("candidate cache did not evict its least-recently-used entry")

    print("incremental candidate-space diagnostic: PASS")
    print("complete search reuse, batch parity, replace/forget invalidation, transient bounded LRU cache: PASS")


if __name__ == "__main__":
    main()
