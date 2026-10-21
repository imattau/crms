"""Phase 11 Stage E: regex footprint ratchet.

Counts call sites of the ``re`` module (``re.compile``, ``re.search``, ...) per
top-level ``crms_*.py`` module and compares with the recorded footprint in
``corpus/phase11_eval/regex_footprint.json``. A module may never gain regex
sites; modules in ``migrated`` may only keep sites listed with a reason (word
splitting, character classes, literal command syntax). Run with ``--write`` to
refresh the record after a deliberate reduction.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "corpus" / "phase11_eval" / "regex_footprint.json"
FUNCTIONS = {"compile", "search", "match", "fullmatch", "findall", "finditer",
             "sub", "subn", "split"}


def count_sites(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    total = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re" and node.func.attr in FUNCTIONS):
            total += 1
    return total


def footprint() -> dict[str, int]:
    return {p.name: count_sites(p) for p in sorted(PROJECT.glob("crms_*.py"))}


def main() -> int:
    current = footprint()
    if "--write" in sys.argv:
        previous = json.loads(RECORD.read_text()) if RECORD.is_file() else {}
        RECORD.write_text(json.dumps({
            "note": "regex call sites per module; the ratchet only allows decreases",
            "migrated": previous.get("migrated", {}),
            "sites": current, "total": sum(current.values())},
            indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("written", sum(current.values()))
        return 0
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    failures = []
    for name, count in current.items():
        allowed = record["sites"].get(name, 0)
        if count > allowed:
            failures.append(f"{name}: {count} regex sites, recorded {allowed}")
    for name, reasons in record.get("migrated", {}).items():
        allowed = len(reasons)
        if current.get(name, 0) > allowed:
            failures.append(f"{name}: migrated module has {current.get(name, 0)} "
                            f"sites, {allowed} justified")
    print(f"modules {len(current)} total regex sites {sum(current.values())} "
          f"(recorded {record['total']})")
    if failures:
        print("FAILED")
        for line in failures:
            print(" ", line)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
