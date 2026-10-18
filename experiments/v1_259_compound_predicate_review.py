"""Check compound-verb candidate matching and bounded negation extraction.

Run from the project root with:
    python3 experiments/v1_259_compound_predicate_review.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document(
        "unix", "Unix history",
        "Ken Thompson co-created Unix at Bell Labs.", "unix.txt")
    index.add_document(
        "capital", "Australian capitals",
        "Canberra is the capital of Australia, not Sydney.", "capital.txt")
    index.add_document(
        "language", "C language history",
        "Dennis Ritchie created the C language at Bell Labs.", "language.txt")
    kb = CRMSKnowledgeBase()

    compound = kb.research("What did Ken Thompson co-create?", index)
    if compound.status != "needs_review":
        raise SystemExit(f"compound-predicate candidate was not reviewable: {compound}")
    if not any((candidate.subject, candidate.relation, candidate.object,
                candidate.polarity) ==
               ("Ken Thompson", "co-created", "Unix", True)
               for candidate in compound.candidates or []):
        raise SystemExit("co-create wording failed to match its complete candidate")

    capital = kb.research("What is the capital of Australia?", index)
    claims = {(item.subject, item.relation, item.object, item.polarity)
              for item in capital.candidates or []}
    if (("Canberra", "capital of", "Australia", True) not in claims
            or ("Sydney", "capital of", "Australia", False) not in claims
            or any("not Sydney" in item.object for item in capital.candidates or [])):
        raise SystemExit(f"negation was not separated from the positive claim: {claims}")
    if kb.facts() or kb.negative_facts():
        raise SystemExit("source candidates entered the fact store without review")

    language = kb.research("Who created the C language?", index)
    if not any((item.subject, item.relation, item.object) ==
               ("Dennis Ritchie", "created", "the C language")
               for item in language.candidates or []):
        raise SystemExit("multiword object was truncated during extraction")

    print("compound predicate review diagnostic: PASS")
    print("hyphenated verb inversion, negation polarity, full object span, "
          "review-only storage: PASS")


if __name__ == "__main__":
    main()
