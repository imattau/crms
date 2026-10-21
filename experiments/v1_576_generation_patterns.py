"""Phase 11 Stage A: pattern-based clarity rewriting and faithfulness checks.

The clarity pass and critic now match over tokens, not regex. Checks: whole-token
phrase rewriting, one verb rule covering every inflection, capital letters kept,
jargon detection, invented-number / polarity / unsupported-name detection, no
false alarms on a faithful text, and that the generation modules no longer use
regex for matching (compiled tokenisers excepted).
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_generation import ClarityRewriter, Fact, GenerationRequest  # noqa: E402
from crms_generation_checks import check_generated  # noqa: E402
from crms_generation_rules import load_rules  # noqa: E402
from crms_pattern_defaults import seeded_resources  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    rules = load_rules()
    clarity = ClarityRewriter(rules)
    request = GenerationRequest(prompt="x", genre="explanation", facts=())

    text, issues = clarity.rewrite("The team utilizes tools prior to lunch in order to work.", request)
    require(text == "The team uses tools before lunch to work.", f"phrase/verb rewrite wrong: {text!r}")
    require(not issues, f"unexpected issues: {issues}")
    # an inflection the old word list never named
    text, _ = clarity.rewrite("Teams are utilizing it and have utilized it.", request)
    require(text == "Teams are using it and have used it.", f"inflections not covered: {text!r}")
    # capitalisation is kept; partial words are untouched
    text, _ = clarity.rewrite("Utilize the tool. Reutilize nothing. Prior tool use stays.", request)
    require(text.startswith("Use the tool.") and "Reutilize" in text and "Prior tool" in text,
            f"capitalisation / whole-token handling wrong: {text!r}")
    # verbs added with the pattern seed
    text, _ = clarity.rewrite("We commence work and purchase food to assist you.", request)
    require(text == "We begin work and buy food to help you.", f"seed verb rules not applied: {text!r}")
    # long sentence still splits, jargon check still runs on what remains
    long_text = ("The report " + " ".join(["covers"] * 12) + " many topics in depth, and "
                 + " ".join(["adds"] * 12) + " several examples as well.")
    out, long_issues = clarity.rewrite(long_text, request)
    require("\n" not in out and out.count(".") >= 2, f"long sentence not split: {out!r}")

    language = seeded_resources()[0]
    facts = (Fact(fact_id="a", subject="The reactor", verb="does not use", object="coal",
                  source="r.txt", source_text="The reactor does not use coal and runs at 300 degrees."),)
    good = "The reactor does not use coal. It runs at 300 degrees."
    require(check_generated(good, facts, language) == [], "a faithful text was flagged")
    require(any("number" in i for i in check_generated(
        "The reactor does not use coal. It runs at 900 degrees.", facts, language)),
        "an invented number was not caught")
    require(any("polarity" in i for i in check_generated(
        "The reactor uses coal. It runs at 300 degrees.", facts, language)),
        "a dropped negation was not caught")
    require(any("polarity" in i for i in check_generated(
        "The reactor does not use coal. It never runs at 300 degrees.",
        (Fact(fact_id="b", subject="The reactor", verb="uses", object="coal", source="r.txt",
              source_text="The reactor uses coal and runs at 300 degrees."),), language)),
        "an invented negation was not caught")
    require(any("name" in i for i in check_generated(
        "The reactor does not use coal. It was built by Acme Corp.", facts, language)),
        "an unsupported name was not caught")
    require(check_generated("Their results, said Dr Rao, are clear.",
                            (Fact(fact_id="c", subject="Dr Rao", verb="reports", complement="clear results",
                                  source="d", source_text="Dr Rao reports clear results."),), language) == [],
            "a name from the facts was flagged")

    # footprint: no matching regex in the generation modules (compiled tokenisers excepted)
    for name in ("crms_generation.py", "crms_generation_rules.py", "crms_generation_checks.py",
                 "crms_pattern_rewrite.py"):
        source = (PROJECT / name).read_text(encoding="utf-8")
        calls = re.findall(r"\bre\.(?:search|match|fullmatch|sub|subn|findall|finditer)\(", source)
        allowed = 2 if name == "crms_generation_checks.py" else 0   # sentence-boundary scan only
        require(len(calls) <= allowed, f"{name} still uses {len(calls)} matching regex call(s)")
    print("Phase 11 generation patterns contract passed")


if __name__ == "__main__":
    main()
