"""Phase 13 D: the pattern tables ship in the release; install, verify, tamper, roll back, smoke test.

Builds the Phase 8 fixture release with a pattern database, copies it to a clean room, checks the
integrity gates (a changed pattern file or a missing policy is refused), swaps in an updated
database and rolls it back in one operation, shows the chat's gate reads the installed tables, and
runs ten fixed questions through the real chat CLI from the clean room."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import run_phase8_eval as p8  # noqa: E402
from crms_pattern_defaults import use_pattern_db  # noqa: E402
from crms_pattern_pack import (PATTERNS_FILE, build_pattern_db, rollback_patterns,  # noqa: E402
                               update_patterns, verify_pattern_db)
from crms_phase8_model import build_release, open_release  # noqa: E402


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(message)


QUESTIONS = [   # (question, must contain / "ABSTAIN")
    ("Who created Python?", "Guido van Rossum created Python."),
    ("Who created Linux?", "Linus Torvalds"),
    ("When was Linux created?", "1991"),
    ("Where is the Eiffel Tower?", "Paris"),
    ("What is 4 plus 5?", "9"),
    ("What is 17 + 25?", "42"),
    ("What is the capital of Xyzzyland?", "ABSTAIN"),
    ("Who founded Quuxcorp?", "ABSTAIN"),
    ("When was the Zorblat Treaty signed?", "ABSTAIN"),
    ("What did I just ask?", "When was the Zorblat Treaty signed?"),
]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-p13-pack-") as folder:
        root = Path(folder)
        db = root / "patterns.sqlite"
        manifest = build_pattern_db(db, version="1")
        require(not verify_pattern_db(db), verify_pattern_db(db))
        require(int(manifest["word_df_words"]) > 1000, manifest)

        broken = root / "broken.sqlite"
        shutil.copy2(db, broken)
        connection = sqlite3.connect(broken)
        connection.execute("DELETE FROM pat_gate_policy")
        connection.commit()
        connection.close()
        require(any("gate policy" in p for p in verify_pattern_db(broken)), "a missing policy must fail")
        (root / "not_a_db.sqlite").write_bytes(b"nope")
        require(verify_pattern_db(root / "not_a_db.sqlite"), "garbage must fail")

        # release with the pattern database
        fixture = json.loads((PROJECT / "corpus" / "phase8_eval" / "fixture.json").read_text())
        seed = root / "seed"
        seed.mkdir()
        model, _ = p8._build_seed(fixture, seed)
        registry = seed / "registry.sqlite"
        p8._build_registry(registry)
        release = root / "release"
        build_release(release, model_db=model, licences=p8._licence_rows(fixture),
                      dependencies=fixture["dependencies"], dependency_edges=fixture["edges"],
                      registry_db=registry, corrections=fixture["corrections"], replace=True,
                      patterns_db=db)
        opened = open_release(release)
        try:
            require(opened.patterns_path is not None and opened.verify()["valid"], opened.verify())
            roles = {f["role"] for f in opened.manifest["files"]}
            require("pattern-memory" in roles, roles)
        finally:
            opened.close()

        # clean room: a copy, the original hidden, a tampered pattern file refused
        clean = root / "clean_room"
        shutil.copytree(release, clean)
        original = release.with_name("release_hidden")
        release.rename(original)
        tampered = root / "tampered"
        shutil.copytree(clean, tampered)
        with open(tampered / PATTERNS_FILE, "r+b") as handle:
            handle.seek(2048)
            handle.write(b"\xff")
        try:
            open_release(tampered)
            raise SystemExit("a changed pattern file must be refused")
        except ValueError:
            pass

        # update and one-step rollback
        before = (clean / PATTERNS_FILE).read_bytes()
        newer = root / "patterns_v2.sqlite"
        build_pattern_db(newer, version="2")
        connection = sqlite3.connect(newer)
        connection.execute("UPDATE pat_gate_policy SET threshold=0.123 WHERE dimension='weighted_coverage'")
        connection.commit()
        connection.close()
        update_patterns(clean, newer)
        require((clean / PATTERNS_FILE).read_bytes() != before, "update did not change the file")
        require(open_release(clean).verify()["valid"], "updated release must verify")
        use_pattern_db(clean / PATTERNS_FILE)
        from crms_nl_gate import gate_policy
        require(gate_policy()["weighted_coverage"]["threshold"] == 0.123,
                "the gate must read the installed policy")
        rollback_patterns(clean)
        require((clean / PATTERNS_FILE).read_bytes() == before, "rollback did not restore the file")
        require(open_release(clean).verify()["valid"], "rolled-back release must verify")
        use_pattern_db(clean / PATTERNS_FILE)
        require(gate_policy()["weighted_coverage"]["threshold"] == 0.4, f"policy not restored: {gate_policy()['weighted_coverage']}")
        use_pattern_db(None)

        # first-run smoke test through the real chat, from the clean room
        work = root / "work"
        work.mkdir()
        turns = [q for q, _e in QUESTIONS]
        output = p8._run_chat(work, turns, model_db=clean / "model.sqlite")
        replies = output.split("CRMS> ")[1:]
        require(len(replies) >= len(QUESTIONS), f"{len(replies)} replies for {len(QUESTIONS)} questions")
        failures = []
        for (question, expect), reply in zip(QUESTIONS, replies):
            text = reply.split("you>")[0]
            if expect == "ABSTAIN":
                low = text.casefold()
                if not any(w in low for w in ("don't know", "do not know", "couldn't", "no grounded",
                                              "can't", "won't", "not enough", "no accepted")):
                    failures.append((question, "expected a refusal", text[:120]))
            elif expect not in text:
                failures.append((question, f"expected {expect!r}", text[:120]))
        require(not failures, failures)
    print("Phase 13 pattern release contract and smoke test passed")


if __name__ == "__main__":
    main()
