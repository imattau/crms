"""Check deterministic evidence updates, abstention margins, and noise response."""
from __future__ import annotations

import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_ledger import Ledger, LedgerParams


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_ledger(margin: float = 0.30) -> Ledger:
    return Ledger(sqlite3.connect(":memory:"), LedgerParams(
        preference_margin=margin))


def noisy_trial(seed: int, margin: float, noise: float = 0.20,
                steps: int = 60) -> tuple[int, int, int]:
    rng = random.Random(seed)
    ledger = make_ledger(margin)
    ledger.register("fact", "C")
    ledger.register("fact", "D")
    for _ in range(60):
        ledger.record("fact", "C", "confirmed")
    prior_winner = "C"
    flips = stale_answers = abstentions = 0
    for index in range(steps):
        observed = "C" if rng.random() < noise else "D"
        rival = "D" if observed == "C" else "C"
        ledger.record("fact", observed, "confirmed", observation=index)
        ledger.record("fact", rival, "contradicted", observation=index)
        preference = ledger.prefer("fact", ["C", "D"])
        if preference.outcome == "ambiguous":
            abstentions += 1
            continue
        if preference.winner != prior_winner:
            flips += 1
            prior_winner = preference.winner or prior_winner
        if preference.winner != "D":
            stale_answers += 1
    return flips, stale_answers, abstentions


