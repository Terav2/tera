"""Build and query Tera's own web index from the command line.

    python -m tera.websearch crawl --seeds https://en.wikipedia.org/wiki/ISRO \
        --depth 1 --max-pages 25 --out web_index.json
    python -m tera.websearch query "when was ISRO founded" --index web_index.json
"""

from __future__ import annotations

import argparse
import sys

from .engine import WebSearch


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tera.websearch", description="Tera Search")
    sub = parser.add_subparsers(dest="cmd", required=True)

    crawl = sub.add_parser("crawl", help="crawl seed pages into an index")
    crawl.add_argument("--seeds", nargs="+", required=True)
    crawl.add_argument("--depth", type=int, default=1)
    crawl.add_argument("--max-pages", type=int, default=40)
    crawl.add_argument("--out", default="web_index.json")
    crawl.add_argument("--all-domains", action="store_true",
                       help="follow links off the seed domains too")
    crawl.add_argument("--delay", type=float, default=0.0)

    query = sub.add_parser("query", help="search an index")
    query.add_argument("text")
    query.add_argument("--index", default="web_index.json")
    query.add_argument("-k", type=int, default=5)

    stats = sub.add_parser("stats", help="show index size")
    stats.add_argument("--index", default="web_index.json")

    args = parser.parse_args(argv)

    if args.cmd == "crawl":
        ws = WebSearch(path=None)
        pages = ws.crawl(
            args.seeds, depth=args.depth, max_pages=args.max_pages,
            same_domain=not args.all_domains, delay=args.delay,
        )
        out = ws.save(args.out)
        print(f"crawled {pages} pages -> {out}")
        return 0

    if args.cmd == "query":
        ws = WebSearch(args.index)
        results = ws.search(args.text, k=args.k)
        if not results:
            print("no results")
            return 1
        for i, r in enumerate(results, 1):
            print(f"{i}. {r['title']}  [{r['score']}]")
            print(f"   {r['url']}")
            print(f"   {r['snippet']}\n")
        return 0

    if args.cmd == "stats":
        ws = WebSearch(args.index)
        for k, v in ws.stats().items():
            print(f"{k:12} {v}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
