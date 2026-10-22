"""Independent oracle for relation questions (Phase 11).

Infobox fields give gold answers for questions about the same page, so large
labelled samples need no hand authoring and do not reuse the sentence patterns
under test. Gold can be wrong (an infobox may disagree with the text), so
results are reported with that caveat and per relation.
"""
from __future__ import annotations

import collections
import random
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

RELATIONS: tuple[tuple[str, str, str, str | None], ...] = (
    ("Infobox film", "director", "Who directed {T}?", None),
    ("Infobox film", "producer", "Who produced {T}?", None),
    ("Infobox book", "author", "Who wrote {T}?", None),
    ("Infobox album", "artist", "Who made {T}?", None),
    ("Infobox company", "founder", "Who founded {T}?", None),
    ("Infobox company", "foundation", "When was {T} founded?", "year"),
    ("Infobox video game", "developer", "Who developed {T}?", None),
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower().replace(",", "")).strip()


def matches(gold: str, answer: str) -> bool:
    a = _norm(answer)
    g = _norm(gold)
    if not g:
        return False
    # an infobox may give a full name where the text gives only a surname
    return g in a or (len(g.split()) > 1 and g.split()[-1] in a.split())


def sample_questions(index_path: str | Path, *, per_relation: int = 150, seed: int = 0,
                     exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    skip = set(exclude)
    connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    items: list[dict[str, Any]] = []
    for kind, field, template, mode in RELATIONS:
        rows = connection.execute(
            "SELECT title, substr(body,1,2500) FROM source_documents WHERE body LIKE ? "
            "ORDER BY (rowid * 2654435761 + ?) % 4294967296 LIMIT 1500",
            (kind + "%", seed)).fetchall()      # deterministic for a given seed
        rng.shuffle(rows)
        taken = 0
        for title, body in rows:
            question = template.format(T=title)
            if question in skip or "(" in title or len(title.split()) > 6:
                continue
            m = re.search(r"^" + field.replace("_", "[_ ]") + r"\s*=\s*(.+)$", body, re.M | re.I)
            if not m:
                continue
            value = m.group(1).strip()
            if re.search(r"[\[\]{}<>|;]|\n", value) or not value or len(value) > 50:
                continue
            if re.search(r"plainlist|unbulleted|flatlist|hlist", value, re.I):
                continue   # template residue, not an answer
            if mode == "year":
                y = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", value)
                gold = y.group(1) if y else None
            else:
                gold = value
            if not gold or len(gold) < 2:
                continue
            items.append({"relation": field, "question": question, "gold": gold})
            taken += 1
            if taken >= per_relation:
                break
    connection.close()
    return items


def evaluate(engine: Any, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = collections.Counter()
    per: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    wrong_examples: list[dict[str, str]] = []
    for item in items:
        answer = engine.ask(item["question"])
        if answer is None:
            status = "no_candidate"
        elif matches(item["gold"], answer.answer):
            status = "correct"
        else:
            status = "wrong"
            if len(wrong_examples) < 25:
                wrong_examples.append({"question": item["question"], "gold": item["gold"],
                                       "answer": answer.answer})
        total[status] += 1
        per[item["relation"]][status] += 1
    n = len(items)
    answered = total["correct"] + total["wrong"]
    return {"questions": n, **dict(total),
            "coverage": round(answered / n, 4) if n else 0.0,
            "wrong_rate_of_answered": round(total["wrong"] / answered, 4) if answered else 0.0,
            "utility": total["correct"] - 3 * total["wrong"],
            "per_relation": {k: dict(v) for k, v in sorted(per.items())},
            "wrong_examples": wrong_examples}


_ABSTAIN = re.compile(
    r"won't guess|couldn't verify|does not support|can't safely|I don't have|I don't know|"
    r"do not have|I couldn't|couldn't find|no retrieved sentence|I can't|not enough", re.I)


def chat_answer(chat: Path, index: Path, question: str, *, timeout: int = 180,
                keep_source: bool = False) -> str:
    """Ask one question in a fresh, isolated chat session; return the answer text."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(prefix="crms-baseline-") as folder:
        command = [sys.executable, str(chat), "--index", str(index)]
        for name in ("dialogue-state", "candidate-session", "rule-session", "math-session"):
            command += [f"--{name}", f"{folder}/{name}.json"]
        command += ["--feedback-db", f"{folder}/feedback.sqlite3"]
        try:
            out = subprocess.run(command, input=question + "\n/quit\n", text=True,
                                 capture_output=True, timeout=timeout, cwd=folder).stdout
        except (subprocess.TimeoutExpired, OSError):
            return ""
    parts = out.split("CRMS> ")
    if len(parts) < 2:
        return ""
    answer = re.sub(r"\s*you>\s*$", "", parts[1].strip())
    if not keep_source:
        answer = re.sub(r"\[Source:[^\]]*\]", "", answer)
    return answer.split("CRMS state saved")[0].strip()


def baseline_chat(chat: Path, index: Path, items: Sequence[dict[str, Any]], *,
                  workers: int = 8) -> list[str]:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(lambda it: chat_answer(chat, index, it["question"]), items))


def grade(item: dict[str, Any], answer: str | None) -> str:
    """correct / wrong / abstain for one answer to one oracle question."""
    if not answer or _ABSTAIN.search(answer):
        return "abstain"
    return "correct" if matches(item["gold"], answer) else "wrong"


def compare(items: Sequence[dict[str, Any]], relation_answers: Sequence[str | None],
            baseline_answers: Sequence[str]) -> dict[str, Any]:
    """Quote baseline vs relation layer alone vs relation-first with baseline fallback."""
    systems = {"baseline": collections.Counter(), "relation_only": collections.Counter(),
               "combined": collections.Counter()}
    per: dict[str, dict[str, collections.Counter]] = collections.defaultdict(
        lambda: {k: collections.Counter() for k in systems})
    changes = {"gained": 0, "lost": 0, "wrong_to_correct": 0, "correct_to_wrong": 0}
    examples: list[dict[str, str]] = []
    for item, rel, base in zip(items, relation_answers, baseline_answers):
        b = grade(item, base)
        r = grade(item, rel) if rel else "abstain"
        c = grade(item, rel) if rel else b
        for name, status in (("baseline", b), ("relation_only", r), ("combined", c)):
            systems[name][status] += 1
            per[item["relation"]][name][status] += 1
        if b != "correct" and c == "correct":
            changes["gained"] += 1
        if b == "correct" and c != "correct":
            changes["lost"] += 1
            if len(examples) < 20:
                examples.append({"question": item["question"], "gold": item["gold"],
                                 "baseline": (base or "")[:120], "combined": (rel or "")[:120]})
        if b == "wrong" and c == "correct":
            changes["wrong_to_correct"] += 1
        if b == "correct" and c == "wrong":
            changes["correct_to_wrong"] += 1
    def summary(counter):
        n = sum(counter.values())
        answered = counter["correct"] + counter["wrong"]
        return {**dict(counter), "questions": n,
                "wrong_rate_of_answered": round(counter["wrong"] / answered, 4) if answered else 0.0,
                "utility": counter["correct"] - 3 * counter["wrong"]}
    return {"systems": {k: summary(v) for k, v in systems.items()},
            "per_relation": {rel: {k: dict(v) for k, v in d.items()} for rel, d in sorted(per.items())},
            "changes_vs_baseline": changes, "lost_examples": examples}
