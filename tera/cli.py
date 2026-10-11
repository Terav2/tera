"""A small command-line front end for Tera.

Plain text is routed automatically: give it a fact and it stores it, ask it a
question and it answers from the knowledge base. Slash-commands give explicit
control.

    python -m tera                      # interactive chat
    python -m tera --learn "..."        # store one fact
    python -m tera --ask "..."          # ask one question
    python -m tera --stats              # show counters
"""

from __future__ import annotations

import argparse
import sys

from .config import TeraConfig
from .engine import Tera

BANNER = (
    "Tera — knowledge-base-first assistant.\n"
    "Type a fact and I'll remember it; ask a question and I'll answer from what I know.\n"
    "Commands: /learn <text>  /ask <q>  /list  /stats  /quit\n"
)


def _print_stats(tera: Tera) -> None:
    s = tera.stats()
    print(
        f"active facts: {s['active_facts']} | total ever: {s['total_facts']} | "
        f"vocabulary: {s['vocabulary']}\n"
        f"added: {s['added']} | reinforced: {s['reinforced']} | "
        f"superseded: {s['superseded']} | rejected: {s['rejected']} | "
        f"queries: {s['queries']}"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tera", description="Tera chatbot")
    parser.add_argument("--db", default=None, help="knowledge base folder")
    parser.add_argument("--llm", default=None, help="mock | openai | anthropic | ollama")
    parser.add_argument("--model", default=None, help="model name for the chosen LLM")
    parser.add_argument("--learn", default=None, help="store a fact and exit")
    parser.add_argument("--ask", default=None, help="ask a question and exit")
    parser.add_argument("--stats", action="store_true", help="show counters and exit")
    args = parser.parse_args(argv)

    cfg = TeraConfig()
    if args.db:
        cfg.db_path = args.db
    if args.llm:
        cfg.llm_backend = args.llm
    if args.model:
        cfg.llm_model = args.model

    with Tera(config=cfg) as tera:
        if args.learn:
            res = tera.learn(args.learn)
            print("stored" if res.stored else f"not stored ({res.reason})")
            return 0
        if args.ask:
            print(tera.ask(args.ask).text)
            return 0
        if args.stats:
            _print_stats(tera)
            return 0

        print(BANNER)
        while True:
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                break
            if line == "/stats":
                _print_stats(tera)
                continue
            if line == "/list":
                for f in tera.store.all_active(limit=50):
                    print(f"  [{f.confidence:.2f}] {f.content}")
                continue
            if line.startswith("/learn "):
                res = tera.learn(line[len("/learn "):])
                print("tera>", "stored" if res.stored else f"not stored ({res.reason})")
                continue
            if line.startswith("/ask "):
                print("tera>", tera.ask(line[len("/ask "):]).text)
                continue

            reply = tera.chat(line)
            print("tera>", reply.text)
        return 0


if __name__ == "__main__":
    sys.exit(main())
