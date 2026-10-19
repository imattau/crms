"""Deterministic conversation acts that stay separate from evidence retrieval."""

from __future__ import annotations

import re
from typing import Any

from crms_dialogue import CRMSDialogue, DialogueTurn


_ACTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greeting", re.compile(
        r"^(?:hi(?:\s+there)?|hello(?:\s+there)?|hey(?:\s+there)?|"
        r"good\s+(?:morning|afternoon|evening)|how\s+are\s+you)[?.! ]*$",
        re.IGNORECASE)),
    ("farewell", re.compile(
        r"^(?:goodbye|bye|see\s+you|take\s+care)[?.! ]*$", re.IGNORECASE)),
    ("thanks", re.compile(r"^(?:thanks|thank\s+you|thx)[.! ]*$", re.IGNORECASE)),
    ("acknowledgement", re.compile(
        r"^(?:ok|okay|got\s+it|understood)[.! ]*$", re.IGNORECASE)),
    ("elaboration", re.compile(
        r"^(?:tell\s+me\s+more|go\s+on|anything\s+else)[?.! ]*$",
        re.IGNORECASE)),
    ("help", re.compile(
        r"^(?:help|what\s+can\s+you\s+do|how\s+do\s+i\s+use\s+this)"
        r"[?!. ]*$", re.IGNORECASE)),
    ("unclassified", re.compile(
        r"^(?:h+m+|u+h+|u+m+|e+r+m+|\.\.\.|\?+)[.!? ]*$",
        re.IGNORECASE)),
)
_MIXED_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey)(?:\s+there)?[,]\s*(?P<question>\S.+)$",
    re.IGNORECASE)


def classify_act(text: str) -> str | None:
    """Classify only anchored, content-free seed acts; mixed turns pass through."""
    normalized = text.strip()
    for act, pattern in _ACTS:
        if pattern.fullmatch(normalized):
            return act
    return None


def is_farewell(text: str) -> bool:
    return classify_act(text) == "farewell"


def respond(dialogue: CRMSDialogue, text: str, *,
            research_index: Any | None = None,
            pending_claims: int = 0) -> DialogueTurn:
    """Handle simple dialogue acts, delegating every content turn unchanged."""
    mixed_greeting = _MIXED_GREETING_RE.fullmatch(text.strip())
    if mixed_greeting is not None:
        content = mixed_greeting.group("question").strip()
        turn = dialogue.turn(content, research_index=research_index)
        if turn.text:
            turn.text = "Hello. " + turn.text
        return turn
    act = classify_act(text)
    if act is None:
        return dialogue.turn(text, research_index=research_index)

    if act == "greeting":
        fact_count = len(dialogue.knowledge._facts)
        source_count = (research_index.document_count()
                        if research_index is not None else 0)
        counts = f"{fact_count:,} accepted facts and {source_count:,} source documents"
        if pending_claims:
            counts += f"; {pending_claims:,} claims awaiting review"
        reply = (f"Hello. CRMS has {counts} loaded. Ask about an entity or source; "
                 "ask ‘why?’ to see the supporting evidence.")
        return DialogueTurn("social", text, text, text=reply)
    if act == "farewell":
        return DialogueTurn("farewell", text, text, text="Goodbye.")
    if act == "thanks":
        return DialogueTurn("social", text, text, text="You're welcome.")
    if act == "acknowledgement":
        return DialogueTurn("social", text, text,
                            text="Okay. What would you like to ask or do next?")
    if act == "elaboration":
        focus = dialogue.last_entity
        if focus:
            reply = (f"I can look for more grounded information about {focus}. "
                     "Ask a specific question about it or name another topic.")
        else:
            reply = "Which entity or source should I look at in more detail?"
        return DialogueTurn("clarify", text, text, text=reply)
    if act == "help":
        return DialogueTurn(
            "help", text, text,
            text=("Ask about indexed sources or accepted facts. Add sources with "
                  "/source or /source-dir; ask ‘why?’ for evidence. You can also "
                  "teach cited facts and ask CRMS to write a short fictional story."))
    return DialogueTurn(
        "unclassified", text, text,
        text=("I didn't recognize a question or action. Ask about a source or fact, "
              "request a short fictional story, or type /help."))
