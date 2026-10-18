"""Learn an additive number-phrase pattern from grounded examples."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel


def train(model: CRMSModel, values: list[tuple[int, str]]) -> None:
    for value, word in values:
        for literal in (str(value), word):
            phrase = f"add {literal} to every value"
            result = model.teach(
                phrase, [([1, -2], [1 + value, -2 + value]),
                         ([4, 3], [4 + value, 3 + value])])
            if result.status != "learned":
                raise SystemExit(f"could not learn {phrase!r}: {result}")


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1, max_add=30)
    train(model, [(1, "one"), (2, "two"), (3, "three"),
                  (20, "twenty"), (21, "twenty one"), (22, "twenty two")])

    learned = model._grounded_number_words()
    if learned.get(("twenty", "three"), (None,))[0] != 23:
        raise SystemExit(f"additive phrase pattern did not generalize: {learned}")
    result = model.predict("add twenty three to every value", [4, -3])
    if result.status != "ok" or result.output != [27, 20]:
        raise SystemExit(f"composed numeric parameter did not transfer: {result}")
    hyphenated = model.predict("add twenty-three to every value", [4, -3])
    if hyphenated.status != "ok" or hyphenated.output != [27, 20]:
        raise SystemExit(f"hyphenated composition did not transfer: {hyphenated}")
    needed = {
        "add 20 to every value", "add twenty to every value",
        "add 21 to every value", "add twenty one to every value",
        "add 22 to every value", "add twenty two to every value",
        "add 3 to every value", "add three to every value",
    }
    if not needed.issubset(set(result.evidence_phrases or [])):
        raise SystemExit(f"composed number lost its teaching lineage: {result}")

    unknown = model.predict("add twenty four to every value", [4, -3])
    if (unknown.status not in {"need_examples", "need_more_examples"}
            or unknown.output is not None):
        raise SystemExit(f"unsupported phrase was guessed: {unknown}")

    # A composed meaning depends on both observed compound examples. Forgetting
    # one must invalidate the learned pattern and withdraw the held-out mapping.
    retracting = CRMSModel(max_composition_depth=1, max_workers=1, max_add=30)
    train(retracting, [(1, "one"), (2, "two"), (3, "three"),
                       (20, "twenty"), (21, "twenty one"), (22, "twenty two")])
    if not retracting.forget("add twenty two to every value"):
        raise SystemExit("could not forget a supporting composition example")
    if ("twenty", "three") in retracting._grounded_number_words():
        raise SystemExit("composed mapping survived loss of pattern support")
    after_forget = retracting.predict("add twenty three to every value", [4, -3])
    if (after_forget.status not in {"need_examples", "need_more_examples"}
            or after_forget.output is not None):
        raise SystemExit(f"forgotten composition remained applicable: {after_forget}")

    insufficient = CRMSModel(max_composition_depth=1, max_workers=1,
                             max_add=30)
    train(insufficient, [(1, "one"), (2, "two"), (3, "three"),
                         (20, "twenty"), (21, "twenty one")])
    if ("twenty", "three") in insufficient._grounded_number_words():
        raise SystemExit("one observed compound licensed an additive pattern")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "numbers.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1,
                             max_add=30)
        after_load = restored.predict("add twenty three to every value", [4, -3])
        if after_load.status != "ok" or after_load.output != [27, 20]:
            raise SystemExit(f"compositional number did not survive reload: {after_load}")

    # Exercise the user-facing language-learning path and persisted CLI memory.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        rules_path = root / "rules.json"
        cli = [sys.executable, str(Path(__file__).resolve().parents[1]
                                  / "crms_chat.py"),
               "--rules", str(rules_path), "--rule-depth", "1",
               "--rule-max-add", "30",
               "--knowledge", str(root / "knowledge.json"),
               "--index", str(root / "index.json"),
               "--dialogue-state", str(root / "dialogue.json"),
               "--rule-session", str(root / "session.json")]
        commands = []
        for value, word in [(1, "one"), (2, "two"), (3, "three"),
                            (20, "twenty"), (21, "twenty one"),
                            (22, "twenty two")]:
            for literal in (str(value), word):
                phrase = f"add {literal} to every value"
                commands.extend((
                    f"/teach-rule {phrase}|1,-2|{1 + value},{-2 + value}",
                    f"/teach-rule {phrase}|4,3|{4 + value},{3 + value}"))
        commands.extend(("/apply-rule add twenty-three to every value|4,-3",
                         "/quit"))
        process = subprocess.run(
            cli, input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "CRMS> [27, 20]" not in process.stdout:
            raise SystemExit(f"CLI did not apply composed phrase:\n{process.stdout}")

    print("compositional number-word diagnostic: PASS")
    print("two-example addition schema, held-out and hyphenated composition, provenance, abstention, forgetting, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
