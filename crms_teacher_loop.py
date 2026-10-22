"""Automated teacher loop for relation specs (Phase 12, workstream 2).

One round:

    measure   the system answers a training split; every miss is grouped by cause
    brief     the misses (with the author's supporting sentence) go to a teacher
              session as a JSON brief; the teacher never sees the dev split
    propose   the teacher writes spec proposals to a JSON file
    verify    each proposal is checked by the deterministic spec verifier (replay,
              held-out, contrast, verb-swap, corpus fire-rate, bank non-regression)
    accept    only a verified proposal enters pattern memory, logged as a change
    remeasure the dev split is answered again; a round is kept only if the dev
              wrong share did not rise and dev utility did not fall

The teacher proposes; nothing here trusts it. Questions need an author-supplied
gold answer and supporting sentence (`crms_independent_eval.load_set` format).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from crms_independent_eval import oracle_label, summarise
from crms_patterns import __doc__ as PATTERN_DOC
from crms_relation_specs import RelationEngine, RelationSpec
from crms_spec_verifier import candidate_tuple, expand, verify_spec

Item = Mapping[str, Any]


def split(items: Sequence[Item]) -> tuple[list[Item], list[Item]]:
    """Deterministic train/dev split by item id (about half each)."""
    train, dev = [], []
    for item in items:
        (train if int(hashlib.sha1(item["id"].encode()).hexdigest(), 16) % 2 == 0 else dev).append(item)
    return train, dev


class CorpusEngines:
    """One relation engine per corpus label, all sharing one pattern memory."""

    def __init__(self, memory: Any, sources: Mapping[str, Any]) -> None:
        self.memory = memory
        self.engines = {c: RelationEngine(memory.language(), memory.specs(), s, memory.params())
                        for c, s in sources.items()}

    def ask(self, item: Item, **kw: Any):
        return self.engines[item["corpus"]].ask(item["question"], **kw)

    def refresh(self) -> None:
        for engine in self.engines.values():
            engine.specs = list(self.memory.specs())
            engine.params = {**engine.params, **self.memory.params()}


def measure(engines: CorpusEngines, items: Sequence[Item]) -> dict[str, Any]:
    rows, labels = [], []
    for item in items:
        answer = engines.ask(item)
        text = answer.answer if answer else None
        label = oracle_label(item, text)
        labels.append(label)
        rows.append({"id": item["id"], "label": label, "answer": text,
                     "spec": answer.spec if answer else None})
    return {"summary": summarise(items, labels), "rows": rows}


def failures(items: Sequence[Item], rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Misses worth teaching: answerable and not correct (abstained or wrong)."""
    out = []
    for item, row in zip(items, rows):
        if item["answerable"] and row["label"] != "correct":
            out.append({"id": item["id"], "type": item.get("type", "?"), "question": item["question"],
                        "gold": item["gold"], "support": item["support"], "title": item.get("title", ""),
                        "system": row["answer"], "outcome": row["label"]})
    return out


