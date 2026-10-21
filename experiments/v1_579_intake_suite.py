"""Phase 11 Stage A: project-authored intake suite (not independent authorship).

Ten cases over agent, date, place, naming, population, death, role, and merger
relations, plus conflict, pronoun-only, and nothing-answerable controls. Checks
status, fact counts, required and forbidden text, copy ratio, and determinism.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_generate import request_from_mapping  # noqa: E402
from crms_generation import GenerationEngine, copy_ratio  # noqa: E402
from crms_generation_rules import load_rules  # noqa: E402
from crms_source_intake import intake_facts  # noqa: E402

SUITE = PROJECT / "corpus" / "phase11_eval" / "intake_suite.json"


def run_suite(engine: GenerationEngine | None = None) -> list[dict]:
    engine = engine or GenerationEngine(load_rules())
    rows = []
    for case in json.loads(SUITE.read_text(encoding="utf-8"))["cases"]:
        raw = {k: v for k, v in case.items() if k != "expect"}
        raw.update({"audience": "general", "style": "plain"})
        documents = [(d["name"], d["text"]) for d in case["source_documents"]]
        facts, _report = intake_facts(case["intake"]["questions"], documents)
        result = engine.generate(request_from_mapping(raw))
        copy = copy_ratio(result.text, [t for _n, t in documents]) if result.text else 0.0
        failures = []
        expect = case["expect"]
        if result.status != expect["status"]:
            failures.append(f"status {result.status!r} != {expect['status']!r}")
        if len(facts) != expect["facts"]:
            failures.append(f"{len(facts)} facts != {expect['facts']}")
        for needle in expect.get("contains", ()):
            if needle not in result.text:
                failures.append(f"missing {needle!r}")
        for needle in expect.get("excludes", ()):
            if needle in result.text:
                failures.append(f"contains forbidden {needle!r}")
        if expect.get("max_copy") is not None and copy > expect["max_copy"]:
            failures.append(f"copy ratio {copy:.2f} > {expect['max_copy']}")
        again = engine.generate(request_from_mapping(raw))
        if again.text != result.text:
            failures.append("not deterministic")
        rows.append({"id": case["id"], "passed": not failures, "failures": failures,
                     "status": result.status, "facts": len(facts), "copy_ratio": round(copy, 3)})
    return rows


def main() -> None:
    rows = run_suite()
    failed = [r for r in rows if not r["passed"]]
    if failed:
        raise SystemExit(f"intake suite failures: {failed}")
    print(f"Phase 11 intake suite passed: {len(rows)}/{len(rows)} cases")


if __name__ == "__main__":
    main()
