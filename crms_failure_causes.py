"""Group relation-engine failures by cause (Phase 12, teacher-loop step 2).

For every graded question the engine's result is placed in one bucket:

    correct
    wrong_boundary     the answer overlaps the gold value (a truncated or extended name)
    wrong_entity       the answer shares nothing with the gold value
    no_question        no question pattern parses the question
    retrieval_empty    nothing was retrieved for the entity
    retrieval_miss     sentences were retrieved but none contains the gold value
    infobox_only       the gold value appears only in infobox residue ("director = X"),
                       not in prose: the oracle label is real but prose cannot answer it
    no_sentence        a prose sentence contains the gold value but no spec reads it
    vetoed_or_tied     candidates existed and the engine abstained (veto or tie)

Each non-correct bucket keeps exemplars. `no_sentence` exemplars are what a teacher
turns into new specs; `retrieval_*` are not pattern problems and are reported apart.
"""
from __future__ import annotations

import collections
from typing import Any, Sequence

from crms_oracle_eval import _norm, matches


def _contains(sentence: str, gold: str) -> bool:
    g = _norm(gold)
    return bool(g) and g in _norm(sentence)


def _structured(sentence: str) -> bool:
    """Infobox or template residue rather than a prose sentence."""
    return " = " in sentence or sentence.count(" ; ") >= 2 or sentence.startswith("{{")


def classify(engine: Any, item: dict[str, Any]) -> dict[str, Any]:
    question, gold = item["question"], item["gold"]
    answer = engine.ask(question)
    if answer is not None:
        if matches(gold, answer.answer):
            return {"cause": "correct"}
        a, g = _norm(answer.value), _norm(gold)
        overlap = bool(a and g and (a in g or g in a or set(a.split()) & set(g.split())))
        return {"cause": "wrong_boundary" if overlap else "wrong_entity",
                "answer": answer.answer, "source": answer.source, "spec": answer.spec}
    prepared = engine.pool_for(question)
    if prepared is None:
        return {"cause": "no_question"}
    entity, pool = prepared
    if not pool:
        return {"cause": "retrieval_empty", "entity": entity}
    holders = [(t, s) for t, s in pool if _contains(s, gold)]
    if not holders:
        return {"cause": "retrieval_miss", "entity": entity}
    holders = [h for h in holders if not _structured(h[1])] or \
        [("", "")]
    if holders[0] == ("", ""):
        return {"cause": "infobox_only", "entity": entity}
    if engine.instances(question) is None:
        return {"cause": "no_sentence", "entity": entity, "sentence": holders[0][1],
                "source": holders[0][0]}
    return {"cause": "vetoed_or_tied", "entity": entity, "sentence": holders[0][1]}


def group(engine: Any, items: Sequence[dict[str, Any]], *, keep: int = 5) -> dict[str, Any]:
    per: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    total: collections.Counter = collections.Counter()
    examples: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for item in items:
        row = classify(engine, item)
        cause = row["cause"]
        total[cause] += 1
        per[item["relation"]][cause] += 1
        if cause != "correct" and len(examples[cause]) < keep * 6:
            examples[cause].append({"relation": item["relation"], "question": item["question"],
                                    "gold": item["gold"], **{k: v for k, v in row.items()
                                                             if k != "cause"}})
    n = len(items)
    return {"questions": n, "causes": dict(total),
            "pattern_addressable": total["no_sentence"] + total["no_question"],
            "label_only_in_infobox": total["infobox_only"],
            "retrieval_problems": total["retrieval_empty"] + total["retrieval_miss"],
            "per_relation": {r: dict(c) for r, c in sorted(per.items())},
            "examples": {k: v[:keep * 6] for k, v in examples.items()}}