def write_brief(path: str | Path, train_failures: Sequence[Mapping[str, Any]], engines: CorpusEngines,
                *, round_no: int, per_type: int = 10,
                previous: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    by_type: dict[str, list] = {}
    for f in train_failures:
        by_type.setdefault(f["type"], []).append(f)
    exemplars = {t: rows[:per_type] for t, rows in sorted(by_type.items())}
    specs = engines.memory.specs()
    brief = {
        "round": round_no,
        "task": ("Propose relation specs that would answer these missed questions from their "
                 "supporting sentences. Prefer a spec that generalises over a whole question "
                 "shape (e.g. 'What is E', 'How many X does E have', 'Where is E') over one "
                 "that fits a single exemplar. An answer must be a span of the supporting "
                 "sentence, bound to capture A. Do not answer unanswerable questions."),
        "pattern_language": PATTERN_DOC,
        "proposal_schema": {
            "name": "snake_case, unique", "priority": "int 1-99, lower tries first",
            "question_patterns": ["pattern over the question; E = the entity, bind it with E or NP:q"],
            "sentence_patterns": ["pattern over a source sentence; capture the answer as :A"],
            "template": "answer sentence using {A}, {E}, {cop}, {v.q} ...",
            "support": "list of {q, S, A, E}: at least 2 real exemplars the spec must answer",
            "heldout": "list of {q, S, A, E}: at least 1 exemplar not used to design the patterns",
            "contrast": "list of {q, S}: sentences that mention the entity but must NOT answer",
            "rationale": "one sentence"},
        "existing_specs": [{"name": s.name, "question_patterns": list(s.question_patterns)} for s in specs],
        "exemplars_by_type": exemplars,
        "counts_by_type": {t: len(r) for t, r in sorted(by_type.items())},
        "previous_round_rejections": list(previous),   # name + reasons: tighten, do not repeat
    }
    Path(path).write_text(json.dumps(brief, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return brief


def make_bank(engines: CorpusEngines, controls: Sequence[Item]) -> Callable[..., Mapping[str, str]]:
    """Bank function for the verifier: status of every control with a candidate added."""
    def bank(candidate: tuple | None, retired: tuple[str, ...]) -> Mapping[str, str]:
        out: dict[str, str] = {}
        for item in controls:
            answer = engines.engines[item["corpus"]].ask(
                item["question"], extra=[candidate] if candidate else (), exclude=retired)
            label = oracle_label(item, answer.answer if answer else None)
            if label == "wrong" and not item["answerable"]:
                label = "hallucinated"
            out[item["id"]] = label
        return out
    return bank


def spec_precision(engines: CorpusEngines, candidate: tuple, items: Sequence[Item]) -> dict[str, int]:
    """How the candidate spec alone does on labelled items: answered / correct / wrong."""
    name = candidate[0]
    counts = {"answered": 0, "correct": 0, "wrong": 0}
    for item in items:
        answer = engines.engines[item["corpus"]].ask(item["question"], extra=[candidate])
        if answer is None or answer.spec != name:
            continue
        counts["answered"] += 1
        label = oracle_label(item, answer.answer)
        counts["correct" if label == "correct" else "wrong"] += 1
    return counts


def apply_proposals(proposals: Sequence[dict[str, Any]], engines: CorpusEngines,
                    controls: Sequence[Item], corpus_sentences: Sequence[str], *,
                    round_no: int, precision_items: Sequence[Item] = (),
                    min_answered: int = 3, max_wrong_share: float = 0.25
                    ) -> list[dict[str, Any]]:
    """Verify each proposal; accept the ones that pass, one at a time.

    The random-sentence fire-rate check swaps the question's entity for a sentence's
    own opening words, so it flags every definitional or counting spec (any "X is a Y"
    sentence legitimately answers "What is X?"). When `precision_items` are given the
    fire-rate check is replaced by measured precision on those labelled questions:
    the spec must answer at least `min_answered` of them and be wrong on at most
    `max_wrong_share`. Relation specs keep the fire-rate check (no `precision_items`)."""
    memory = engines.memory
    raw_bank = make_bank(engines, controls)
    cache: dict[tuple, Mapping[str, str]] = {}

    def bank(candidate, retired):
        """The 'before' statuses depend only on the accepted specs, so reuse them."""
        if candidate is None:
            key = tuple(sorted(s.name for s in memory.specs()))
            if key not in cache:
                cache[key] = raw_bank(None, retired)
            return cache[key]
        return raw_bank(candidate, retired)
    verdicts = []
    for raw in proposals:
        proposal = expand(dict(raw))
        name = proposal.get("name", "?")
        existing = {s.name for s in memory.specs()}
        if name in existing:
            verdicts.append({"name": name, "accepted": False, "reasons": ["name already used"]})
            continue
        try:
            result = verify_spec(proposal, next(iter(engines.engines.values())), bank=bank,
                                 corpus_sentences=() if precision_items else corpus_sentences)
            if result.ok and precision_items:
                counts = spec_precision(engines, candidate_tuple(proposal), precision_items)
                result.metrics["train_precision"] = counts
                if counts["answered"] < min_answered:
                    result.ok = False
                    result.reasons.append(f"answers only {counts['answered']} labelled questions (needs {min_answered})")
                elif counts["wrong"] > max_wrong_share * counts["answered"]:
                    result.ok = False
                    result.reasons.append(f"wrong on {counts['wrong']}/{counts['answered']} labelled questions")
        except Exception as error:  # a malformed proposal is a rejection, not a crash
            verdicts.append({"name": name, "accepted": False, "reasons": [f"verifier error: {error}"]})
            continue
        if result.ok:
            spec = RelationSpec(
                name=name, priority=int(proposal.get("priority", 50)),
                question_patterns=tuple(proposal["question_patterns"]),
                sentence_patterns=tuple(proposal["sentence_patterns"]),
                template=proposal["template"], verb_class=proposal.get("verb_class", ""),
                rationale=proposal.get("rationale", ""), origin="teacher",
                proposition=proposal.get("proposition", {}))
            change = memory.log_change("rule", f"round {round_no}: accept spec {name}",
                                       reference=f"teacher-round-{round_no}", accepted=True,
                                       metrics=result.metrics)
            evidence = {k: proposal.get(k) for k in ("support", "heldout", "contrast")}
            if precision_items:
                evidence["gate"] = "train_precision"
            memory.put_spec(spec, evidence=evidence, change_id=change)
            memory.connection.commit()
            engines.refresh()
        verdicts.append({"name": name, "accepted": result.ok, "reasons": result.reasons,
                         "metrics": result.metrics})
    return verdicts


def round_decision(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a round only if the dev wrong share did not rise and utility did not fall."""
    b, a = before["overall"], after["overall"]
    keep = (a["wrong_share_of_answered"] <= b["wrong_share_of_answered"] + 1e-9
            and a["utility"] >= b["utility"])
    return {"keep": keep, "dev_correct": [b["correct"], a["correct"]], "dev_wrong": [b["wrong"], a["wrong"]],
            "dev_utility": [b["utility"], a["utility"]],
            "wrong_share": [b["wrong_share_of_answered"], a["wrong_share_of_answered"]]}
