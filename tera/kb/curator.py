"""The curator: decides what deserves a permanent place in the knowledge base.

This is the component that satisfies the requirement *"it should not store
unnecessary things like questions"*. It is deliberately rule-based, so it
works with no model at all — which keeps Tera's architecture centred on the
knowledge base rather than the LLM. A real model can *assist* (see
`llm.extract`) but never gates the core behaviour.

Decision classes
----------------
store              -> a durable, declarative piece of information
reject:question    -> interrogatives ("What is ...?", "Can you ...?")
reject:command     -> imperatives / requests ("Write me a poem")
reject:chitchat    -> greetings, thanks, acknowledgements, filler
reject:empty       -> blank / whitespace
reject:too_short   -> below the minimum length
reject:too_long    -> above the maximum length
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# --- decision constants --------------------------------------------------
STORE = "store"
REJECT_QUESTION = "reject:question"
REJECT_COMMAND = "reject:command"
REJECT_CHITCHAT = "reject:chitchat"
REJECT_EMPTY = "reject:empty"
REJECT_TOO_SHORT = "reject:too_short"
REJECT_TOO_LONG = "reject:too_long"


@dataclass
class CuratorResult:
    decision: str
    reason: str = ""
    content: str = ""
    category: str = "fact"
    confidence: float = 0.6
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    meta: dict = field(default_factory=dict)

    @property
    def should_store(self) -> bool:
        return self.decision == STORE


# --- vocabularies --------------------------------------------------------
_WH = {"what", "who", "whom", "whose", "which", "when", "where", "why", "how"}
_AUX = {
    "is", "are", "was", "were", "am", "do", "does", "did", "can", "could",
    "will", "would", "should", "shall", "may", "might", "must",
}
_QUESTION_PHRASES = (
    "tell me", "can you", "could you", "would you", "will you", "do you",
    "does it", "did you", "are you", "is it", "is there", "are there",
    "i want to know", "i'd like to know", "id like to know", "i wonder",
    "what is", "what are", "what's", "whats", "who is", "who's", "whos",
    "where is", "where's", "wheres", "when is", "when's", "why is", "how is",
    "how do", "how does", "how can", "how many", "how much", "how long",
    "how to", "explain", "define", "what about", "any idea",
)
_COMMAND_VERBS = {
    "write", "make", "create", "build", "generate", "draw", "design", "compose",
    "translate", "summarise", "summarize", "rewrite", "list", "show", "give",
    "find", "search", "look", "help", "calculate", "compute", "convert", "fix",
    "debug", "play", "open", "send", "remind", "schedule", "draft", "add",
    "delete", "remove", "update", "change", "set", "call", "email", "post",
    "print", "count", "compare", "analyse", "analyze", "solve",
}
_CHITCHAT = {
    "hi", "hello", "hey", "yo", "hiya", "howdy", "sup", "hi there", "hello there",
    "thanks", "thank you", "thanks!", "thx", "ty", "cheers", "ok", "okay", "k",
    "cool", "nice", "great", "awesome", "good", "sure", "yes", "no", "yeah",
    "yep", "nope", "nah", "bye", "goodbye", "see you", "good morning",
    "good afternoon", "good evening", "good night", "how are you",
    "how are you?", "what's up", "whats up", "lol", "haha", "please", "sorry",
    "welcome", "np", "no problem", "got it", "understood",
}
_HEDGES = (
    "i think", "i believe", "i guess", "maybe", "probably", "possibly",
    "i'm not sure", "im not sure", "not sure", "might be", "could be",
    "i recall", "if i remember", "as far as i know",
)
_PREFERENCE_CUES = (
    "i like", "i love", "i prefer", "i enjoy", "i hate", "i dislike",
    "i use", "i work", "i live", "i study", "i'm learning", "im learning",
    "my favourite", "my favorite", "my name is", "i am ", "i'm ", "im ",
    "my birthday", "my email", "my phone", "my address", "i own", "i need",
    "i want", "i usually", "i always", "i never",
)

_WORD_RE = re.compile(r"[a-zA-Z']+")


def _words(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


def _looks_like_question(text: str) -> bool:
    stripped = text.strip()
    if "?" in stripped:
        return True
    words = _words(stripped)
    if not words:
        return False
    if words[0] in _WH or words[0] in _AUX:
        # "Where is X" / "Is X ..." — a leading wh-word or auxiliary.
        return True
    low = stripped.lower()
    return any(low.startswith(p) or f" {p} " in f" {low} " for p in _QUESTION_PHRASES)


def _looks_like_command(text: str) -> bool:
    words = _words(text)
    if not words:
        return False
    if words[0] in _COMMAND_VERBS:
        return True
    low = text.lower().strip()
    return any(low.startswith(v + " ") for v in _COMMAND_VERBS)


def _looks_like_chitchat(text: str) -> bool:
    low = text.lower().strip().strip("!.?,")
    if low in _CHITCHAT:
        return True
    words = _words(text)
    # Very short non-informative messages are treated as chit-chat.
    if len(words) <= 2 and low not in ("",):
        return True
    return False


def _is_hedged(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _HEDGES)


def _is_preference(text: str) -> bool:
    low = " " + text.lower() + " "
    return any(cue in low for cue in _PREFERENCE_CUES)


_IS_A_RE = re.compile(
    r"^(?P<s>.+?)\s+(?:is|are|was|were)\s+(?:a|an|the)?\s*(?P<o>.+?)[.!]?$",
    re.IGNORECASE,
)
_POSSESSIVE_RE = re.compile(
    r"^(?P<s>.+?)'s\s+(?P<p>[a-zA-Z]+)\s+(?:is|are|was|were)\s+(?P<o>.+?)[.!]?$",
    re.IGNORECASE,
)


def extract_triple(text: str):
    """Best-effort (subject, predicate, object) extraction. Never required."""
    m = _POSSESSIVE_RE.match(text.strip())
    if m:
        return m.group("s").strip(), m.group("p").strip(), m.group("o").strip()
    m = _IS_A_RE.match(text.strip())
    if m:
        return m.group("s").strip(), "is", m.group("o").strip()
    return None, None, None


class Curator:
    def __init__(self, config):
        self.config = config

    def evaluate(self, text: str, source: str = "user") -> CuratorResult:
        cfg = self.config
        raw = (text or "").strip()

        if not raw:
            return CuratorResult(REJECT_EMPTY, "empty message")
        if len(raw) < cfg.min_fact_chars:
            # Allow short but meaningful preferences ("I like tea" is long
            # enough; "hi" is caught by chit-chat below anyway).
            if _looks_like_chitchat(raw):
                return CuratorResult(REJECT_CHITCHAT, "greeting or filler")
            return CuratorResult(REJECT_TOO_SHORT, "below minimum length")
        if len(raw) > cfg.max_fact_chars:
            return CuratorResult(REJECT_TOO_LONG, "above maximum length")

        # Order matters: questions and commands before chit-chat, so that a
        # one-word question like "why?" is classified as a question.
        if _looks_like_question(raw):
            return CuratorResult(REJECT_QUESTION, "interrogative")
        if _looks_like_chitchat(raw):
            return CuratorResult(REJECT_CHITCHAT, "greeting or filler")
        if _looks_like_command(raw):
            return CuratorResult(REJECT_COMMAND, "imperative / request")

        # It is a statement: decide its shape and confidence.
        category = "fact"
        confidence = cfg.base_confidence
        if _is_hedged(raw):
            confidence = max(0.2, confidence - cfg.hedge_penalty)
        if _is_preference(raw):
            if not cfg.store_user_preferences:
                return CuratorResult(REJECT_CHITCHAT, "preferences disabled")
            category = "preference"
            confidence = min(cfg.max_confidence, confidence + 0.1)

        subject, predicate, obj = extract_triple(raw)
        if predicate == "is":
            category = "definition" if category == "fact" else category

        return CuratorResult(
            STORE,
            "declarative statement",
            content=raw,
            category=category,
            confidence=round(confidence, 3),
            subject=subject,
            predicate=predicate,
            object=obj,
        )
