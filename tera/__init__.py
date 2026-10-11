"""
Tera — a knowledge-base-first AI chatbot that grows permanently as it is used.

Tera's architecture is built around its knowledge base, not around the LLM.
The LLM is a pluggable, *optional* component: with no API key and no model
installed, Tera still runs, still learns, and still answers from what it has
stored. The knowledge base is the source of truth and the thing that gets
stronger with every piece of information it is given.

Core ideas
----------
1. Curate before storing. Every incoming message is classified first. Facts
   are stored; questions, greetings, commands and small talk are not.
2. Never lose knowledge. Facts are de-duplicated, reinforced when repeated,
   and *versioned* rather than overwritten when corrected.
3. Answer from the base first. The LLM only ever sees facts retrieved from
   the knowledge base, and is told to answer from them alone.

Quick start
-----------
    from tera import Tera

    tera = Tera()                       # zero setup: embedded document DB + offline mode
    tera.learn("The Eiffel Tower is in Paris.")
    print(tera.ask("Where is the Eiffel Tower?").text)

See README.md for the full guide.
"""

from .config import TeraConfig
from .engine import Tera, Answer, IngestResult

__all__ = ["Tera", "TeraConfig", "Answer", "IngestResult"]
__version__ = "0.1.0"
