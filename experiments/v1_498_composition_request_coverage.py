"""Probe where finite-set recombination covers varied chat wording.

This is a small Codex-authored development diagnostic, not an independent
transfer benchmark. Each request runs in a fresh CRMS chat process against the
same reviewed synthetic knowledge and procedures. It records both successful
compositions and honest gaps so later language changes cannot quietly turn
unsupported requests into unsupported answers.
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_492_reasoned_filter_language_coverage import (
    build_case, learn_connective_procedures, teach_relation_surface,
)
from v1_497_composition_derived_practice import run_chat, require
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


CASES = (
    ("licensed baseline",
     "From values 12, 4, 4, 9, and 7, keep only the values that Nia reaches, "
     "then remove duplicate values then reverse the list.",
     "[9, 4, 12]", None),
    ("licensed after construction",
     "From values 12, 4, 4, 9, and 7, keep only the values that Nia reaches, "
     "then reverse the list after removing duplicate values.",
     "[9, 4, 12]", None),
    ("taught relation wording in chat",
     "From values 12, 4, 4, 9, and 7, keep only the values Nia can reach, "
     "then remove duplicate values then reverse the list.",
     "[9, 4, 12]", None),
    ("unsupported operation alias",
     "From values 12, 4, 4, 9, and 7, keep only the values Nia can reach, "
     "then deduplicate and reverse the list.",
     None, "no taught phrase evidence"),
    ("unlicensed relation paraphrase",
     "From values 12, 4, 4, 9, and 7, keep only values reachable by Nia, "
     "then remove duplicate values then reverse the list.",
     None, "unambiguous stored relation and subject"),
    ("unsupported compound request frame",
     "Take 12, 4, 4, 9, and 7; retain values Nia reaches, then remove "
     "duplicate values and reverse the list.",
     None, "I don't know this from the sources and facts I have"),
)


def main() -> None:
    knowledge, _ = build_case()
    procedures = learn_connective_procedures()
    index = CRMSResearchIndex()
    teach_relation_surface(knowledge, index)

    completed = 0
    abstained = 0
    with tempfile.TemporaryDirectory(prefix="crms-composition-coverage-") as d:
        root = Path(d)
        knowledge_path = root / "model.sqlite3"
        procedures_path = root / "procedures.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(procedures_path)
        index.save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        for name, request, expected, expected_gap in CASES:
            # Isolate every chat state file so a previous answer cannot
            # inflate coverage or contaminate the abstention check.
            session = root / f"session-{len([p for p in root.glob('session-*')])}"
            session.mkdir()
            for source in (knowledge_path, procedures_path, index_path,
                           root / "math.json", root / "translations.json"):
                shutil.copy2(source, session / source.name)
            output = run_chat(session, session / knowledge_path.name,
                              session / procedures_path.name,
                              session / index_path.name, (request,))
            if expected is not None:
                require(expected in output,
                        f"{name} stopped completing through chat:\n{output}")
                completed += 1
                print(f"{name}: completed with cited/proof-backed result: PASS")
            else:
                require(expected_gap in output and "[9, 4, 12]" not in output,
                        f"{name} did not preserve its current abstention boundary:\n"
                        f"{output}")
                abstained += 1
                print(f"{name}: no unsupported positive result: PASS")

    print(f"coverage: {completed}/{len(CASES)} requests completed; "
          f"{abstained}/{len(CASES)} abstained on unsupported wording/frame")
    print("scope: authored development diagnostic; not an independent transfer result")


if __name__ == "__main__":
    main()
