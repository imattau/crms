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
            "ORDER BY random() LIMIT 1500", (kind + "%",)).fetchall()
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
