"""Keep corpus task-intent labels representable without promoting candidates."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue_intent import (CRMSDialogueIntentModel,
                                  empty_dialogue_intent_memory,
                                  validate_dialogue_intent_memory)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    payload = empty_dialogue_intent_memory()
    examples = (
        ("request-action", "make-reservation", "book a table"),
        ("provide-information", "provide-constraint", "party of four"),
        ("question", "check-availability", "is a table available"),
        ("correction", "correct-prior-result", "no, that is wrong"),
        ("reject", "cancel-reservation", "cancel the reservation"),
    )
    for index, (act, intent, surface) in enumerate(examples):
        payload["learned_frames"].append({
            "frame_id": f"candidate-{index}",
            "dialogue_act": act,
            "task_intent": intent,
            "surface_patterns": [surface],
            "context_predicates": [],
            "predecessor_act": None,
            "source_citations": [f"taskmaster:conversation-{index}#turn=1"],
            "status": "candidate",
            "validation": None,
            "runtime_route": None,
        })

    validated = validate_dialogue_intent_memory(payload)
    model = CRMSDialogueIntentModel(validated)
    for _act, _intent, surface in examples:
        require(model.resolve(surface, context=set(), predecessor_act=None) is None,
                "an unvalidated task-intent candidate affected runtime decisions")

    print("corpus task-intent distinctions are representable in portable frames: PASS")
    print("candidate task-intent frames remain inert until validated: PASS")


if __name__ == "__main__":
    main()
