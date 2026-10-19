"""Bounded, explicitly fictional story composition from a small story grammar.

This module does not treat generated story details as facts. It provides a
deterministic, inspectable writing path for short stories while CRMS has no
general-purpose text generator.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import unicodedata


@dataclass(frozen=True)
class StoryArtifact:
    topic: str
    tone: str
    template_id: str
    beats: tuple[tuple[str, str], ...]

    @property
    def text(self) -> str:
        return " ".join(sentence for _role, sentence in self.beats)

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "fictional_story",
            "version": 1,
            "topic": self.topic,
            "tone": self.tone,
            "template_id": self.template_id,
            "beats": [{"role": role, "text": sentence}
                      for role, sentence in self.beats],
        }

    def render(self) -> str:
        roles = " → ".join(role for role, _sentence in self.beats)
        return ("Fictional short story (invented details; no factual claims):\n"
                + self.text + "\n"
                + f"Story structure: {roles}. Template: {self.template_id}.")


_STORY_GRAMMARS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("discovery-and-cooperation-v1", (
        ("discovery", "One afternoon, Rowan found a tiny door beneath a sign that read “{topic}.”"),
        ("problem", "Behind it was a village whose only bridge had vanished just as the river began to rise."),
        ("attempt", "The villagers argued until Rowan asked what each person could contribute."),
        ("resolution", "A carpenter brought planks, a baker brought rope, and a child held the lantern; together they built a safe crossing."),
        ("change", "At dawn, Rowan left the door open, knowing the next visitor would find a village ready to help."),
    )),
    ("mystery-and-repair-v1", (
        ("discovery", "At the old station marked “{topic},” Mira found a pocket watch ticking backward."),
        ("problem", "Each time it chimed, one of the station clocks went dark."),
        ("attempt", "Mira followed the faint ticking beneath the platform and found a loose gear caught in a crack."),
        ("resolution", "She freed the gear, and every clock began keeping time together again."),
        ("change", "The watch stopped in her palm, its hands pointing to the moment she had solved the mystery."),
    )),
    ("small-kindness-v1", (
        ("discovery", "Beside a garden gate labelled “{topic},” Eli found a seed glowing like a small green star."),
        ("problem", "The garden was dry, and nobody believed one seed could make a difference."),
        ("attempt", "Eli shared the seed with the neighbors, who each brought a cup of water."),
        ("resolution", "By morning, a bright vine had climbed the fence and offered shade to the whole lane."),
        ("change", "Eli kept one seed for the next dry season and learned that small help travels far."),
    )),
    ("comic-council-v1", (
        ("discovery", "In the hall marked “{topic},” a goose named Mayor Waddles called an emergency meeting."),
        ("problem", "The town's enormous cheese had rolled downhill and blocked the only road."),
        ("attempt", "Waddles organized a pushing team, but the cheese rolled the other way whenever he honked."),
        ("resolution", "A quiet mouse suggested turning the cheese into a feast, and the road cleared as everyone came to eat."),
        ("change", "Waddles declared the meeting delicious and appointed the mouse Minister of Directions."),
    )),
)


def generate_short_story(topic: str, *, tone: str = "adventure") -> StoryArtifact:
    """Compose a deterministic five-beat fictional story around a user topic."""
    if not isinstance(topic, str):
        raise ValueError("story topic must be text")
    if any(unicodedata.category(character) == "Cc" for character in topic):
        raise ValueError("story topic must contain printable text on one line")
    normalized = " ".join(topic.split()).strip(" \t\r\n.,!?;:")
    if not normalized or len(normalized) > 120:
        raise ValueError("story topic must contain 1 to 120 printable characters")
    if not isinstance(tone, str) or tone.casefold() not in {"adventure", "funny"}:
        raise ValueError("story tone must be 'adventure' or 'funny'")
    tone = tone.casefold()
    eligible = [row for row in _STORY_GRAMMARS
                if (tone == "funny") == row[0].startswith("comic-")]
    digest = hashlib.sha256(
        (tone + "\0" + normalized.casefold()).encode("utf-8")).digest()
    template_id, grammar = eligible[int.from_bytes(digest[:4], "big") % len(eligible)]
    beats = tuple((role, sentence.format(topic=normalized))
                  for role, sentence in grammar)
    return StoryArtifact(normalized, tone, template_id, beats)