def main() -> None:
    ledger = make_ledger()
    ledger.register("fact", "auto")
    require(abs(ledger.weight("fact", "auto") - 0.20) < 1e-12,
            "auto-learned item did not get its configured initial weight")
    ledger.register("fact", "auto")
    require(abs(ledger.weight("fact", "auto") - 0.20) < 1e-12
            and len(ledger.events()) == 0,
            "repeated item registration was not idempotent")
    ledger.record("fact", "auto", "confirmed", answer="q1")
    require(abs(ledger.weight("fact", "auto") - 0.32) < 1e-12,
            "confirmation update did not match the configured hit rule")
    ledger.record("fact", "auto", "rejected", answer="q2")
    require(abs(ledger.weight("fact", "auto") - 0.208) < 1e-12,
            "rejection update did not match the configured miss rule")
    before = ledger.weight("fact", "auto")
    for _ in range(1000):
        ledger.prefer("fact", ["auto"])
    require(ledger.weight("fact", "auto") == before,
            "retrieval/preference changed the item weight")

    ledger.register("fact", "teacher", protected=True)
    for _ in range(20):
        ledger.record("fact", "teacher", "rejected")
    require(ledger.weight("fact", "teacher") == 1.0,
            "rejected user feedback changed a protected item")

    for item_id, dependency in (("unknown-deps", None),
                                ("has-deps", True),
                                ("no-deps", False)):
        ledger.register("rule", item_id)
        for _ in range(6):
            ledger.record("rule", item_id, "rejected",
                          has_dependents=dependency)
    rows = {row[0]: row[1] for row in ledger.connection.execute(
        "SELECT item_id,status FROM item_ledger WHERE item_kind='rule'")}
    require(rows == {"unknown-deps": "active", "has-deps": "active",
                     "no-deps": "dormant"},
            f"dormancy ignored dependency uncertainty: {rows}")
    require(ledger.stale("rule", max_weight=0.02, min_misses=6)
            == ["has-deps", "unknown-deps"],
            "stale listing included protected/dormant items or missed candidates")
    require(ledger.prefer("rule", ["no-deps", "has-deps"]).winner == "has-deps",
            "dormant item remained eligible to win a preference")
    ledger.record("rule", "no-deps", "held_out_pass")
    require(ledger.connection.execute(
                "SELECT status FROM item_ledger WHERE item_kind='rule' "
                "AND item_id='no-deps'").fetchone()[0] == "active",
            "held-out revalidation did not restore a dormant item")

    conflict = make_ledger()
    conflict.register("fact", "strong", weight=0.70)
    conflict.register("fact", "weak", weight=0.20)
    require(conflict.prefer("fact", ["weak", "strong"]).winner == "strong",
            "margin policy did not prefer a sufficiently stronger item")
    close = make_ledger()
    close.register("fact", "left", weight=0.50)
    close.register("fact", "right", weight=0.25)
    require(close.prefer("fact", ["left", "right"]).outcome == "ambiguous",
            "close competing items did not abstain")

    sequence = [("corroborated", "src-b"), ("confirmed", "answer-1"),
                ("rejected", "answer-2")]
    runs = []
    for _ in range(2):
        replay = make_ledger()
        replay.register("frame", "f1")
        for event, source in sequence:
            replay.record("frame", "f1", event, source=source)
        runs.append((replay.weight("frame", "f1"), replay.events()))
    require(runs[0] == runs[1], "same event sequence was not deterministic")

    shared = sqlite3.connect(":memory:")
    shared.execute("CREATE TABLE caller_state (value TEXT)")
    shared.commit()
    shared.execute("BEGIN")
    shared.execute("INSERT INTO caller_state VALUES ('pending')")
    shared_ledger = Ledger(shared)
    shared_ledger.register("fact", "transactional")
    require(shared.in_transaction,
            "ledger committed the caller's surrounding transaction")
    shared.rollback()
    require(shared.execute("SELECT COUNT(*) FROM caller_state").fetchone()[0] == 0
            and shared.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='item_ledger'").fetchone()[0] == 0,
            "ledger savepoints did not respect caller rollback")

    revision = make_ledger(margin=0.30)
    revision.register("fact", "C")
    revision.register("fact", "D")
    for _ in range(60):
        revision.record("fact", "C", "confirmed")
    require(revision.prefer("fact", ["C", "D"]).winner == "C",
            "entrenched item was not preferred before the truth change")
    changes = 0
    prior = "C"
    for step in range(1, 6):
        revision.record("fact", "D", "confirmed", phase="revision", step=step)
        revision.record("fact", "C", "contradicted", phase="revision", step=step)
        current = revision.prefer("fact", ["C", "D"])
        if current.outcome == "prefer":
            if current.winner != prior:
                changes += 1
            prior = current.winner or prior
    require(changes == 1,
            "truth change did not produce exactly one preference switch within five observations")
    require(revision.prefer("fact", ["C", "D"]).winner == "D",
            "corrected item did not remain preferred after the flip")
    final_c = revision.weight("fact", "C")
    final_d = revision.weight("fact", "D")
    require(abs(final_c - final_d) > 0.10 * max(final_c, final_d),
            "near-tied residual conflict did not clear within five observations")

    trials = 200
    margin_runs = [noisy_trial(seed, 0.30) for seed in range(trials)]
    zero_runs = [noisy_trial(seed, 0.00) for seed in range(trials)]
    mean = lambda rows, index: sum(row[index] for row in rows) / len(rows)
    margin_flips = mean(margin_runs, 0)
    margin_stale = mean(margin_runs, 1)
    zero_stale = mean(zero_runs, 1)
    abstentions = mean(margin_runs, 2)
    require(margin_flips <= 2.5,
            f"20% noise caused too many margin-policy flips: {margin_flips:.2f}")
    require(margin_stale < zero_stale,
            f"margin did not reduce stale answers: {margin_stale:.2f} vs {zero_stale:.2f}")

    print("hit/miss equations, protected items, and idempotent retrieval: PASS")
    print("dependency-safe dormancy, stale listing, and deterministic replay: PASS")
    print("preference margin abstains on close conflicts: PASS")
    print("single truth revision within five observations: PASS")
    print(f"20% noise over {trials} seeds: flips={margin_flips:.2f}, "
          f"stale={margin_stale:.2f} vs margin-0 {zero_stale:.2f}, "
          f"abstentions={abstentions:.2f}: PASS")


if __name__ == "__main__":
    main()
