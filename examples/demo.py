"""Interactive demo of Tera running fully offline (no API key, no server).

Run:  python examples/demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tera import Tera, TeraConfig


def main():
    cfg = TeraConfig(db_path=":memory:")   # throwaway base for the demo
    with Tera(config=cfg) as tera:
        print("=" * 68)
        print("Tera demo — offline mode (embedded document DB, no API key)")
        print("=" * 68)

        print("\n-- Teaching Tera some facts --")
        facts = [
            "The Eiffel Tower is located in Paris.",
            "The Eiffel Tower was completed in 1889.",
            "Paris is the capital of France.",
            "Water boils at 100 degrees Celsius at sea level.",
            "ISRO is the Indian Space Research Organisation.",
            "ISRO was founded in 1969.",
        ]
        for f in facts:
            res = tera.learn(f)
            print(f"  + {f}   -> {res.action}")

        print("\n-- Things that should NOT be stored --")
        rejects = [
            "What is the capital of France?",
            "Can you write me a poem?",
            "hi",
            "thanks!",
            "Where is the Eiffel Tower?",
        ]
        for r in rejects:
            res = tera.learn(r)
            print(f"  x {r!r:45} -> {res.decision}")

        print("\n-- Re-stating a fact strengthens it (no duplicate) --")
        tera.learn("The Eiffel Tower is located in Paris.")
        for fact in tera.store.all_active():
            if "Eiffel" in fact.content and "Paris" in fact.content:
                print(f"  confidence now {fact.confidence:.2f}, "
                      f"reinforced {fact.reinforcements}x")

        print("\n-- Correcting a fact versions the old one --")
        res = tera.learn("The Eiffel Tower is located in Berlin.")
        print(f"  -> {res.action} (old fact kept as history, marked superseded)")

        print("\n-- Asking questions (answered only from the knowledge base) --")
        for q in [
            "Where is the Eiffel Tower?",
            "When was ISRO founded?",
            "What is the capital of France?",
            "Who won the 2050 World Cup?",
        ]:
            ans = tera.ask(q)
            grounded = "grounded" if ans.grounded else "NOT in base"
            print(f"\n  Q: {q}\n  A: {ans.text}\n     [{grounded}, {len(ans.facts)} fact(s)]")

        print("\n-- Knowledge base statistics --")
        for k, v in tera.stats().items():
            print(f"  {k:14} {v}")
        print()


if __name__ == "__main__":
    main()
