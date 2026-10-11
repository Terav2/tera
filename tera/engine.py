"""The Tera engine — the public face of the system.

Tera's centre of gravity is the knowledge base. The engine wires together the
curator (what to keep), the consolidator (how to keep it well) and the
retriever (how to use it), with an optional LLM at the very end for phrasing
answers. Remove the LLM and Tera still learns and still answers.

Public surface
--------------
    learn(text)  -> store a piece of information (returns what happened)
    ask(q)       -> answer from the knowledge base
    chat(text)   -> route a free-form message: store it, answer it, or reply
    stats()      -> counters describing the growing base
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .config import TeraConfig
from .llm import build_llm
from .kb import Candidate, Curator, Retriever, Consolidator, open_store
from .kb import curator as curator_mod


@dataclass
class IngestResult:
    stored: bool
    decision: str
    reason: str = ""
    action: Optional[str] = None      # added | reinforced | superseded
    fact_id: Optional[str] = None
    content: str = ""
    extra_facts: int = 0

    def __bool__(self) -> bool:
        return self.stored


@dataclass
class Answer:
    text: str
    question: str = ""
    facts: List = field(default_factory=list)
    retrieved: List = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return bool(self.facts)


@dataclass
class ChatReply:
    kind: str                          # answered | stored | chitchat | refused
    text: str
    answer: Optional[Answer] = None
    ingest: Optional[IngestResult] = None


class Tera:
    def __init__(self, config: Optional[TeraConfig] = None, llm=None, store=None):
        self.config = config or TeraConfig()
        self.store = store or open_store(self.config)
        self.llm = llm or build_llm(self.config.llm_backend, self.config.llm_model or None)
        self.curator = Curator(self.config)
        self.retriever = Retriever(self.store, self.config)
        self.consolidator = Consolidator(self.store, self.config)

    # ------------------------------------------------------------------ #
    # learning
    # ------------------------------------------------------------------ #
    def learn(self, text: str, source: str = "user") -> IngestResult:
        """Offer a message to the knowledge base. Stores it only if it is
        durable information; rejects questions, commands and chit-chat."""
        verdict = self.curator.evaluate(text, source=source)

        if not verdict.should_store:
            self.store.meta_inc("rejected")
            return IngestResult(False, verdict.decision, verdict.reason)

        candidates = self._candidates_for(text, verdict, source)
        results = [self.consolidator.consolidate(c) for c in candidates]
        first = results[0]
        return IngestResult(
            stored=True,
            decision=curator_mod.STORE,
            reason=verdict.reason,
            action=first["action"],
            fact_id=first["id"],
            content=first["content"],
            extra_facts=max(0, len(results) - 1),
        )

    def _candidates_for(self, text: str, verdict, source: str) -> List[Candidate]:
        """Turn a stored message into one or more fact candidates.

        The rule-based curator always produces one. If a real LLM is attached,
        its structured extraction is preferred (it can split a paragraph into
        several facts); on any failure we fall back to the curator's candidate.
        """
        try:
            extracted = self.llm.extract(text)
        except Exception:
            extracted = []

        cands: List[Candidate] = []
        for item in extracted:
            content = (item.get("content") or "").strip()
            if len(content) < self.config.min_fact_chars:
                continue
            cands.append(Candidate(
                content=content,
                subject=item.get("subject"),
                predicate=item.get("predicate"),
                object=item.get("object"),
                category=verdict.category,
                confidence=verdict.confidence,
                source=source,
            ))

        if not cands:
            cands.append(Candidate(
                content=verdict.content,
                subject=verdict.subject,
                predicate=verdict.predicate,
                object=verdict.object,
                category=verdict.category,
                confidence=verdict.confidence,
                source=source,
            ))
        return cands

    # ------------------------------------------------------------------ #
    # answering
    # ------------------------------------------------------------------ #
    def ask(self, question: str, top_k: Optional[int] = None) -> Answer:
        retrieved = self.retriever.retrieve(question, top_k=top_k)
        facts = [r["fact"] for r in retrieved if r["score"] >= self.config.min_score]
        fact_texts = [f.content for f in facts]
        text = self.llm.answer(question, fact_texts)
        self.store.meta_inc("queries")
        return Answer(text=text, question=question, facts=facts, retrieved=retrieved)

    # ------------------------------------------------------------------ #
    # one entry point for free-form chat
    # ------------------------------------------------------------------ #
    def chat(self, text: str) -> ChatReply:
        verdict = self.curator.evaluate(text)

        if verdict.decision == curator_mod.REJECT_QUESTION:
            ans = self.ask(text)
            return ChatReply("answered", ans.text, answer=ans)

        if verdict.decision == curator_mod.STORE:
            res = self.learn(text)
            if res.action == "reinforced":
                msg = "I already knew that — I've noted it again, so I'm now more confident."
            elif res.action == "superseded":
                msg = "Thanks — I've updated what I had stored with this newer information."
            else:
                msg = "Got it. I've stored that permanently."
            return ChatReply("stored", msg, ingest=res)

        if verdict.decision == curator_mod.REJECT_CHITCHAT:
            return ChatReply(
                "chitchat",
                "Hi! Tell me a fact and I'll remember it, or ask me something "
                "and I'll answer from what I've learned.",
            )

        # commands and everything else
        return ChatReply(
            "refused",
            "I only keep durable information in my knowledge base — I didn't "
            "store that. Give me a fact, or ask me a question.",
        )

    # ------------------------------------------------------------------ #
    def stats(self) -> dict:
        return self.store.stats()

    def close(self) -> None:
        self.store.close()

    # context-manager sugar
    def __enter__(self) -> "Tera":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
