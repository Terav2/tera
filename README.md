# Tera

A chatbot whose intelligence lives in its **knowledge base**, not in a language
model. Give Tera information and it keeps it — permanently, de-duplicated, and
with corrections versioned rather than lost. Ask it something and it answers
only from what it has actually stored, and says so honestly when it doesn't
know yet. The more it is used, the more it knows.

Tera ships with a **web chat UI** and a **REST API**, and runs with **zero
setup**: one `pip install`, no database server, no API key. A language model is
*optional* and *pluggable* — swap in OpenAI, Claude or a local Ollama model to
improve phrasing, or run entirely offline. Nothing in the learning or answering
logic depends on it.

---

## Why it's built this way

Most "chatbots with memory" bolt a vector store onto a model and hope. Tera
inverts that: the knowledge base is the core system, and the model is a thin
presentation layer on top of it.

That inversion buys three properties:

1. **It never bloats.** Every message is *curated* before it is stored. Facts
   go in; questions, greetings, commands and small talk do not.
2. **It never forgets or duplicates.** Repeating a fact raises its confidence
   instead of adding a row. Correcting a fact keeps the old one as history.
3. **It works without a model.** With no key and no network, Tera still learns,
   still retrieves, and still answers. The model only ever sees facts pulled
   from the base, and is instructed to answer from those alone.

## The pipeline

```
                    ┌──────────────────────────────────────────────┐
   user message ──▶ │ CURATOR   is this durable information?       │
                    │  • question?   -> reject                     │
                    │  • command?    -> reject                     │
                    │  • chit-chat?  -> reject                     │
                    │  • statement?  -> keep, with a confidence    │
                    └───────────────┬──────────────────────────────┘
                                    │ (keep)
                                    ▼
                    ┌──────────────────────────────────────────────┐
                    │ CONSOLIDATOR   strengthen, don't just grow   │
                    │  • exact repeat   -> reinforce (+confidence) │
                    │  • same relation  -> supersede (version old) │
                    │  • new knowledge  -> add + index             │
                    └───────────────┬──────────────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────────────┐
                    │ STORE   document DB (embedded) + inverted    │
                    │         index  (no SQL, no server)           │
                    └───────────────┬──────────────────────────────┘
                                    │
   user question ──▶ RETRIEVER ─────┘   BM25 + confidence + reinforcement
                       │
                       ▼
                    LLM (optional) — phrases an answer from the retrieved facts
```

## Storage: no SQL, nothing to set up

