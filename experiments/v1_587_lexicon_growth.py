"""Phase 12: verb induction proposes regular verbs the corpus attests and ignores the rest."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_lexicon_growth import grow, paradigm  # noqa: E402

TEXT = (["The bridge was designed by Ann Lee. Ann Lee designs bridges. They design many bridges."] * 4
        + ["The film was directed by Sam Pike. Sam Pike directs films. They direct films."] * 3
        + ["The award was named by the board.", "The cat is blue by nature."] * 2)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(message)


def main() -> None:
    require(paradigm("design") == ("design", "designs", "designed", "designed"), paradigm("design"))
    require(paradigm("study")[2] == "studied" and paradigm("make")[2] == "maked", "regular rule only")
    found = {c["lemma"]: c for c in grow(TEXT, {"build": ["build", "builds", "built", "built"]})}
    require("design" in found and found["design"]["forms"][2] == "designed", found)
    require("direct" in found, found)
    require("build" not in found, "known verbs must not be re-proposed")
    require("blue" not in found and "nature" not in found, "non-verbs proposed")
    print("Phase 12 lexicon growth passed")


if __name__ == "__main__":
    main()
