"""Short-term, evidence-bound dialogue state for CRMS."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any

from crms_knowledge import (
    CRMSKnowledgeBase, CounterfactualResult, QuestionResult, ResearchResult,
    WritingResult,
)
from crms_dialogue_intent import CRMSDialogueIntentModel
from crms_text import tokens as normalized_tokens, word_matches


_REFERENTIAL_PRONOUNS = {
    "he", "she", "they", "it", "him", "her", "them", "this", "that",
}
_THAT_COMPLEMENT_VERBS = {
    "accept", "add", "admit", "agree", "argue", "assume", "believe",
    "claim", "clarify", "conclude", "confirm", "consider", "decide",
    "demonstrate", "discover", "estimate", "expect", "explain", "find",
    "forget", "guess", "hear", "hope", "imagine", "indicate", "insist",
    "know", "learn", "mean", "notice", "predict", "prove", "realize",
    "remember", "report", "say", "see", "show", "state", "suggest",
    "suppose", "tell", "think", "understand", "warn", "write",
}
class _WordScanner:
    """Regex-like interface backed by the shared Unicode token scanner."""

    @staticmethod
    def findall(text: str) -> list[str]:
        return list(normalized_tokens(text))

    @staticmethod
    def finditer(text: str):
        return iter(word_matches(text))


_WORD_RE = _WordScanner()
_CORRECTION_RE = re.compile(
    r"^(?:(?:no|actually)[, ]+)*(?:i meant)\s+(.+?)[.!?]*$",
    flags=re.IGNORECASE)
_BARE_YES_NO_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|certainly|absolutely|ok|okay|got it|"
    r"understood|no|nope|nah|not really)"
    r"(?:[, ]+(?:please|thanks|thank you))?[.!? ]*$",
    flags=re.IGNORECASE)
_FOLLOWUP_ENTITY_RE = re.compile(
    r"^(?:and\s+)?what about\s+(.+?)[?!.]*$|^and\s+(.+?)[?!.]*$",
    flags=re.IGNORECASE)
_EXPLANATION_FOLLOWUP_RE = re.compile(
    r"^(?:why(?: is that)?|how do you know(?: that)?|what supports that)"
    r"[?!. ]*$", flags=re.IGNORECASE)
_POSSESSIVE_PROPERTY_FOLLOWUP_RE = re.compile(
    r"\s*(?P<wh>what|where|who|which|how)"
    r"(?P<aux>\s+(?:is|was|are|were)|['’]s)\s+"
    r"(?:its|their|his|her)\s+(?P<property>[^?!.]+?)\s*[?!.]*\s*",
    flags=re.IGNORECASE)
_OUT_OF_SCOPE_SMALLTALK_RE = re.compile(
    r"^(?:(?:hi|hello|hey)(?:\s*,?\s*how\s+are\s+you)?|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"how\s+are\s+you|tell\s+me\s+a\s+joke)[?.! ]*$",
    flags=re.IGNORECASE)
_THANKS_RE = re.compile(r"^(?:thanks|thank you|thx)[.! ]*$", re.IGNORECASE)
_HELP_RE = re.compile(r"^(?:help|what can you do|how do i use this)[?!. ]*$", re.IGNORECASE)
_AUXILIARY_CONTRACTION_RE = re.compile(
    r"\b(who|what|where|when|why|how|he|she|it|they|we|you|i)['’](s|re|ve|ll|d|m)\b",
    flags=re.IGNORECASE)
_NEGATIVE_CONTRACTION_RE = re.compile(
    r"\b(can't|won't|shan't|ain't|don't|doesn't|didn't|isn't|aren't|"
    r"wasn't|weren't|haven't|hasn't|hadn't|couldn't|wouldn't|shouldn't|"
    r"mustn't|mightn't|needn't)\b", flags=re.IGNORECASE)
_NEGATIVE_CONTRACTION_READINGS = {
    "can't": ("cannot",),
    "won't": ("will not",),
    "shan't": ("shall not",),
    "ain't": ("am not", "is not", "are not"),
    "don't": ("do not",),
    "doesn't": ("does not",),
    "didn't": ("did not",),
    "isn't": ("is not",),
    "aren't": ("are not",),
    "wasn't": ("was not",),
    "weren't": ("were not",),
    "haven't": ("have not",),
    "hasn't": ("has not",),
    "hadn't": ("had not",),
    "couldn't": ("could not",),
    "wouldn't": ("would not",),
    "shouldn't": ("should not",),
    "mustn't": ("must not",),
    "mightn't": ("might not",),
    "needn't": ("need not",),
}


@dataclass
class UserIntentHypothesis:
    """Inspectable intent decision with the rule or model basis recorded."""

    dialogue_act: str
    task_intent: str | None
    decision: str
    matched_frame: str | None = None
    context_predicates: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    selected_value: str | None = None
    basis: str = "hand_checked_runtime_rule"
    evidence_refs: tuple[str, ...] = ()
    runtime_route: str | None = None


_HISTORY_LIMIT = 12
_HISTORY_FIELD_LIMIT = 200
_HISTORY_QUESTION_LIMIT = 500
_INTENT_TRACE_LIMIT = 12
_INTENT_TASKS = {
    "seek-information", "provide-information", "continue-current-task",
    "resolve-ambiguity", "correct-result", "social-contact",
    "end-interaction", "other-task",
}
_SHOWN_LIMIT = 500
_ELABORATION_BATCH = 3
_OVERVIEW_BATCH = 5
_BINDING_OPTION_LIMIT = 6
_HISTORY_KEYS = {"act", "utterance", "status"}


def _shown_key(fact: Any) -> str:
    parts = [fact.subject, fact.relation, fact.object,
             *(f"{name}={value}" for name, value in fact.qualifiers)]
    return " | ".join(" ".join(_WORD_RE.findall(part)).casefold()
                      for part in parts)


def _source_label(sources: Any) -> str:
    names = [str(source).partition("#sha256=")[0] for source in sources]
    if not names:
        return "no source"
    return "source: " + ", ".join(names[:2]) + (
        f" +{len(names) - 2}" if len(names) > 2 else "")


@dataclass
class DialogueTurn:
    status: str
    question: str
    resolved_question: str
    response: QuestionResult | None = None
    research: ResearchResult | None = None
    text: str = ""
    writing: WritingResult | None = None
    counterfactual: CounterfactualResult | None = None
    grouped_results: list[dict[str, Any]] | None = None
    intent_hypothesis: UserIntentHypothesis | None = None
    # A chat command the conversation layer asks the terminal to run next,
    # always taken from a fixed allowlist, never from user text.
    action: str | None = None
    # True when this turn added a fact, so the terminal saves the knowledge.
    learned: bool = False


class CRMSDialogue:
    """Route fact questions while retaining recent grounded entity context.

    This handles only explicitly listed personal/demonstrative pronouns and
    a bounded distributive form over two entities. It does not infer gender or
    long-range discourse structure; unresolved references trigger abstention.
    """

    def __init__(self, knowledge: CRMSKnowledgeBase, *,
                 intent_model: CRMSDialogueIntentModel | None = None) -> None:
        self.knowledge = knowledge
        self.intent_model = intent_model or CRMSDialogueIntentModel()
        self.last_entity: str | None = None
        self.subject_entity: str | None = None
        self.object_entity: str | None = None
        self.pending_question: str | None = None
        self.pending_result: QuestionResult | None = None
        self.last_question: str | None = None
        self.last_selected_answer: str | None = None
        self.last_intent_hypothesis: UserIntentHypothesis | None = None
        self.last_writing_subject: str | None = None
        self.last_writing_request: str | None = None
        self.last_timeline_subject: str | None = None
        self.last_timeline_order_by: str | None = None
        # Names extracted from the most recently quoted source passage are
        # discourse candidates only; they never become facts or answer evidence.
        self.source_mentions: list[dict[str, str]] = []
        # Conversation memory that outlives a refused turn. ``clear`` drops
        # referents so a stale pronoun cannot bind; it leaves these alone, and
        # only ``reset_history`` (the explicit /reset) wipes them.
        self.history: list[dict[str, str]] = []
        # A bounded record of licensed turn-level intent decisions. This is
        # session context, not shared knowledge or a user profile.
        self.intent_trace: list[dict[str, Any]] = []
        self.active_task_intent: str | None = None
        self.last_answered: dict[str, str] | None = None
        self.shown: list[str] = []
        # A pronoun that could mean several entities leaves its candidates
        # here so the next turn can pick one by number or name. Transient:
        # it is not saved, and any other turn discards it.
        self.pending_binding: dict[str, Any] | None = None
        self._pronoun_options: list[tuple[str, str]] = []
        # Next steps CRMS has offered, each answerable by a bare yes or no for a
        # short time. Transient: not saved, and ``clear`` leaves them alone.
        self.offers: list[dict[str, Any]] = []
        # A short, typed follow-up question asked by the conversation layer.
        # The slot is explicit so the next user turn can be interpreted in
        # context without treating it as a new factual question.
        self.pending_dialogue_slot: str | None = None

    def record_turn(self, utterance: str, act: str,
                    turn: "DialogueTurn",
                    intent_hypothesis: Any | None = None) -> None:
        """Append the turn and licensed intent evidence to bounded session state."""
        self.history.append({
            "act": act[:_HISTORY_FIELD_LIMIT],
            "utterance": utterance.strip()[:_HISTORY_FIELD_LIMIT],
            "status": str(turn.status)[:_HISTORY_FIELD_LIMIT],
        })
        del self.history[:-_HISTORY_LIMIT]
        if intent_hypothesis is not None:
            trace_entry = {
                "dialogue_act": str(intent_hypothesis.dialogue_act)[:80],
                "task_intent": intent_hypothesis.task_intent,
                "decision": str(intent_hypothesis.decision)[:40],
                "matched_frame": intent_hypothesis.matched_frame,
                "context_predicates": list(intent_hypothesis.context_predicates)[:20],
                "selected_value": intent_hypothesis.selected_value,
                "basis": str(intent_hypothesis.basis)[:80],
                "evidence_refs": list(intent_hypothesis.evidence_refs)[:100],
            }
            self.intent_trace.append(trace_entry)
            del self.intent_trace[:-_INTENT_TRACE_LIMIT]
            task_intent = intent_hypothesis.task_intent
            if intent_hypothesis.decision == "selected":
                if task_intent == "end-interaction":
                    self.active_task_intent = None
                elif task_intent in {
                        "seek-information", "provide-information", "other-task"}:
                    self.active_task_intent = task_intent
        response = turn.response
        if (turn.status == "answered" and response is not None
                and response.status == "answered" and turn.resolved_question):
            answer = response.answer or (
                "yes" if response.truth is True else
                "no" if response.truth is False else "")
            self.last_answered = {
                "question": turn.resolved_question[:_HISTORY_QUESTION_LIMIT],
                "answer": answer[:_HISTORY_QUESTION_LIMIT],
            }

    def intent_context(self) -> tuple[set[str], str | None]:
        """Expose bounded, observable predicates to the intent-frame matcher."""
        open_task = bool(self.pending_result or self.pending_binding
                         or self.pending_dialogue_slot or self.offers)
        context = set()
        if not self.history:
            context.add("conversation_opening")
        if self.last_entity or self.source_mentions or self.last_answered:
            context.add("current_topic_available")
        if self.last_answered:
            context.add("previous_grounded_answer")
        if self.active_task_intent is not None:
            context.add("task_in_progress")
        if self.last_answered or self.last_question:
            context.add("correction_target_available")
        if self.pending_result is not None:
            context.update({"pending_candidate_choice", "awaiting_user_detail",
                            "task_in_progress"})
        if self.pending_dialogue_slot is not None:
            context.update({"open_dialogue_slot", "awaiting_user_detail",
                            "task_in_progress"})
        if self.pending_binding is not None:
            context.update({"awaiting_user_detail", "task_in_progress"})
        if any(item.get("kind") == "confirm_statement" for item in self.offers):
            context.update({"awaiting_confirmation", "task_in_progress"})
        elif self.offers:
            context.add("task_in_progress")
        if not open_task and self.last_answered:
            context.add("task_complete")
        predecessor = None
        if self.history:
            predecessor = {
                "answered": "answer", "ambiguous": "clarification-request",
                "clarify": "clarification-request", "learned": "action-result",
                "farewell": "close", "help": "other", "social": "other",
            }.get(self.history[-1].get("status"), "uncertain")
        return context, predecessor

    def reset_history(self) -> None:
        self.history = []
        self.intent_trace = []
        self.active_task_intent = None
        self.last_intent_hypothesis = None
        self.last_answered = None
        self.shown = []
        self.offers = []
        self.pending_dialogue_slot = None

    def focus_entities(self) -> list[str]:
        """Entities the conversation is currently about, most recent answer first."""
        return list(dict.fromkeys(
            entity for entity in (
                self.last_entity, self.subject_entity, self.object_entity)
            if entity))

    def _facts_about(self, entities: list[str]) -> list[Any]:
        keys = {tuple(token.casefold() for token in _WORD_RE.findall(entity))
                for entity in entities}
        keys.discard(())
        store = self.knowledge._facts
        found: dict[tuple[Any, ...], Any] = {}
        if hasattr(store, "lookup_subject") and hasattr(store, "lookup_object"):
            candidates = (fact for key in sorted(keys)
                          for fact in (*store.lookup_subject(key),
                                       *store.lookup_object(key)))
        else:
            candidates = (fact for fact in store.values())
        for fact in candidates:
            subject = tuple(token.casefold() for token in
                            _WORD_RE.findall(fact.subject))
            obj = tuple(token.casefold() for token in _WORD_RE.findall(fact.object))
            if subject in keys or obj in keys:
                found[(subject, tuple(token.casefold() for token in
                                      _WORD_RE.findall(fact.relation)), obj,
                       tuple(fact.qualifiers))] = fact
        return [found[key] for key in sorted(found)]

    def elaborate(self) -> "DialogueTurn | None":
        """Show the next accepted facts about the focus that were not shown yet.

        Replies are cited fact lines, never retrieval; ``None`` means there is
        no current focus to elaborate on.
        """
        entities = self.focus_entities()
        if not entities:
            return None
        rows = self._facts_about(entities)
        topic = entities[0]
        if not rows:
            text = (f"I have no accepted facts about {topic} yet. Ask a "
                    "specific question about it, or add a source.")
            return DialogueTurn("elaborated", "tell me more", "tell me more",
                                text=text)
        keyed = [(_shown_key(fact), fact) for fact in rows]
        unshown = [(key, fact) for key, fact in keyed if key not in self.shown]
        if not unshown:
            return DialogueTurn(
                "elaborated", "tell me more", "tell me more",
                text=f"That is everything I have accepted about {topic}.")
        batch = unshown[:_ELABORATION_BATCH]
        lines = [("More about " if self.shown else "About ") + f"{topic}:"]
        for key, fact in batch:
            lines.append(f"- {fact.subject} — {fact.relation} → {fact.object} "
                         f"[{_source_label(fact.sources)}]")
            self.shown.append(key)
        del self.shown[:-_SHOWN_LIMIT]
        remaining = len(unshown) - len(batch)
        lines.append(f"{remaining} more available; say ‘tell me more’ again."
                     if remaining else
                     f"That is everything I have accepted about {topic}.")
        return DialogueTurn("elaborated", "tell me more", "tell me more",
                            text="\n".join(lines))

    def clear(self) -> None:
        self.last_entity = None
        self.subject_entity = None
        self.object_entity = None
        self.last_question = None
        self.last_selected_answer = None
        self.last_intent_hypothesis = None
        self.last_writing_subject = None
        self.last_writing_request = None
        self.last_timeline_subject = None
        self.last_timeline_order_by = None
        self.source_mentions = []
        self.pending_dialogue_slot = None
        self._clear_pending()

    def _clear_pending(self) -> None:
        self.pending_question = None
        self.pending_result = None
        self.pending_binding = None

    def select_binding(self, message: str) -> dict[str, str] | None:
        """Return the open pronoun-binding option the message picks, if any."""
        if self.pending_binding is None:
            return None
        options = self.pending_binding["options"]
        words = [word.casefold() for word in _WORD_RE.findall(message)]
        words = [word for word in words
                 if word not in {"the", "a", "an", "one", "option", "answer",
                                 "it", "is", "that", "i", "mean", "meant"}]
        if len(words) > 1 and words[0] == "no":
            words = words[1:]
        ordinals = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2,
                    "3rd": 2, "fourth": 3, "4th": 3, "last": len(options) - 1}
        if len(words) == 1 and words[0].isdigit():
            index = int(words[0]) - 1
            return options[index] if 0 <= index < len(options) else None
        if len(words) == 1 and words[0] in ordinals:
            return options[ordinals[words[0]]]
        for option in options:
            name = [word.casefold() for word in _WORD_RE.findall(option["entity"])]
            name = name[1:] if name[:1] in (["the"], ["a"], ["an"]) else name
            if words and words == name:
                return option
        return None

    def overview(self, phrase: str) -> "DialogueTurn | None":
        """Summarise the accepted facts about one named entity, five at a time.

        Returns ``None`` unless the phrase names a single entity that has
        accepted facts, so every other case keeps its existing handling.
        """
        entity = self._canonical_entity(phrase.strip())
        if entity is None:
            return None
        rows = self._facts_about([entity])
        if not rows:
            return None
        keyed = [(_shown_key(fact), fact) for fact in rows]
        self.shown = [key for key in self.shown
                      if key not in {item for item, _ in keyed}]
        batch = keyed[:_OVERVIEW_BATCH]
        lines = [f"What I have accepted about {entity}:"]
        for key, fact in batch:
            lines.append(f"- {fact.subject} — {fact.relation} → {fact.object} "
                         f"[{_source_label(fact.sources)}]")
            self.shown.append(key)
        del self.shown[:-_SHOWN_LIMIT]
        remaining = len(keyed) - len(batch)
        lines.append(f"{remaining} more available; say ‘tell me more’."
                     if remaining else
                     f"That is everything I have accepted about {entity}.")
        self.subject_entity = entity
        self.last_entity = entity
        self.object_entity = None
        self.last_question = None
        self.last_selected_answer = None
        question = f"What do you know about {entity}?"
        return DialogueTurn("elaborated", question, question,
                            text="\n".join(lines))

    def _select_candidate(self, message: str) -> tuple[str | None, bool]:
        if self.pending_result is None:
            return None, False
        candidates = self.pending_result.candidates or []
        normalized_message = message.strip().rstrip(".!? ")
        # A correction phrase is a common way to answer a choice clarification:
        # "I meant the second one" or "No, I meant the Analytical Engine".
        # Interpret it as a selection only while a candidate choice is open.
        selection_phrase = re.fullmatch(
            r"(?:(?:no|actually)\s*[, ]\s*)?"
            r"(?:i\s+(?:meant|mean|want|choose|prefer)|"
            r"the answer is|it is|it's)\s+(.+?)[.!? ]*",
            normalized_message, flags=re.IGNORECASE)
        if selection_phrase is not None:
            normalized_message = selection_phrase.group(1).strip()
        else:
            normalized_message = re.sub(
                r"^(?:(?:no|actually)\s*[, ]\s*)", "",
                normalized_message, flags=re.IGNORECASE)
        words = [word.casefold() for word in _WORD_RE.findall(normalized_message)]
        selection_words = [word for word in words if word not in {
            "the", "one", "option", "answer", "candidate", "choice",
            "please", "i", "d", "choose", "want", "prefer", "mean",
            "meant", "would", "like",
            "yes", "yeah", "yep", "sure", "ok", "okay", "no", "nope", "nah",
        }]
        ordinals = {"first": 0, "1st": 0, "second": 1, "2nd": 1,
                    "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
                    "last": len(candidates) - 1}
        if len(selection_words) == 1 and selection_words[0].isdigit():
            index = int(selection_words[0]) - 1
            return (candidates[index] if 0 <= index < len(candidates) else None), True
        if len(selection_words) == 1 and selection_words[0] in ordinals:
            index = ordinals[selection_words[0]]
            return (candidates[index] if 0 <= index < len(candidates) else None), True
        message_key = tuple(words)
        for candidate in candidates:
            candidate_key = tuple(word.casefold()
                                  for word in _WORD_RE.findall(candidate))
            if message_key == candidate_key:
                return candidate, True
            # Articles are optional in natural answers but do not change which
            # stored candidate the user selected.
            if (message_key[:1] in (("a",), ("an",), ("the",))
                    and message_key[1:] == candidate_key):
                return candidate, True
            if (candidate_key[:1] in (("a",), ("an",), ("the",))
                    and message_key == candidate_key[1:]):
                return candidate, True
        return None, False

    def _resolve_pronoun(self, question: str, *,
                         research_index: Any | None = None
                         ) -> tuple[str | None, str | None]:
        matches = list(_WORD_RE.finditer(question))
        known_surfaces = tuple(self._known_entity_surfaces())
        self._pronoun_options = []
        pronouns = []
        for index, match in enumerate(matches):
            word = match.group(0).casefold()
            if word not in _REFERENTIAL_PRONOUNS:
                continue
            if (word == "it" and index > 0 and index + 2 < len(matches)
                    and matches[index - 1].group(0).casefold()
                    in {"is", "was"}
                    and matches[index + 1].group(0).casefold() == "true"
                    and matches[index + 2].group(0).casefold() == "that"):
                # In "Is it true that ...?", "it" is an expletive subject,
                # not an entity reference for dialogue resolution.
                continue
            if (word == "that" and index >= 3
                    and matches[index - 1].group(0).casefold() == "true"
                    and matches[index - 2].group(0).casefold() == "it"
                    and matches[index - 3].group(0).casefold()
                    in {"is", "was"}):
                # This "that" introduces the proposition in "Is it true
                # that ...?"; it does not refer to an entity either.
                continue
            if (word == "that" and index > 0
                    and matches[index - 1].group(0).casefold()
                    in _THAT_COMPLEMENT_VERBS
                    and index + 1 < len(matches)):
                # A clause-taking predicate followed by "that" commonly
                # introduces a proposition ("the count proves that CRMS ..."),
                # rather than referring to a prior entity. Keep this grammatical
                # use out of entity resolution.
                continue
            if word in {"this", "that"}:
                following = tuple(item.group(0).casefold()
                                  for item in matches[index + 1:])
                # Demonstratives before corpus/source containers are ordinary
                # determiners ("this model", "that paper"), not references to
                # a conversational entity.
                if following and following[0] in {
                        "model", "corpus", "index", "database", "store",
                        "source", "paper", "article", "document"}:
                    continue
                # A demonstrative followed by a known entity name is a
                # determiner ("that Engine"), not a replaceable pronoun.
                if any(following[:len(surface)] == surface
                       for surface in known_surfaces if surface):
                    continue
                # In "the paper that studies X", that introduces a relative
                # clause. It is not an anaphoric pronoun and should remain in
                # the research query so title and abstract retrieval can use it.
                if (word == "that" and index >= 1 and following
                        and matches[index - 1].group(0).casefold()
                        in {"paper", "article", "study", "document", "work"}
                        and following[0] in {
                            "studies", "describes", "examines", "reports",
                            "introduces", "proposes", "investigates",
                            "considers", "uses", "presents"}):
                    continue
            pronouns.append(match)
        if not pronouns:
            return question, None
        if len(pronouns) > 4:
            return None, ("This question has too many pronoun bindings to resolve; "
                          "please name the entities.")
        entities = list(dict.fromkeys(
            entity for entity in (
                self.last_entity, self.subject_entity, self.object_entity,
                *(item.get("entity") for item in self.source_mentions))
            if entity))
        if not entities and self.last_question:
            focus = self._explicit_research_acronym(self.last_question)
            if focus:
                entities = [focus]
        if not entities:
            return None, ("Please name the entity or entities these pronouns "
                          "refer to." if len(pronouns) > 1 else
                          "Please name the entity this pronoun refers to.")
        alternatives: list[tuple[str, tuple[str, ...]]] = []
        for binding in product(entities, repeat=len(pronouns)):
            surface_options = [self._entity_surface_variants(entity)
                               for entity in binding]
            for surfaces in product(*surface_options):
                resolved = question
                for match, surface in reversed(list(zip(pronouns, surfaces))):
                    resolved = (resolved[:match.start()] + surface
                                + resolved[match.end():])
                alternatives.append((resolved, binding))
        if len(pronouns) == 1:
            options: dict[str, str] = {}
            for resolved, binding in alternatives:
                options.setdefault(binding[0], resolved)
            self._pronoun_options = list(options.items())

        supported: dict[tuple[str, ...], list[tuple[str, tuple[Any, ...]]]] = {}
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for resolved, binding in alternatives:
            alternative_key = (resolved, binding)
            if alternative_key in seen:
                continue
            seen.add(alternative_key)
            if research_index is None:
                response, _text = self.knowledge.respond(resolved)
            else:
                response = self.knowledge.research(
                    resolved, research_index).response
            if (response is not None
                    and response.status in {"answered", "ambiguous"}):
                signature = (response.answer, response.truth,
                             tuple(response.candidates or []))
                supported.setdefault(binding, []).append((resolved, signature))
        if len(supported) == 1:
            evidence = next(iter(supported.values()))
            if len({signature for _question, signature in evidence}) == 1:
                # Variants such as "Engine" and "the Engine" can express the
                # same grounded binding. Keep the first (canonical) form.
                return evidence[0][0], None
            return None, ("This reference has conflicting supported readings; "
                          "please restate the question with the entity named.")
        if len(supported) > 1:
            return None, ("The pronouns have multiple bindings with supported "
                          "answers; please name the entities.")
        if len(entities) > 1 and self.source_mentions:
            mentions = list({item["entity"]: item
                             for item in self.source_mentions}.values())
            choices = "; ".join(
                f"{item['entity']} [Source: {item.get('title') or 'source'}]"
                for item in mentions)
            return None, ("The last quoted source mentions " + choices
                          + ". Which entity do you mean? Please restate the "
                          "question with that name.")
        if len(entities) == 1:
            resolved = question
            for match in reversed(pronouns):
                resolved = (resolved[:match.start()] + entities[0]
                            + resolved[match.end():])
            return resolved, None
        if len(entities) > 1:
            names = ", ".join(entities)
            return None, ("I couldn't verify one referent for this pronoun. It "
                          f"could refer to {names}; please name one and restate "
                          "the question.")
        if self.last_entity:
            return None, (
                "I could not verify this follow-up with the learned question "
                f"frames. The previous answer was {self.last_entity}; name the "
                "entity if you mean someone else, or teach this wording with "
                "distinct fact-backed examples."
            )
        return None, ("The pronoun could refer to multiple entities, and the "
                      "available evidence does not resolve them; please name the entities.")

    @staticmethod
    def _explicit_research_acronym(question: str) -> str | None:
        """Return one explicit acronym that can anchor a source follow-up."""
        excluded = {"WHO", "WHAT", "WHERE", "WHEN", "WHY", "HOW"}
        matches = [match.group(0) for match in re.finditer(
            r"\b[A-Z][A-Z0-9]{1,}\b", question)
                   if match.group(0) not in excluded]
        return matches[0] if len(set(matches)) == 1 else None

    @staticmethod
    def _entity_surface_variants(entity: str) -> tuple[str, ...]:
        """Return bounded bare/definite forms for learned question-frame matching."""
        entity = entity.strip()
        words = [word for word in _WORD_RE.findall(entity)]
        bare_words = words[1:] if words[:1] and words[0].casefold() in {
            "a", "an", "the"} else words
        bare = " ".join(bare_words)
        variants = [entity]
        if bare and bare not in variants:
            variants.append(bare)
        definite = f"the {bare}" if bare else ""
        if definite and definite not in variants:
            variants.append(definite)
        return tuple(variants)

    def _canonical_entity(self, value: str) -> str | None:
        canonical = self.knowledge._canonicalize_query_entity(value)
        key = tuple(token.casefold() for token in _WORD_RE.findall(canonical))
        entities = {
            value
            for fact in self.knowledge.facts() + self.knowledge.negative_facts()
            for value in (fact.subject, fact.object)
            if tuple(token.casefold() for token in _WORD_RE.findall(value)) == key
        }
        return next(iter(entities)) if len(entities) == 1 else None

    def _known_entity_surfaces(self) -> dict[tuple[str, ...], str]:
        """Map known surface names and licensed aliases to canonical entities."""
        surfaces: dict[tuple[str, ...], str] = {}
        for fact in self.knowledge.facts() + self.knowledge.negative_facts():
            for entity in (fact.subject, fact.object):
                surfaces[tuple(token.casefold() for token in
                               _WORD_RE.findall(entity))] = entity
        for alias, record in self.knowledge._entity_alias_records().items():
            surfaces[alias] = record["entity"]
        for item in self.source_mentions:
            entity = item.get("entity", "")
            key = tuple(token.casefold() for token in _WORD_RE.findall(entity))
            if key:
                surfaces[key] = entity
        return {key: entity for key, entity in surfaces.items() if key}

    def _source_entity_mentions(
            self, source_sentences: list[dict[str, Any]] | None
            ) -> list[dict[str, str]]:
        """Extract bounded name candidates from exact quoted sentences.

        Capitalisation is used only to offer referents. Resolution still needs
        a fact-backed or source-backed answer for the substituted question.
        """
        if not source_sentences:
            return []
        common_sentence_starts = {
            "a", "an", "the", "this", "that", "these", "those", "when",
            "while", "after", "before", "during", "he", "she", "it", "they",
            "we", "i", "in", "on", "at", "for", "by", "as",
        }
        mentions: dict[tuple[str, ...], dict[str, str]] = {}
        pattern = re.compile(
            r"\b[A-Z][a-z]+(?:['’][A-Z]?[a-z]+)?"
            r"(?:\s+[A-Z][a-z]+(?:['’][A-Z]?[a-z]+)?)*\b")
        for source in source_sentences:
            text = source.get("text")
            if not isinstance(text, str):
                continue
            for match in pattern.finditer(text):
                entity = match.group().strip()
                words = tuple(word.casefold() for word in
                              _WORD_RE.findall(entity))
                if not words or words[0] in common_sentence_starts:
                    continue
                if len(words) == 1 and match.start() == 0:
                    continue
                key = tuple(word.casefold() for word in _WORD_RE.findall(entity))
                mentions.setdefault(key, {
                    "entity": entity,
                    "citation": str(source.get("citation", "")),
                    "title": str(source.get("title", "source")),
                })
        keys = sorted(mentions, key=lambda key: (len(key), key))
        filtered = []
        for key in keys:
            contained = any(
                len(other) > len(key)
                and any(other[start:start + len(key)] == key
                        for start in range(len(other) - len(key) + 1))
                for other in mentions)
            if not contained:
                filtered.append(mentions[key])
        return filtered[:100]

    def _remember_evidence(self, response: QuestionResult) -> None:
        self.source_mentions = []
        facts = response.evidence or []
        subjects = {fact.get("subject", "") for fact in facts if fact.get("subject")}
        objects = {fact.get("object", "") for fact in facts if fact.get("object")}
        for proof in response.inference_proofs or []:
            conclusion = proof.get("conclusion", {})
            if conclusion.get("subject"):
                subjects.add(conclusion["subject"])
            if conclusion.get("object"):
                objects.add(conclusion["object"])
        self.subject_entity = next(iter(subjects)) if len(subjects) == 1 else None
        self.object_entity = next(iter(objects)) if len(objects) == 1 else None
        if response.answer and response.truth is None:
            self.last_entity = self._canonical_entity(response.answer)

    def _resolve_distributive_plural(
            self, question: str, *, research_index: Any | None = None
            ) -> DialogueTurn | None:
        """Answer explicit ``they each`` queries over the last two entities."""
        matches = list(re.finditer(
            r"\b(?:they\s+each|each\s+of\s+them)\b", question,
            flags=re.IGNORECASE))
        if not matches:
            return None
        if len(matches) != 1:
            self.clear()
            text = ("I can resolve one 'they each' reference at a time; "
                    "please ask about one pair of entities.")
            return DialogueTurn("unknown", question, question,
                                response=QuestionResult("unknown", request=text),
                                text=text)
        entities = list(dict.fromkeys(
            entity for entity in (self.subject_entity, self.object_entity)
            if entity))
        if len(entities) != 2:
            self.clear()
            text = ("Please name the two entities that 'they each' refers to.")
            return DialogueTurn("unknown", question, question,
                                response=QuestionResult("unknown", request=text),
                                text=text)

        cue = matches[0]
        records: list[dict[str, Any]] = []
        rendered: list[str] = []
        answer_labels: list[str] = []
        all_evidence: list[dict[str, Any]] = []
        all_proofs: list[list[dict[str, Any]]] = []
        all_inference_proofs: list[dict[str, Any]] = []
        all_templates: list[str] = []
        truths: list[bool | None] = []
        for entity in entities:
            resolved = question[:cue.start()] + entity + question[cue.end():]
            if research_index is None:
                response, _text = self.knowledge.respond(resolved)
                research = None
                result_status = response.status
            else:
                research = self.knowledge.research(resolved, research_index)
                response = research.response
                result_status = research.status
            if response is None or response.status != "answered":
                self.clear()
                text = ("I could not find one supported answer for each entity. "
                        "Please name the entity or ask about them separately.")
                return DialogueTurn(
                    "unknown", question, question,
                    response=QuestionResult("unknown", request=text),
                    text=text)
            records.append({
                "entity": entity,
                "question": resolved,
                "status": result_status,
                "response": response,
                "research": research,
            })
            label = response.answer
            if label is None and response.truth is not None:
                label = "yes" if response.truth else "no"
            if label is None:
                self.clear()
                text = ("The grounded answer did not include a value for each "
                        "entity; please ask about them separately.")
                return DialogueTurn("unknown", question, question,
                                    response=QuestionResult("unknown", request=text),
                                    text=text)
            answer_labels.append(f"{entity}: {label}")
            if research is None:
                answer_text = self.knowledge.render_brief(response)
            else:
                answer_text = self.knowledge.render_research_brief(research)
            if answer_text.startswith("Answer: "):
                answer_text = answer_text[len("Answer: "):]
            rendered.append(f"{entity}: {answer_text}")
            all_evidence.extend(response.evidence or [])
            all_proofs.extend(response.proofs or [])
            all_inference_proofs.extend(response.inference_proofs or [])
            all_templates.extend(response.matched_templates or [])
            truths.append(response.truth)

        aggregate_truth = (truths[0] if truths and all(
            truth is not None and truth == truths[0] for truth in truths)
                           else None)
        aggregate = QuestionResult(
            "answered", answer="; ".join(answer_labels),
            evidence=all_evidence,
            matched_templates=list(dict.fromkeys(all_templates)),
            proofs=all_proofs, truth=aggregate_truth,
            inference_proofs=all_inference_proofs)
        aggregate_research = None
        if research_index is not None:
            passages: dict[str, dict[str, Any]] = {}
            source_sentences: dict[str, dict[str, Any]] = {}
            candidates: dict[tuple[Any, ...], Any] = {}
            derived_context: list[dict[str, Any]] = []
            query_expansions: dict[str, dict[str, Any]] = {}
            for record in records:
                research = record["research"]
                if research is None:
                    continue
                for passage in research.passages or []:
                    citation = passage.get("citation")
                    key = citation or json.dumps(passage, sort_keys=True)
                    passages.setdefault(key, passage)
                for sentence in research.source_sentences or []:
                    key = sentence.get("citation") or json.dumps(
                        sentence, sort_keys=True)
                    source_sentences.setdefault(key, sentence)
                for expansion in research.query_expansions or []:
                    key = json.dumps(expansion, sort_keys=True)
                    query_expansions.setdefault(key, expansion)
                for candidate in research.candidates or []:
                    key = (candidate.subject.casefold(), candidate.relation,
                           candidate.object.casefold(), candidate.source,
                           candidate.polarity)
                    candidates[key] = candidate
                derived_context.extend(research.derived_context or [])
            aggregate_research = ResearchResult(
                "answered", aggregate, list(passages.values()),
                [candidates[key] for key in sorted(candidates)],
                derived_context=derived_context or None,
                query_expansions=list(query_expansions.values()) or None,
                source_sentences=list(source_sentences.values()) or None)
        display_question = (
            question[:cue.start()] + " and ".join(entities)
            + question[cue.end():])
        self.clear()
        return DialogueTurn(
            "answered", question, display_question, response=aggregate,
            research=aggregate_research, text="\n".join(rendered),
            grouped_results=records)

    def _repair_entity_reference(
            self, message: str, *, research_index: Any | None = None
            ) -> DialogueTurn | None:
        """Retry the previous grounded question with one explicitly corrected entity."""
        if (self.pending_result is not None
                and self._select_candidate(message)[1]):
            # While a choice is open, "I meant X" answers that clarification;
            # do not route it through correction of the previous question.
            return None
        correction = _CORRECTION_RE.fullmatch(message.strip())
        if correction is None:
            return None
        target_phrase = correction.group(1).strip()
        target = self._canonical_entity(target_phrase)
        if target is None:
            target_words = tuple(word.casefold()
                                 for word in _WORD_RE.findall(target_phrase))
            target_bare = (target_words[1:] if target_words[:1] in
                           {("a",), ("an",), ("the",)} else target_words)
            possible: set[str] = set()
            for fact in self.knowledge.facts() + self.knowledge.negative_facts():
                for entity in (fact.subject, fact.object):
                    entity_words = tuple(word.casefold()
                                         for word in _WORD_RE.findall(entity))
                    entity_bare = (entity_words[1:] if entity_words[:1] in
                                   {("a",), ("an",), ("the",)} else entity_words)
                    if target_bare and target_bare == entity_bare:
                        possible.add(entity)
            if len(possible) == 1:
                target = next(iter(possible))
        if target is None:
            return DialogueTurn(
                "unknown", message, self.last_question or message,
                text="Please name an entity already present in the knowledge base.")
        if self.last_question is None:
            return DialogueTurn(
                "unknown", message, message,
                text="There is no previous grounded question to correct.")

        target_surface = target_phrase
        surface_words = list(_WORD_RE.finditer(target_surface))
        canonical_words = [word.casefold() for word in _WORD_RE.findall(target)]
        if (surface_words and surface_words[0].group(0).casefold()
                in {"a", "an", "the"}
                and (not canonical_words
                     or canonical_words[0] != surface_words[0].group(0).casefold())):
            target_surface = target_surface[surface_words[0].end():].strip()

        words = [match.group(0).casefold()
                 for match in _WORD_RE.finditer(self.last_question)]
        spans = list(_WORD_RE.finditer(self.last_question))
        entities = self._known_entity_surfaces()
        replacements: set[str] = set()
        for entity_words_tuple, entity in entities.items():
            entity_words = list(entity_words_tuple)
            if not entity_words:
                continue
            for start in range(len(words) - len(entity_words) + 1):
                end = start + len(entity_words)
                if words[start:end] != entity_words:
                    continue
                replaced = (self.last_question[:spans[start].start()] + target_surface
                            + self.last_question[spans[end - 1].end():])
                if replaced != self.last_question:
                    replacements.add(replaced)

        answered: dict[str, tuple[QuestionResult | None, str, ResearchResult | None]] = {}
        for replacement in sorted(replacements):
            if research_index is None:
                response, text = self.knowledge.respond(replacement)
                research = None
            else:
                research = self.knowledge.research(replacement, research_index)
                response = research.response
                text = self.knowledge.render_research_brief(research)
            if response is not None and response.status == "answered":
                answered[replacement] = (response, text, research)

        if len(answered) != 1:
            message_text = (
                "That correction could change multiple entities; please restate "
                "the full question with the intended entity."
                if len(answered) > 1 else
                "I could not verify the corrected question from stored evidence.")
            return DialogueTurn("unknown", message, self.last_question,
                                text=message_text)

        resolved_question, (response, text, research) = next(iter(answered.items()))
        assert response is not None
        self.last_question = resolved_question
        self.last_selected_answer = None
        self.last_writing_subject = None
        self.last_writing_request = None
        self._remember_evidence(response)
        return DialogueTurn("answered", message, resolved_question,
                            response=response, research=research, text=text)

    def _explain_previous_answer(
            self, message: str, *, research_index: Any | None = None
            ) -> DialogueTurn | None:
        """Recompute and explain the previous answer from current evidence."""
        if _EXPLANATION_FOLLOWUP_RE.fullmatch(message.strip()) is None:
            return None
        if self.pending_result is not None:
            return DialogueTurn(
                "ambiguous", message, self.pending_question or message,
                response=self.pending_result,
                text="Please choose a supported answer before asking for its evidence.")
        if self.last_question is None:
            if (self.last_timeline_subject is not None
                    and self.last_timeline_order_by is not None):
                subject = self.last_timeline_subject
                order_by = self.last_timeline_order_by
                writing = self.knowledge.write_timeline(
                    subject, order_by=order_by)
                if writing.statements:
                    return DialogueTurn(
                        writing.status, message,
                        f"Tell me the story of {subject} ordered by {order_by}",
                        text=writing.text, writing=writing)
                self.clear()
                return DialogueTurn(
                    "unknown", message,
                    f"Tell me the story of {subject} ordered by {order_by}",
                    text="I can no longer support that timeline from current evidence.",
                    writing=writing)
            if self.last_writing_subject is not None:
                subject = self.last_writing_subject
                writing = self.knowledge.write_about(subject)
                if writing.statements:
                    return DialogueTurn(
                        writing.status, message,
                        f"Tell me about {subject}", text=writing.text,
                        writing=writing)
                self.clear()
                return DialogueTurn(
                    "unknown", message, f"Tell me about {subject}",
                    text="I can no longer support that summary from current evidence.",
                    writing=writing)
            return DialogueTurn(
                "unknown", message, message,
                response=QuestionResult(
                    "unknown", request="There is no previous grounded answer to explain."),
                text="There is no previous grounded answer to explain yet.")
        resolved = self.last_question
        if research_index is None:
            response, text = self.knowledge.respond(resolved)
            research = None
        else:
            research = self.knowledge.research(resolved, research_index)
            response = research.response
            text = self.knowledge.render_research(research)
        if self.last_selected_answer:
            selected = tuple(token.casefold() for token in
                             _WORD_RE.findall(self.last_selected_answer))
            if response.status == "answered":
                current = tuple(token.casefold() for token in
                                _WORD_RE.findall(response.answer or ""))
                if current != selected:
                    self.clear()
                    return DialogueTurn(
                        "unknown", message, resolved,
                        response=QuestionResult(
                            "unknown", request="The selected answer no longer has current support."),
                        text="I can no longer verify that selected answer from current evidence.")
                self.last_selected_answer = None
            elif (response.status != "ambiguous"
                  or not any(tuple(token.casefold() for token in
                                   _WORD_RE.findall(candidate)) == selected
                             for candidate in response.candidates or [])):
                self.clear()
                return DialogueTurn(
                    "unknown", message, resolved,
                    response=QuestionResult(
                        "unknown", request="The selected answer no longer has current support."),
                    text="I can no longer verify that selected answer from current evidence.")
        if self.last_selected_answer and response.status == "ambiguous":
            selected = tuple(token.casefold() for token in
                             _WORD_RE.findall(self.last_selected_answer))
            evidence = [fact for fact in response.evidence or []
                        if any(tuple(token.casefold() for token in
                                     _WORD_RE.findall(fact.get(field, ""))) == selected
                               for field in ("subject", "object"))]
            inference_proofs = [proof for proof in response.inference_proofs or []
                                if any(tuple(token.casefold() for token in
                                             _WORD_RE.findall(proof.get(
                                                 "conclusion", {}).get(field, "")))
                                       == selected
                                       for field in ("subject", "object"))]
            if not evidence and not inference_proofs:
                self.clear()
                return DialogueTurn(
                    "unknown", message, resolved,
                    response=QuestionResult(
                        "unknown", request="The selected answer no longer has current support."),
                    text="I can no longer verify that selected answer from current evidence.")
            response = QuestionResult(
                "answered", answer=self.last_selected_answer,
                candidates=[self.last_selected_answer], evidence=evidence,
                matched_templates=response.matched_templates,
                inference_proofs=inference_proofs,
                language_evidence=response.language_evidence)
            if research is None:
                text = self.knowledge.render(response)
            else:
                research = ResearchResult(
                    "answered", response=response, passages=research.passages,
                    candidates=None, derived_context=research.derived_context,
                    query_expansions=research.query_expansions,
                    source_sentences=research.source_sentences)
                text = self.knowledge.render_research(research)
        result = DialogueTurn(
            response.status if research is None else research.status,
            message, resolved, response=response, research=research, text=text)
        if response.status == "answered":
            self._remember_evidence(response)
            self.last_selected_answer = None
            self.last_writing_subject = None
            self.last_writing_request = None
        else:
            self.clear()
        return result

    def _resolve_entity_followup(
            self, message: str, *, research_index: Any | None = None
            ) -> DialogueTurn | None:
        """Carry a grounded question frame to an explicitly named entity."""
        match = _FOLLOWUP_ENTITY_RE.fullmatch(message.strip())
        if match is None:
            return None
        target_phrase = next((group for group in match.groups() if group), "")
        target_is_pronoun = target_phrase.strip().casefold() in _REFERENTIAL_PRONOUNS
        if target_is_pronoun:
            if (self.last_question is None and self.last_writing_subject is not None):
                target_candidates = [self.last_writing_subject]
            else:
                candidates = [self.subject_entity, self.object_entity,
                              self.last_entity]
                candidates.extend(item.get("entity")
                                  for item in self.source_mentions)
                target_candidates = sorted({entity for entity in candidates
                                            if entity})
            target = target_candidates[0] if len(target_candidates) == 1 else None
        else:
            source_match = next((item.get("entity")
                                 for item in self.source_mentions
                                 if tuple(word.casefold() for word in
                                          _WORD_RE.findall(item.get("entity", "")))
                                 == tuple(word.casefold() for word in
                                          _WORD_RE.findall(target_phrase.strip()))),
                                None)
            target = (source_match or
                      self._canonical_entity(target_phrase.strip()))
            target_candidates = []
        if target is None and not target_candidates:
            target_words = tuple(word.casefold()
                                 for word in _WORD_RE.findall(target_phrase))
            target_bare = (target_words[1:] if target_words[:1] in
                           {("a",), ("an",), ("the",)} else target_words)
            possible = set()
            for fact in self.knowledge.facts() + self.knowledge.negative_facts():
                for entity in (fact.subject, fact.object):
                    entity_words = tuple(word.casefold()
                                         for word in _WORD_RE.findall(entity))
                    entity_bare = (entity_words[1:] if entity_words[:1] in
                                   {("a",), ("an",), ("the",)} else entity_words)
                    if target_bare and target_bare == entity_bare:
                        possible.add(entity)
            target = next(iter(possible)) if len(possible) == 1 else None
            target_candidates = [target] if target is not None else []
        if not target_candidates and target is not None:
            target_candidates = [target]
        if not target_candidates:
            return DialogueTurn(
                "unknown", message, self.last_question or
                self.last_writing_request or message,
                text=("Please name the entity or entities these pronouns refer to."
                      if target_is_pronoun else
                      "Please name an entity already present in the knowledge base."))

        if (self.last_question is None and self.last_writing_subject is not None
                and self.last_writing_request is not None):
            target = target_candidates[0]
            old_words = [word.casefold() for word in
                         _WORD_RE.findall(self.last_writing_subject)]
            request_words = [word.casefold() for word in
                             _WORD_RE.findall(self.last_writing_request)]
            request_spans = list(_WORD_RE.finditer(self.last_writing_request))
            replacements: set[str] = set()
            for start in range(len(request_words) - len(old_words) + 1):
                end = start + len(old_words)
                if request_words[start:end] != old_words:
                    continue
                replacements.add(
                    self.last_writing_request[:request_spans[start].start()]
                    + target
                    + self.last_writing_request[request_spans[end - 1].end():])
            if len(replacements) != 1:
                return DialogueTurn(
                    "unknown", message, self.last_writing_request,
                    text="I could not resolve that about-request to one learned frame.")
            expanded = next(iter(replacements))
            about_subject, conflict = self.knowledge.resolve_about_request(expanded)
            if conflict or about_subject is None:
                return DialogueTurn(
                    "unknown" if not conflict else "ambiguous", message,
                    expanded, text="That about-request is not uniquely grounded.")
            writing = self.knowledge.write_about(about_subject)
            if not writing.statements:
                self.clear()
                return DialogueTurn(writing.status, message, expanded,
                                    text=writing.text, writing=writing)
            if self.knowledge._resolve_subject_group(about_subject):
                self.subject_entity = None
                self.object_entity = None
                self.last_entity = None
            else:
                self.subject_entity = about_subject
                self.object_entity = None
                self.last_entity = about_subject
            self.last_writing_subject = writing.subject
            self.last_writing_request = expanded
            return DialogueTurn(writing.status, message, expanded,
                                text=writing.text, writing=writing)

        if self.last_question is None:
            return None

        words = [word.casefold() for word in _WORD_RE.findall(self.last_question)]
        spans = list(_WORD_RE.finditer(self.last_question))
        entities = self._known_entity_surfaces()
        replacements: set[str] = set()
        for target in target_candidates:
            target_surface = (target if target_is_pronoun
                              else target_phrase.strip())
            surface_words = list(_WORD_RE.finditer(target_surface))
            canonical_words = [word.casefold() for word in _WORD_RE.findall(target)]
            if (surface_words and surface_words[0].group(0).casefold()
                    in {"a", "an", "the"}
                    and (not canonical_words
                         or canonical_words[0] != surface_words[0].group(0).casefold())):
                target_surface = target_surface[surface_words[0].end():].strip()
            for entity_words_tuple, _entity in entities.items():
                entity_words = list(entity_words_tuple)
                for start in range(len(words) - len(entity_words) + 1):
                    end = start + len(entity_words)
                    if words[start:end] != entity_words:
                        continue
                    replaced = (self.last_question[:spans[start].start()]
                                + target_surface
                                + self.last_question[spans[end - 1].end():])
                    if replaced != self.last_question or target_is_pronoun:
                        replacements.add(replaced)

        answered: dict[str, tuple[QuestionResult | None, str, ResearchResult | None]] = {}
        for replacement in sorted(replacements):
            if research_index is None:
                response, text = self.knowledge.respond(replacement)
                research = None
            else:
                research = self.knowledge.research(replacement, research_index)
                response = research.response
                text = self.knowledge.render_research_brief(research)
            if response is not None and response.status == "answered":
                answered[replacement] = (response, text, research)

        if len(answered) != 1:
            response_text = (
                "That follow-up matches multiple grounded entity substitutions; "
                "please restate the full question."
                if len(answered) > 1 else
                "I could not verify that follow-up from stored evidence.")
            return DialogueTurn("unknown", message, self.last_question,
                                text=response_text)
        resolved_question, (response, text, research) = next(iter(answered.items()))
        assert response is not None
        self.last_question = resolved_question
        self.last_selected_answer = None
        self.last_writing_subject = None
        self.last_writing_request = None
        self._remember_evidence(response)
        return DialogueTurn("answered", message, resolved_question,
                            response=response, research=research, text=text)

    def _resolve_possessive_property_followup(
            self, message: str, *, research_index: Any | None = None
            ) -> DialogueTurn | None:
        """Resolve a bounded "what is its property?" follow-up by evidence."""
        match = _POSSESSIVE_PROPERTY_FOLLOWUP_RE.fullmatch(message)
        if match is None:
            return None
        wh = match.group("wh").casefold()
        auxiliary = match.group("aux").strip()
        if auxiliary in {"'s", "’s"}:
            auxiliary = "is"
        property_phrase = match.group("property").strip()
        entities = sorted({entity for entity in
                           (self.subject_entity, self.object_entity) if entity})
        supported: dict[str, tuple[str, QuestionResult, ResearchResult | None, str]] = {}
        for entity in entities:
            resolved_question = (
                f"{wh.capitalize()} {auxiliary} the {property_phrase} of {entity}?")
            if research_index is None:
                response, text = self.knowledge.respond(resolved_question)
                research = None
            else:
                research = self.knowledge.research(resolved_question, research_index)
                response = research.response
                text = self.knowledge.render_research_brief(research)
            if response is not None and response.status == "answered":
                supported[entity] = (resolved_question, response, research, text)
        if len(supported) == 1:
            resolved_question, response, research, text = next(iter(supported.values()))
            self._remember_evidence(response)
            self.last_question = resolved_question
            self.last_selected_answer = None
            self.last_writing_subject = None
            self.last_writing_request = None
            return DialogueTurn("answered", message, resolved_question,
                                response=response, research=research, text=text)
        self.clear()
        if supported:
            candidates = sorted(supported)
            request = ("That possessive reference matches more than one grounded "
                       "entity: " + ", ".join(candidates) + ". Please name one.")
            response = QuestionResult("ambiguous", candidates=candidates,
                                      request=request)
            return DialogueTurn("ambiguous", message, message, response=response,
                                text=request)
        request = ("I could not resolve that possessive reference to one grounded "
                   "answer. Please name the entity or restate the question.")
        response = QuestionResult("unknown", request=request)
        return DialogueTurn("unknown", message, message, response=response,
                            text=request)

    def _resolve_contractions(
            self, question: str, *, research_index: Any | None = None
            ) -> tuple[str | None, str | None]:
        """Resolve bounded contractions only when evidence selects a reading."""
        alternatives_by_match: list[
            tuple[re.Match[str], tuple[str, ...], bool]] = []
        interrogatives = {"who", "what", "where", "when", "why", "how"}
        for match in _AUXILIARY_CONTRACTION_RE.finditer(question):
            stem = match.group(1).casefold()
            suffix = match.group(2).casefold()
            if suffix == "s":
                readings = ("is", "has")
            elif suffix == "re":
                readings = ("are",)
            elif suffix == "ve":
                readings = ("have",)
            elif suffix == "ll":
                readings = ("will",)
            elif suffix == "m":
                readings = ("am",)
            elif stem in interrogatives:
                readings = ("did", "would", "had")
            else:
                readings = ("would", "had")
            alternatives_by_match.append((match, readings, True))
        for match in _NEGATIVE_CONTRACTION_RE.finditer(question):
            readings = _NEGATIVE_CONTRACTION_READINGS[
                match.group(1).casefold()]
            alternatives_by_match.append((match, readings, False))
        alternatives_by_match.sort(key=lambda item: item[0].start())
        if not alternatives_by_match:
            return None, None
        if len(alternatives_by_match) > 3:
            return None, "This question has too many contraction readings; please rephrase it."
        alternatives = set()
        for readings in product(*(item[1] for item in alternatives_by_match)):
            expanded = question
            for (match, _options, auxiliary), reading in reversed(
                    list(zip(alternatives_by_match, readings))):
                if auxiliary:
                    replacement = f"{match.group(1)} {reading}"
                else:
                    replacement = reading
                    if match.group(0)[0].isupper():
                        replacement = replacement[0].upper() + replacement[1:]
                expanded = (expanded[:match.start()] + replacement
                            + expanded[match.end():])
            alternatives.add(expanded)
        supported = []
        fully_retrieved = []
        for expanded in sorted(alternatives):
            if research_index is None:
                response, _text = self.knowledge.respond(expanded)
            else:
                research = self.knowledge.research(expanded, research_index)
                response = research.response
                expanded_tokens = tuple(_WORD_RE.findall(expanded))
                if any(tuple(_WORD_RE.findall(item.get("text", "")))
                       == expanded_tokens
                       for item in research.source_sentences or []):
                    fully_retrieved.append(expanded)
            if response is not None and response.status == "answered":
                supported.append(expanded)
        if len(supported) == 1:
            return supported[0], None
        if len(supported) > 1:
            return None, ("The contraction has multiple readings with supported "
                          "answers; please write it out.")
        if len(fully_retrieved) == 1:
            return fully_retrieved[0], None
        if len(fully_retrieved) > 1:
            return None, ("The contraction has multiple readings that match "
                          "supplied sources; please write it out.")
        return None, None

    def turn(self, question: str, *, research_index: Any | None = None) -> DialogueTurn:
        question = question.strip()
        if not question:
            raise ValueError("question must be a non-empty string")
        if _THANKS_RE.fullmatch(question):
            return DialogueTurn("smalltalk", question, question, text="You're welcome.")
        if _HELP_RE.fullmatch(question):
            return DialogueTurn(
                "help", question, question,
                text=("Ask about indexed sources or accepted facts. Add sources "
                      "with /source or /source-dir; ask ‘why?’ for evidence."))
        if _OUT_OF_SCOPE_SMALLTALK_RE.fullmatch(question):
            return DialogueTurn(
                "out_of_scope", question, question,
                text=("CRMS answers questions from supplied sources and learned "
                      "facts; try asking about a stored fact or adding a source."))
        if (_BARE_YES_NO_RE.fullmatch(question)
                and self.pending_result is None):
            return DialogueTurn(
                "clarify", question, question,
                text=("I don't have an open yes/no question in this conversation. "
                      "What would you like to ask or confirm?"))
        repaired = self._repair_entity_reference(
            question, research_index=research_index)
        if repaired is not None:
            return repaired
        explanation = self._explain_previous_answer(
            question, research_index=research_index)
        if explanation is not None:
            return explanation
        self.last_timeline_subject = None
        self.last_timeline_order_by = None
        followup = self._resolve_entity_followup(
            question, research_index=research_index)
        if followup is not None:
            return followup
        possessive_followup = self._resolve_possessive_property_followup(
            question, research_index=research_index)
        if possessive_followup is not None:
            return possessive_followup
        expanded, contraction_clarification = self._resolve_contractions(
            question, research_index=research_index)
        if contraction_clarification:
            self.clear()
            response = QuestionResult("unknown", request=contraction_clarification)
            return DialogueTurn("unknown", question, question, response,
                                text=contraction_clarification)
        if expanded is not None:
            if research_index is None:
                response, text = self.knowledge.respond(expanded)
                result = DialogueTurn(response.status, question, expanded,
                                      response=response, text=text)
            else:
                research = self.knowledge.research(expanded, research_index)
                response = research.response
                text = self.knowledge.render_research_brief(research)
                result = DialogueTurn(research.status, question, expanded,
                                      response=response, research=research,
                                      text=text)
            if response is not None and response.status == "answered":
                self._remember_evidence(response)
                self.last_question = expanded
                self.last_selected_answer = None
                self.last_writing_subject = None
                self.last_writing_request = None
            else:
                self.clear()
            return result
        selected, selection_input = self._select_candidate(question)
        if selection_input and self.pending_result is not None:
            candidates = self.pending_result.candidates or []
            if selected is None:
                choices = "; ".join(f"{i}. {value}"
                                     for i, value in enumerate(candidates, 1))
                text = f"Please choose one of the supported answers: {choices}."
                return DialogueTurn("ambiguous", question,
                                    self.pending_question or question,
                                    response=self.pending_result, text=text)
            selected_tokens = tuple(token.casefold() for token in
                                    _WORD_RE.findall(selected))
            selected_paths = [
                proof for proof in self.pending_result.proofs or []
                if proof and tuple(token.casefold() for token in _WORD_RE.findall(
                    proof[-1].get("object", ""))) == selected_tokens
            ]
            inference_proofs = [
                proof for proof in self.pending_result.inference_proofs or []
                if any(tuple(token.casefold() for token in _WORD_RE.findall(
                    proof.get("conclusion", {}).get(field, ""))) == selected_tokens
                       for field in ("subject", "object"))
            ]
            lineage_rows = [fact for proof in selected_paths for fact in proof]
            lineage_rows.extend(
                fact for proof in inference_proofs
                for fact in self.knowledge._inference_fact_leaves(proof))
            if lineage_rows:
                lineage_keys = {
                    (tuple(_WORD_RE.findall(fact.get("subject", "").casefold())),
                     tuple(_WORD_RE.findall(fact.get("relation", "").casefold())),
                     tuple(_WORD_RE.findall(fact.get("object", "").casefold())),
                     tuple(sorted((str(name).casefold(), str(value).casefold())
                                  for name, value in fact.get("qualifiers", []))))
                    for fact in lineage_rows
                }
                evidence = [
                    fact for fact in self.pending_result.evidence or []
                    if (tuple(_WORD_RE.findall(fact.get("subject", "").casefold())),
                        tuple(_WORD_RE.findall(fact.get("relation", "").casefold())),
                        tuple(_WORD_RE.findall(fact.get("object", "").casefold())),
                        tuple(sorted((str(name).casefold(), str(value).casefold())
                                     for name, value in fact.get("qualifiers", []))))
                    in lineage_keys
                ]
            else:
                evidence = [fact for fact in self.pending_result.evidence or []
                            if any(tuple(token.casefold() for token in _WORD_RE.findall(
                                fact.get(field, ""))) == selected_tokens
                                   for field in ("subject", "object"))]
            response = QuestionResult(
                "answered", answer=selected, candidates=[selected],
                evidence=evidence,
                matched_templates=self.pending_result.matched_templates,
                proofs=selected_paths, inference_proofs=inference_proofs)
            resolved_question = self.pending_question or question
            self._remember_evidence(response)
            self._clear_pending()
            self.last_question = resolved_question
            self.last_selected_answer = selected
            self.last_writing_subject = None
            self.last_writing_request = None
            return DialogueTurn("answered", question, resolved_question,
                                response=response,
                                text=self.knowledge.render_brief(response))
        if (self.pending_result is not None
                and _BARE_YES_NO_RE.fullmatch(question)):
            candidates = self.pending_result.candidates or []
            choices = "; ".join(f"{i}. {value}"
                                 for i, value in enumerate(candidates, 1))
            return DialogueTurn(
                "ambiguous", question, self.pending_question or question,
                response=self.pending_result,
                text=("Yes or no does not identify one of the supported answers. "
                      f"Please choose: {choices}."))
        self._clear_pending()
        grouped = self._resolve_distributive_plural(
            question, research_index=research_index)
        if grouped is not None:
            return grouped
        resolved, clarification = self._resolve_pronoun(
            question, research_index=research_index)
        if resolved is None:
            candidate_entities = list(dict.fromkeys(
                entity for entity in (
                    self.last_entity, self.subject_entity, self.object_entity,
                    *(item.get("entity") for item in self.source_mentions))
                if entity))
            if candidate_entities:
                source_evidence = [
                    {"entity": item["entity"], "citation": item["citation"],
                     "title": item["title"]}
                    for item in self.source_mentions]
                response = QuestionResult(
                    "unknown", candidates=candidate_entities,
                    request=clarification,
                    language_evidence=[{"kind": "source_entity_candidates",
                                        "mentions": source_evidence}])
                if len(self._pronoun_options) >= 2:
                    options = self._pronoun_options[:_BINDING_OPTION_LIMIT]
                    self.pending_binding = {
                        "question": question,
                        "options": [{"entity": entity, "resolved": resolved}
                                    for entity, resolved in options]}
                    numbered = "; ".join(
                        f"{number}. {entity}"
                        for number, (entity, _) in enumerate(options, 1))
                    clarification = (f"{clarification} Or reply with a number or "
                                     f"a name: {numbered}.")
            else:
                self.clear()
                response = QuestionResult("unknown", request=clarification)
            return DialogueTurn("unknown", question, question, response, text=clarification or "")
        counterfactual = self.knowledge.ask_counterfactual_source_question(resolved)
        if counterfactual is not None:
            self.clear()
            return DialogueTurn(
                counterfactual.status, question, resolved,
                text=self.knowledge.render_counterfactual(counterfactual),
                counterfactual=counterfactual)
        about_subject, about_conflict = self.knowledge.resolve_about_request(resolved)
        if about_conflict:
            self.clear()
            request = "This about-request matches multiple learned frames; please rephrase it."
            return DialogueTurn("ambiguous", question, resolved,
                                text=request)
        if about_subject is not None:
            writing = self.knowledge.write_about(about_subject)
            if writing.statements:
                if self.knowledge._resolve_subject_group(about_subject):
                    self.subject_entity = None
                    self.object_entity = None
                    self.last_entity = None
                else:
                    self.subject_entity = about_subject
                    self.object_entity = None
                    self.last_entity = about_subject
                self.last_question = None
                self.last_selected_answer = None
                self.last_writing_subject = writing.subject
                self.last_writing_request = resolved
            else:
                self.clear()
            return DialogueTurn(writing.status, question, resolved,
                                text=writing.text, writing=writing)
        research: ResearchResult | None = None
        if research_index is None:
            response, text = self.knowledge.respond(resolved)
            result = DialogueTurn(response.status, question, resolved,
                                 response=response, text=text)
        else:
            research = self.knowledge.research(resolved, research_index)
            response = research.response
            text = self.knowledge.render_research_brief(research)
            result = DialogueTurn(research.status, question, resolved,
                                 response=response, research=research, text=text)

        if response is not None and response.status == "answered":
            self._remember_evidence(response)
            self.last_question = resolved
            self.last_selected_answer = None
            self.last_writing_subject = None
            self.last_writing_request = None
            self.last_selected_answer = None
        else:
            # Unknown, ambiguous, or review-only turns must not leave a stale
            # referent available for an unrelated later pronoun.
            self.clear()
            if response is not None and response.status == "ambiguous" and response.candidates:
                self.pending_question = resolved
                self.pending_result = response
            elif research is not None and research.status in {
                    "sources_found", "needs_review"}:
                # A quoted answer awaiting review is still text the user just
                # read, so its names stay available as candidate referents.
                self.source_mentions = self._source_entity_mentions(
                    research.source_sentences)
                if self.source_mentions:
                    # Keep only entities from text actually quoted this turn;
                    # they are candidate referents, not accepted knowledge.
                    self.last_question = resolved
                else:
                    # Retain a source-backed acronym as a discourse focus.
                    focus = self._explicit_research_acronym(resolved)
                    evidence_text = " ".join(
                        [str(item.get("text", "")) + " "
                         + str(item.get("title", ""))
                         for item in (research.source_sentences or [])]
                        + [str(item.get("excerpt", "")) + " "
                           + str(item.get("title", ""))
                           for item in (research.passages or [])])
                    if focus and focus.casefold() in evidence_text.casefold():
                        self.last_question = resolved
        return result

    def save(self, path: str) -> None:
        """Save only the small dialogue state; knowledge is stored separately."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps({"format_version": 13, "last_entity": self.last_entity,
                        "subject_entity": self.subject_entity,
                        "object_entity": self.object_entity,
                        "last_question": self.last_question,
                        "source_mentions": self.source_mentions,
                        "last_selected_answer": self.last_selected_answer,
                        "last_writing_subject": self.last_writing_subject,
                        "last_writing_request": self.last_writing_request,
                        "last_timeline_subject": self.last_timeline_subject,
                        "last_timeline_order_by": self.last_timeline_order_by,
                        "pending_question": self.pending_question,
                        "pending_result": asdict(self.pending_result)
                        if self.pending_result else None,
                        "last_intent_hypothesis": (
                            asdict(self.last_intent_hypothesis)
                            if self.last_intent_hypothesis else None),
                        "history": self.history,
                        "intent_trace": self.intent_trace,
                        "active_task_intent": self.active_task_intent,
                        "last_answered": self.last_answered,
                        "shown": self.shown,
                        "pending_dialogue_slot": self.pending_dialogue_slot},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    @classmethod
    def load(cls, knowledge: CRMSKnowledgeBase, path: str, *,
             research_index: Any | None = None,
             intent_model: CRMSDialogueIntentModel | None = None
             ) -> "CRMSDialogue":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format_version") not in (
                 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13):
            raise ValueError("unsupported dialogue-state format version")
        dialogue = cls(knowledge, intent_model=intent_model)
        pending_dialogue_slot = payload.get("pending_dialogue_slot")
        if pending_dialogue_slot not in (None, "elaboration_topic"):
            raise ValueError("stored dialogue slot is malformed")
        dialogue.pending_dialogue_slot = pending_dialogue_slot
        active_task_intent = payload.get("active_task_intent")
        if (active_task_intent is not None
                and (not isinstance(active_task_intent, str)
                     or active_task_intent not in _INTENT_TASKS)):
            raise ValueError("stored active task intent is malformed")
        dialogue.active_task_intent = active_task_intent
        intent_trace = payload.get("intent_trace", [])
        trace_keys = {
            "dialogue_act", "task_intent", "decision", "matched_frame",
            "context_predicates", "selected_value", "basis", "evidence_refs",
        }
        if not isinstance(intent_trace, list) or len(intent_trace) > _INTENT_TRACE_LIMIT:
            raise ValueError("stored intent trace is malformed")
        for entry in intent_trace:
            if not isinstance(entry, dict) or set(entry) != trace_keys:
                raise ValueError("stored intent trace entry is malformed")
            if (not isinstance(entry["dialogue_act"], str)
                    or len(entry["dialogue_act"]) > 80
                    or entry["task_intent"] is not None
                    and (not isinstance(entry["task_intent"], str)
                         or entry["task_intent"] not in _INTENT_TASKS)
                    or not isinstance(entry["decision"], str)
                    or entry["decision"] not in {"selected", "ambiguous", "unlicensed"}
                    or entry["matched_frame"] is not None
                    and (not isinstance(entry["matched_frame"], str)
                         or len(entry["matched_frame"]) > 512)
                    or not isinstance(entry["context_predicates"], list)
                    or len(entry["context_predicates"]) > 20
                    or any(not isinstance(value, str) or len(value) > 512
                           for value in entry["context_predicates"])
                    or entry["selected_value"] is not None
                    and (not isinstance(entry["selected_value"], str)
                         or len(entry["selected_value"]) > 512)
                    or not isinstance(entry["basis"], str)
                    or len(entry["basis"]) > 80
                    or not isinstance(entry["evidence_refs"], list)
                    or len(entry["evidence_refs"]) > 100
                    or any(not isinstance(value, str) or len(value) > 512
                           for value in entry["evidence_refs"])):
                raise ValueError("stored intent trace entry is malformed")
        dialogue.intent_trace = intent_trace
        last_question = payload.get("last_question")
        if last_question is not None:
            if not isinstance(last_question, str):
                raise ValueError("stored previous question is malformed")
            dialogue.last_question = last_question
        source_mentions = payload.get("source_mentions", [])
        if not isinstance(source_mentions, list) or len(source_mentions) > 100:
            raise ValueError("stored source referents are malformed")
        if research_index is not None:
            verified_mentions = []
            for item in source_mentions:
                if not isinstance(item, dict):
                    raise ValueError("stored source referent is malformed")
                entity, citation = item.get("entity"), item.get("citation")
                if (not isinstance(entity, str) or not entity.strip()
                        or not isinstance(citation, str) or not citation.strip()):
                    raise ValueError("stored source referent is malformed")
                title = item.get("title", "source")
                if not isinstance(title, str):
                    raise ValueError("stored source title is malformed")
                try:
                    cited_text = research_index.resolve_citation(citation)
                    document_id = citation.partition("#sha256=")[0]
                    indexed_title = research_index.document(document_id).title
                except (AttributeError, KeyError, TypeError, ValueError):
                    # A source may have been removed or revised since the
                    # dialogue was saved. Its names must not remain usable as
                    # referents unless the current index still verifies it.
                    continue
                recovered = dialogue._source_entity_mentions([{
                    "text": cited_text, "citation": citation,
                    "title": indexed_title,
                }])
                if any(candidate["entity"].casefold() == entity.casefold()
                       for candidate in recovered):
                    verified_mentions.append({
                        "entity": entity, "citation": citation,
                        "title": indexed_title or title,
                    })
            dialogue.source_mentions = verified_mentions
        selected_answer = payload.get("last_selected_answer")
        if selected_answer is not None:
            if not isinstance(selected_answer, str):
                raise ValueError("stored selected answer is malformed")
            dialogue.last_selected_answer = selected_answer
        writing_subject = payload.get("last_writing_subject")
        if writing_subject is not None:
            canonical = dialogue._canonical_entity(writing_subject)
            group = knowledge._resolve_subject_group(writing_subject)
            if canonical is None and group is None:
                raise ValueError("stored writing referent is not present in the knowledge base")
            dialogue.last_writing_subject = (
                canonical if canonical is not None else " and ".join(group or ()))
        writing_request = payload.get("last_writing_request")
        if writing_request is not None:
            if not isinstance(writing_request, str):
                raise ValueError("stored writing request is malformed")
            subject, conflict = knowledge.resolve_about_request(writing_request)
            if (conflict or subject is None
                    or tuple(token.casefold() for token in
                             _WORD_RE.findall(subject))
                    != tuple(token.casefold() for token in
                             _WORD_RE.findall(dialogue.last_writing_subject or ""))):
                raise ValueError("stored writing request does not match its grounded subject")
            dialogue.last_writing_request = writing_request
        timeline_subject = payload.get("last_timeline_subject")
        timeline_order_by = payload.get("last_timeline_order_by")
        if (timeline_subject is None) != (timeline_order_by is None):
            raise ValueError("stored timeline referent is incomplete")
        if timeline_subject is not None:
            canonical = dialogue._canonical_entity(timeline_subject)
            if canonical is None:
                raise ValueError("stored timeline referent is not present in the knowledge base")
            if timeline_order_by not in ("year", "date"):
                raise ValueError("stored timeline order is malformed")
            if (dialogue.last_question is not None
                    or dialogue.last_writing_subject is not None):
                raise ValueError("stored dialogue contains conflicting follow-up contexts")
            dialogue.last_timeline_subject = canonical
            dialogue.last_timeline_order_by = timeline_order_by
        entity = payload.get("last_entity")
        if entity is not None:
            canonical = dialogue._canonical_entity(entity)
            if canonical is None:
                raise ValueError("dialogue referent is not present in the knowledge base")
            dialogue.last_entity = canonical
        for field in ("subject_entity", "object_entity"):
            value = payload.get(field)
            if value is not None:
                canonical = dialogue._canonical_entity(value)
                if canonical is None:
                    raise ValueError("dialogue referent is not present in the knowledge base")
                setattr(dialogue, field, canonical)
        if payload.get("format_version") == 1 and dialogue.last_entity:
            dialogue.subject_entity = dialogue.last_entity
        pending_question = payload.get("pending_question")
        pending_result = payload.get("pending_result")
        if pending_question is not None or pending_result is not None:
            if not isinstance(pending_question, str) or not isinstance(pending_result, dict):
                raise ValueError("stored pending clarification is malformed")
            dialogue.pending_question = pending_question
            dialogue.pending_result = QuestionResult(**pending_result)
        raw_intent = payload.get("last_intent_hypothesis")
        if raw_intent is not None:
            intent_fields = {
                "dialogue_act", "task_intent", "decision", "matched_frame",
                "context_predicates", "alternatives", "selected_value", "basis",
                "evidence_refs", "runtime_route",
            }
            # State written before evidence_refs was added remains readable.
            if isinstance(raw_intent, dict) and "evidence_refs" not in raw_intent:
                intent_fields.remove("evidence_refs")
            if isinstance(raw_intent, dict) and "runtime_route" not in raw_intent:
                intent_fields.remove("runtime_route")
            if (not isinstance(raw_intent, dict)
                    or set(raw_intent) != intent_fields):
                raise ValueError("stored intent hypothesis is malformed")
            dialogue_act = raw_intent.get("dialogue_act")
            task_intent = raw_intent.get("task_intent")
            decision = raw_intent.get("decision")
            matched_frame = raw_intent.get("matched_frame")
            context_predicates = raw_intent.get("context_predicates", [])
            alternatives = raw_intent.get("alternatives", [])
            selected_value = raw_intent.get("selected_value")
            basis = raw_intent.get("basis")
            evidence_refs = raw_intent.get("evidence_refs", [])
            runtime_route = raw_intent.get("runtime_route")
            if (not isinstance(dialogue_act, str) or not dialogue_act.strip()
                    or len(dialogue_act) > 80
                    or (task_intent is not None
                        and (not isinstance(task_intent, str)
                             or len(task_intent) > 120))
                    or not isinstance(decision, str)
                    or decision not in {"selected", "ambiguous", "unlicensed"}
                    or (matched_frame is not None
                        and (not isinstance(matched_frame, str)
                             or len(matched_frame) > 120))
                    or not isinstance(context_predicates, list)
                    or len(context_predicates) > 16
                    or any(not isinstance(value, str) or len(value) > 120
                           for value in context_predicates)
                    or not isinstance(alternatives, list) or len(alternatives) > 32
                    or any(not isinstance(value, str) or len(value) > 512
                           for value in alternatives)
                    or (selected_value is not None
                        and (not isinstance(selected_value, str)
                             or len(selected_value) > 512))
                    or not isinstance(evidence_refs, list)
                    or len(evidence_refs) > 32
                    or any(not isinstance(value, str) or len(value) > 2048
                           for value in evidence_refs)
                    or (runtime_route is not None
                        and (not isinstance(runtime_route, str)
                             or runtime_route not in {
                                 "greeting", "farewell", "thanks",
                                 "acknowledgement", "reaction", "elaboration"}))
                    or not isinstance(basis, str)
                    or basis not in {"hand_checked_runtime_rule",
                                     "portable_dialogue_model"}):
                raise ValueError("stored intent hypothesis is malformed")
            dialogue.last_intent_hypothesis = UserIntentHypothesis(
                dialogue_act=dialogue_act,
                task_intent=task_intent,
                decision=decision,
                matched_frame=matched_frame,
                context_predicates=tuple(context_predicates),
                alternatives=tuple(alternatives),
                selected_value=selected_value,
                basis=basis,
                evidence_refs=tuple(evidence_refs),
                runtime_route=runtime_route,
            )
        history = payload.get("history", [])
        if (not isinstance(history, list) or len(history) > _HISTORY_LIMIT
                or any(not isinstance(item, dict) or set(item) != _HISTORY_KEYS
                       or any(not isinstance(value, str)
                              or len(value) > _HISTORY_FIELD_LIMIT
                              for value in item.values())
                       for item in history)):
            raise ValueError("stored conversation history is malformed")
        dialogue.history = history
        last_answered = payload.get("last_answered")
        if last_answered is not None:
            if (not isinstance(last_answered, dict)
                    or set(last_answered) != {"question", "answer"}
                    or any(not isinstance(value, str)
                           or len(value) > _HISTORY_QUESTION_LIMIT
                           for value in last_answered.values())
                    or not last_answered["question"].strip()):
                raise ValueError("stored last answer is malformed")
            dialogue.last_answered = last_answered
        shown = payload.get("shown", [])
        if (not isinstance(shown, list) or len(shown) > _SHOWN_LIMIT
                or any(not isinstance(value, str) or len(value) > 1000
                       for value in shown)):
            raise ValueError("stored shown facts are malformed")
        dialogue.shown = shown
        return dialogue