The knowledge base is a **document database** ([Mongita](https://github.com/scottrogowski/mongita)),
a MongoDB-style store that runs *embedded in the process*. There is no server
to start and no daemon to manage; the whole base is a folder on disk (or
`:memory:` for tests).

Because Mongita's query language is a deliberate subset of Mongo's, Tera keeps
two things in application code instead of the database:

- an **inverted index** (a `postings` collection: token → fact ids) so retrieval
  is fast without a full scan; and
- **uniqueness** on a content hash, enforced by lookup before insert.

No SQL anywhere.

There are **two interchangeable backends**, chosen automatically: the embedded
Mongita store (the default — zero setup) and a **MongoDB** store, used the
moment a `TERA_MONGODB_URI` connection string is present. The MongoDB backend
exists for stateless hosts such as Vercel, where there is no local disk to keep
the base on. Both expose the identical interface, so nothing else in Tera
changes.

## Install & run

```bash
pip install -r requirements.txt

# Web app (front end + API):
python -m tera.webapp            # then open http://127.0.0.1:5000

# Command line:
python examples/demo.py          # a full offline demo, no key needed
python -m tera                   # interactive chat
python -m tera --learn "ISRO was founded in 1969."
python -m tera --ask   "When was ISRO founded?"
python -m tera --stats
```

## Web app

`python -m tera.webapp` starts a Flask server that serves a single-page chat UI
at `/` and a JSON API underneath it. In the UI you type plain text: give Tera a
fact and it stores it, ask a question and it answers from what it has learned.
Each reply carries a badge saying whether it was **stored**, **answered from the
knowledge base**, or **not stored** — and the sidebar shows the live counters
and everything the base currently holds.

The API is small and easy to integrate:

| Method | Path          | Body / Query                 | Returns |
|--------|---------------|------------------------------|---------|
| GET    | `/`           | —                            | the chat page |
| GET    | `/api/health` | —                            | status + whether offline |
| GET    | `/api/stats`  | —                            | knowledge-base counters |
| GET    | `/api/facts`  | `?limit=`                    | active facts |
| POST   | `/api/learn`  | `{"text": "..."}`            | stored / decision / action |
| POST   | `/api/ask`    | `{"question": "..."}`        | answer + grounding |
| POST   | `/api/chat`   | `{"message": "..."}`         | routed reply (store or answer) |

```bash
curl -X POST localhost:5000/api/learn -H 'Content-Type: application/json' \
     -d '{"text":"ISRO was founded in 1969."}'
curl -X POST localhost:5000/api/ask   -H 'Content-Type: application/json' \
     -d '{"question":"When was ISRO founded?"}'
```

### In your own code

```python
from tera import Tera

tera = Tera()                                   # embedded DB + offline mode
tera.learn("The Eiffel Tower is located in Paris.")
tera.learn("What is the capital of France?")    # rejected: it's a question
print(tera.ask("Where is the Eiffel Tower?").text)

tera.chat("Water boils at 100 degrees Celsius.")  # -> stored
tera.chat("Where does water boil?")               # -> answered from the base
```

### Turning on a model (optional)

```bash
export TERA_LLM=openai      OPENAI_API_KEY=sk-...      # or:
export TERA_LLM=anthropic   ANTHROPIC_API_KEY=sk-...   # or:
export TERA_LLM=ollama      TERA_LLM_MODEL=llama3.1     # local, no key
```

If the chosen backend isn't usable, Tera silently falls back to offline mode
rather than failing — the knowledge base keeps working either way.

## Deploying

The repo is set up to deploy as a normal Python web service. `Procfile`,
`render.yaml` and `Dockerfile` are included.

**Vercel** (needs an external database): deploys as a serverless function via
`api/index.py` + `vercel.json`. Vercel's filesystem is ephemeral, so the
knowledge base must live in MongoDB. Create a free **MongoDB Atlas** cluster,
copy its connection string, then in Vercel *Add New → Project*, import this
repo, and add an Environment Variable `TERA_MONGODB_URI` = your connection
string. Tera picks up Atlas automatically. (Without that variable, Tera still
runs on Vercel but forgets everything between visits.)

**Render** (simplest): push to GitHub, then *New + → Blueprint*, pick the repo,
and Render reads `render.yaml`. That blueprint attaches a 1 GB persistent disk
at `/var/data` and points `TERA_DB` there, so the knowledge base survives
redeploys.

**Railway / Fly.io / Cloud Run**: they detect the `Dockerfile` (or the
`Procfile`) automatically. Set `TERA_DB` to a path on a mounted volume if you
want the base to persist.

**Any host**: the production command is

```bash
gunicorn -w 1 -k gthread --threads 4 -b 0.0.0.0:$PORT wsgi:app
```

> On the embedded store, run a **single** worker — one process owns the file.
> With `TERA_MONGODB_URI` set the base is shared, so you can scale workers and
> instances freely.

## What gets stored, and what doesn't

| Message                                  | Decision            |
|------------------------------------------|---------------------|
| "The Eiffel Tower is located in Paris."  | **stored** (fact)   |
| "I prefer dark mode."                    | **stored** (preference) |
| "What is the capital of France?"         | rejected — question |
| "Can you write me a poem?"               | rejected — command  |
| "hi", "thanks!", "ok"                    | rejected — chit-chat |

Tuning lives in `TeraConfig` (`tera/config.py`): minimum length, confidence
floor, hedge penalty, reinforcement boost, `top_k`, and whether to keep the
user's own preferences.

## Honest limits

- The rule-based curator and the triple extractor are heuristics, not NLP.
  They handle short declarative sentences well; long, compound or deeply nested
  statements are stored but may not be split into atomic facts. Attaching a real
  LLM (its `extract` method) sharpens this.
- Contradiction detection compares a *relation frame* (predicate + leading word
  of the object). It reliably catches "located in X → located in Y", and
  single-word conflicts, but can miss subtler conflicts a model would catch.
- Retrieval is lexical (BM25-style) plus knowledge-base signals. It has no
  semantic embeddings, which is a deliberate trade for zero setup. Adding an
  embedding step behind `Retriever` is a clean extension point.
- The web app has no authentication. Add auth before exposing it publicly with
  anything sensitive in the knowledge base.

## Layout

```
tera/
  config.py            TeraConfig
  engine.py            Tera: learn / ask / chat / stats
  webapp.py            Flask app: REST API + serves the chat page
  templates/
    index.html         the single-page chat UI (self-contained)
  cli.py, __main__.py  command-line front end
  llm/                 pluggable models: mock (offline), openai, anthropic, ollama
  kb/
    store.py           embedded document store + inverted index
    mongo_store.py     MongoDB-backed store (for Vercel / stateless hosts)
    curator.py         decides what is worth keeping
    consolidator.py    reinforce / supersede / add
    retriever.py       BM25-style ranking blended with confidence
    text.py            normalise, hash, tokenise
wsgi.py                production entry point (gunicorn / Render / Railway)
api/index.py           Vercel serverless entry point
vercel.json            Vercel config
Procfile, render.yaml, Dockerfile   deployment
examples/demo.py       offline end-to-end demo
tests/                 test_tera.py (core), test_web.py (API + page)
```

Run the tests with `pytest -q`, or directly:
`python tests/test_tera.py`, `python tests/test_web.py` and
`python tests/test_mongo.py`.
