"""Phase 11 Stage B: parity of the gate's pattern rules with the retired regexes.

The ``answer_type`` and ``locative`` families in the SQL ``pat_intent`` table
replaced regex predicates in ``crms_nl_gate.py``. This test keeps a frozen copy
of the old predicates as a reference (the only regexes allowed to remain for
that purpose) and requires the rules to agree on a project-authored suite. When
a local research index exists it also samples sentences from it; the only
tolerated disagreements are old false positives where a regex word boundary
matched inside a hyphenated word.
"""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import crms_nl_gate as gate  # noqa: E402
from crms_patterns import sentence_spans  # noqa: E402

_tokens = gate._tokens


# ---- frozen reference (the retired implementation) --------------------------
def ref_answer_type(question: str) -> str | None:
    q = question.casefold().strip()
    if re.match(r"^(is|are|was|were|did|does|do|has|have)\b", q):
        return "POLAR"
    if re.search(r"\b(who|whom)\b", q):
        return "WHO"
    if re.search(r"\b(when|what year|in what year)\b", q):
        return "WHEN"
    if re.search(r"\bwhere\b", q):
        return "WHERE"
    if re.search(
            r"\b(?:which\s+(?:country|city|continent|range|mountain range|"
            r"river|region|state|institute|university|laboratory|"
            r"research\s+center|observatory)|"
            r"(?:at|in)\s+which\s+(?:institute|university|laboratory|"
            r"research\s+center|observatory))\b", q):
        return "WHERE"
    if re.search(r"\b(birthplace|place of birth|workplace|location of)\b", q):
        return "WHERE"
    if (re.search(r"\bhow\s+(tall|high|long|big|old)\b|\b(height|temperature|boiling point|melting point)\b", q)):
        return "MEASURE"
    if re.search(r"\bhow\s+(many|much)\b", q):
        return "COUNT"
    if re.match(r"^how\s+(?:can|do|does|should|would)\b", q):
        return "HOW"
    if re.match(r"^(what|define)\s+(is|are)\b", q) or re.match(
            r"^what\s+(does|do)\b", q):
        return "DEF"
    if re.search(r"\b(what|which)\b", q):
        return "NAME"
    return None


def ref_has_locative(sentence: str) -> bool:
    """Require a bounded location-bearing predicate, not any ``in`` phrase."""
    text = " ".join(_tokens(sentence)).casefold()
    preposition = r"(?:in|at|near|on|within|by|through|across|along|from|to)"
    explicit = (
        rf"\b(?:located|based|situated|born|resides?|lives?|lived|"
        rf"works?|worked|lies|lie|stands?|stood|sits?|sat)\s+{preposition}\b",
        rf"\b(?:flows?|flowed|runs?|ran|passes?|passed|cross(?:es|ed)|"
        rf"extends?|extended|borders?|originates?|originated)\s+{preposition}\b",
        rf"\b(?:is|are|was|were|be|been|being)\s+{preposition}\b",
        # Nominal locatives such as "The Colosseum is an amphitheatre in Rome".
        rf"\b(?:is|are|was|were)\s+(?:a|an|the)\s+"
        rf"[\w'-]+\s+{preposition}\b",
    )
    if any(re.search(pattern, text) for pattern in explicit):
        return True
    words = text.split()
    if (words and words[0] in {"in", "at", "near", "within", "across", "along"}
            and re.search(
                r"\b(?:lie|lies|lay|stand|stands|stood|sit|sits|sat|run|runs|ran|"
                r"rise|rises|rose|exist|exists|existed)\b", text)):
        return True
    # A where-clause expresses the place relation after its target:
    # "Bletchley Park is where Alan Turing worked".
    return bool(re.search(
        r"\bwhere\b.{0,100}\b(?:lie|lies|lay|stand|stands|stood|sit|sits|sat|"
        r"work|works|worked|live|lives|lived|reside|resides|resided)\b", text))


QUESTIONS = [
    "Who founded Apple?", "Whom did she marry?", "Whose book is this?", "who's there",
    "When did Rome fall?", "What year did the war end?", "In what year was it built?",
    "what years did he reign", "Where is Paris?", "Which country is Lima in?",
    "Which states border Ohio?", "Which mountain range includes K2?",
    "At which university did she study?", "In which research center was it made?",
    "What is the birthplace of Mozart?", "Where-ever it was", "location of Rome",
    "How tall is Everest?", "How  old is the moon?", "What is the boiling point of lead?",
    "How many people live in Rome?", "How much does it weigh?", "How do I bake bread?",
    "How should I store it?", "What is love?", "Define entropy", "What does a dentist do?",
    "What colour is the sky?", "Which one is bigger?", "Is Paris in France?",
    "Did Newton write it?", "Has he left?", "'Who was it?", "", "   ", "Tell me about Rome",
]
SENTENCES = [
    "The Colosseum is an amphitheatre in Rome.",
    "The river flows through the valley and into the sea.",
    "She was born in Lyon.", "He lives near the lake.", "The town lies on the coast.",
    "In the valley lie three villages.", "Bletchley Park is where Alan Turing worked.",
    "The company is based in Dublin.", "It is the 14th in the line of succession.",
    "The road passes through the town.", "They crossed the border into Spain.",
    "The treaty was signed in 1648.", "Rome is big.", "Paris is a city, in France.",
    "The pass in the mountains was closed.", "Water boils at 100 degrees.",
]
HYPHEN_OLD_FALSE_POSITIVES = [
    "They promote balanced diets, and overall well-being through proper food choices.",
    "In 2014, the studio opened a stand-alone operation in Dublin, Ireland.",
]


def main() -> int:
    failures: list[str] = []
    for q in QUESTIONS:
        old, new = ref_answer_type(q), gate._answer_type(q)
        if old != new:
            failures.append(f"answer_type {q!r}: old {old} new {new}")
    for s in SENTENCES:
        old, new = ref_has_locative(s), gate._has_locative_predicate(s)
        if old != new:
            failures.append(f"locative {s!r}: old {old} new {new}")
    for s in HYPHEN_OLD_FALSE_POSITIVES:     # known, documented improvement
        if not ref_has_locative(s) or gate._has_locative_predicate(s):
            failures.append(f"hyphen case changed: {s!r}")

    sampled = diffs = 0
    index = PROJECT / "data" / "crms_simplewiki_research.sqlite"
    if index.is_file():
        connection = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
        rows = connection.execute(
            "SELECT substr(body,1,3000) FROM source_documents "
            "ORDER BY (rowid*2654435761+7)%4294967296 LIMIT 1500").fetchall()
        for (body,) in rows:
            for a, e in sentence_spans(body):
                text = body[a:e].strip()
                if not 20 < len(text) < 400:
                    continue
                sampled += 1
                if ref_has_locative(text) != gate._has_locative_predicate(text):
                    diffs += 1
                    hyphenated = any("-" in w for w in _tokens(text))
                    if not (ref_has_locative(text) and hyphenated):
                        failures.append(f"unexplained locative difference: {text[:120]!r}")
    print(f"questions {len(QUESTIONS)} sentences {len(SENTENCES)} sampled {sampled} "
          f"tolerated differences {diffs}")
    if failures:
        print("FAILED")
        for line in failures[:20]:
            print(" ", line)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
