"""Learn multiword number phrases and reuse them in parameterized rules."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel


def teach_add(model: CRMSModel, phrase: str, amount: int) -> None:
    result = model.teach(
        phrase, [([1, -2], [1 + amount, -2 + amount])])
    if result.status != "learned":
        raise SystemExit(f"could not learn {phrase!r}: {result}")


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1,
                      max_add=30, max_rotation=25)
    teach_add(model, "add 21 to every value", 21)
    teach_add(model, "add twenty one to every value", 21)
    teach_add(model, "add 22 to every value", 22)
    teach_add(model, "add twenty two to every value", 22)

    rotation_examples = [
        ([1, 2, 3, 4], [4, 1, 2, 3]),
        ([1, 2, 3, 4, 5], [4, 5, 1, 2, 3]),
        ([1, 2, 3, 4, 5, 6, 7], [3, 4, 5, 6, 7, 1, 2]),
    ]
    for phrase in ("rotate left 23 places", "rotate left twenty three places"):
        result = model.teach(phrase, rotation_examples)
        if result.status != "learned":
            raise SystemExit(f"could not ground numeric phrase {phrase!r}: {result}")

    learned = model._grounded_number_words()
    if learned.get(("twenty", "three"), (None,))[0] != 23:
        raise SystemExit(f"multiword number phrase was not grounded: {learned}")

    for phrase in ("add twenty three to every value",
                   "add twenty-three to every value"):
        transferred = model.predict(phrase, [1, -2])
        if transferred.status != "ok" or transferred.output != [24, 21]:
            raise SystemExit(f"multiword parameter did not transfer: {transferred}")
    unknown = model.predict("add twenty four to every value", [1, -2])
    if (unknown.status not in {"need_examples", "need_more_examples"}
            or unknown.output is not None or not unknown.evidence_phrases):
        raise SystemExit(f"ungrounded multiword slot was not blocked: {unknown}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1,
                             max_add=30, max_rotation=25)
        after_load = restored.predict("add twenty three to every value", [1, -2])
        if after_load.status != "ok" or after_load.output != [24, 21]:
            raise SystemExit(f"numeric phrase transfer failed after reload: {after_load}")

    print("multiword numeric-slot diagnostic: PASS")
    print("example-grounded phrase value, cross-frame numeric transfer, unknown-slot abstention, persistence: PASS")


if __name__ == "__main__":
    main()
