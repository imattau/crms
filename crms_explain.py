"""Verified, source-cited explanations for stored-fact inference proofs."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any, Mapping

from crms_rule_proof import verify_inference_proof
from crms_text import tokens


def _claim_key(claim: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    return tuple(tokens(str(claim.get(field, "")))
                 for field in ("subject", "relation", "object"))


def _structured_claim(text: str) -> tuple[str, str, str] | None:
    match = re.fullmatch(r"\s*(.+?)\s+—\s+(.+?)\s+→\s+(.+?)\s*", text)
    return tuple(part.strip() for part in match.groups()) if match else None


def render_verified_explanation(knowledge: Any, proof: Mapping[str, Any], *,
                                complete: bool = True,
                                short_answer: str | None = None) -> str | None:
    """Render one independently verified proof, or refuse/fall back with None.

    Every prose claim must round-trip through CRMS's learned fact patterns.
    Structured claims use the explicit ``subject — relation → object`` syntax,
    which is itself parsed by ``propose_facts``.
    """
    conclusion = proof.get("conclusion")
    if not isinstance(conclusion, Mapping):
        return None
    facts = [asdict(item) for item in knowledge.facts()]
    rules = [asdict(item) for item in knowledge._inference_rules_for_use()]
    check = verify_inference_proof(
        proof, facts, rules, expected_conclusion=conclusion,
        fact_lookup=knowledge._proof_fact_is_present)
    if not check.valid:
        return None

    def sentence_for(claim: Mapping[str, Any]) -> tuple[str, bool]:
        rows = knowledge.realize_claim(
            str(claim["subject"]), str(claim["relation"]),
            str(claim["object"]))
        if rows:
            return str(rows[0]["sentence"]), False
        return (f"{claim['subject']} — {claim['relation']} → "
                f"{claim['object']}", True)

    def source_list(node: Mapping[str, Any]) -> list[str]:
        found: set[str] = set()
        fact = node.get("fact")
        if isinstance(fact, Mapping):
            found.update(str(item) for item in fact.get("sources", ()) if item)
        type_fact = node.get("relation_type_fact")
        if isinstance(type_fact, Mapping):
            found.update(str(item) for item in type_fact.get("sources", ()) if item)
        for premise in node.get("premises", ()):
            if isinstance(premise, Mapping):
                found.update(source_list(premise))
        for fact_item in node.get("middle_kind_facts", ()):
            if isinstance(fact_item, Mapping):
                found.update(str(item) for item in fact_item.get("sources", ()) if item)
        return sorted(found)

    claims: list[tuple[str, tuple[tuple[str, ...], ...], bool]] = []
    paragraphs: list[str] = []

    def visit(node: Mapping[str, Any]) -> None:
        for premise in node.get("premises", ()):
            if isinstance(premise, Mapping):
                visit(premise)
        claim = node.get("conclusion")
        if not isinstance(claim, Mapping):
            return
        sentence, structured = sentence_for(claim)
        key = _claim_key(claim)
        claims.append((sentence, key, structured))
        sources = source_list(node)
        citation = (" [Sources: " + "; ".join(sources) + "]") if sources else ""
        kind = node.get("kind")
        if kind == "fact":
            paragraph = sentence + citation
        else:
            premises = [item.get("conclusion") for item in node.get("premises", ())
                        if isinstance(item, Mapping)]
            premise_text = []
            for item in premises:
                if isinstance(item, Mapping):
                    premise_text.append(sentence_for(item)[0])
            rule = node.get("rule", {})
            label = (f"rule {rule.get('rule_id')}" if isinstance(rule, Mapping)
                     else str(node.get("schema", {}).get("schema_id", "schema")))
            because = " and ".join(premise_text) if premise_text else "the verified premises"
            paragraph = f"Because {because}, {sentence} ({label}).{citation}"
        paragraphs.append(paragraph)

    visit(proof)
    answer, answer_structured = sentence_for(conclusion)
    answer_key = _claim_key(conclusion)
    claims.append((answer, answer_key, answer_structured))
    short_answer = (short_answer.strip() if isinstance(short_answer, str)
                    else "")
    short_polar = (short_answer if short_answer.casefold() in {"yes", "no"}
                   else None)
    output = [(short_polar + "." if short_polar else answer), *paragraphs]
    if not complete:
        output.append("Other proofs may exist; this search did not enumerate them all.")

    # Validate every generated proposition against the same learned parser.
    # Citation suffixes are removed before parsing; structured syntax is also
    # recognized in propose_facts as an explicit representation.
    for statement, expected, _structured in claims:
        proposals = knowledge.propose_facts(statement, source="explanation:round-trip")
        recovered = {
            (tokens(item.subject), tokens(item.relation), tokens(item.object))
            for item in proposals
        }
        if expected not in recovered:
            return None
    return "\n\n".join(output)
