"""Tera web app — a REST API plus a browser chat UI.

Run locally:
    python -m tera.webapp          # http://127.0.0.1:5000
    # or, for production:
    gunicorn -w 1 -k gthread --threads 4 tera.webapp:app

Endpoints
---------
    GET  /                 the chat page
    GET  /api/health       liveness + whether the LLM is offline or live
    GET  /api/stats        knowledge-base counters
    GET  /api/facts        active facts (optional ?limit=)
    POST /api/learn        {"text": "..."}          -> ingest one message
    POST /api/ask          {"question": "..."}      -> answer from the base
    POST /api/chat         {"message": "..."}       -> route a free-form message
"""

from __future__ import annotations

import os
import threading

from flask import Flask, jsonify, render_template, request

from .config import TeraConfig
from .engine import Tera

# Mongita is not guaranteed to be thread-safe, so serialise access to the
# knowledge base. Fine for the intended single-process deployment.
_LOCK = threading.Lock()


def create_app(config: TeraConfig | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates")
    cfg = config or TeraConfig()
    if os.environ.get("TERA_DB"):
        cfg.db_path = os.environ["TERA_DB"]
    tera = Tera(config=cfg)
    app.config["TERA"] = tera

    # ---------------------------------------------------------------- #
    # page
    # ---------------------------------------------------------------- #
    @app.get("/")
    def index():
        return render_template("index.html")

    # ---------------------------------------------------------------- #
    # api
    # ---------------------------------------------------------------- #
    @app.get("/api/health")
    def health():
        store_name = type(tera.store).__name__
        friendly = {
            "FactStore": "embedded (local file)",
            "MongoFactStore": "MongoDB",
            "RedisFactStore": "Redis",
        }.get(store_name, store_name)
        # A local file persists on a normal host but not on a serverless one.
        if store_name == "FactStore":
            persistent = not os.environ.get("VERCEL")
        else:
            persistent = True
        return jsonify({
            "status": "ok",
            "llm": tera.llm.name,
            "offline": tera.llm.name == "mock",
            "store": friendly,
            "persistent": persistent,
        })

    @app.get("/api/stats")
    def stats():
        with _LOCK:
            return jsonify(tera.stats())

    @app.get("/api/facts")
    def facts():
        limit = request.args.get("limit", default=100, type=int)
        with _LOCK:
            rows = tera.store.all_active(limit=limit)
        return jsonify([
            {
                "content": f.content,
                "category": f.category,
                "confidence": round(f.confidence, 3),
                "reinforcements": f.reinforcements,
            }
            for f in rows
        ])

    @app.post("/api/learn")
    def learn():
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text is required"}), 400
        with _LOCK:
            res = tera.learn(text)
            stats_now = tera.stats()
        return jsonify({
            "stored": res.stored,
            "decision": res.decision,
            "reason": res.reason,
            "action": res.action,
            "content": res.content,
            "stats": stats_now,
        })

    @app.post("/api/ask")
    def ask():
        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400
        with _LOCK:
            ans = tera.ask(question)
        return jsonify({
            "answer": ans.text,
            "grounded": ans.grounded,
            "facts": [f.content for f in ans.facts],
        })

    @app.post("/api/chat")
    def chat():
        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message is required"}), 400
        with _LOCK:
            reply = tera.chat(message)
            stats_now = tera.stats()
        payload = {
            "kind": reply.kind,
            "reply": reply.text,
            "stats": stats_now,
        }
        if reply.answer is not None:
            payload["answer"] = reply.answer.text
            payload["grounded"] = reply.answer.grounded
            payload["facts"] = [f.content for f in reply.answer.facts]
        if reply.ingest is not None:
            payload["action"] = reply.ingest.action
            payload["stored_content"] = reply.ingest.content
        return jsonify(payload)

    return app


# Module-level app for `gunicorn tera.webapp:app` and `flask run`.
app = create_app()


def main() -> None:
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
