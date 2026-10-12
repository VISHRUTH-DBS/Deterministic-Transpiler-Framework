"""Transpiler engine: a registry of translation pairs plus a command-line front end.

Each pair is just `str -> str`, built from its own lexer, parser and generator.
Registering a new pair is one `Pair(...)` entry; nothing else needs to change.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import json_to_yaml, md_to_html, python_to_js, ts_to_js
from .core import TranspileError


@dataclass(frozen=True)
class Pair:
    key: str
    source: str
    target: str
    description: str
    transpile: Callable[[str], str]


PAIRS: Dict[str, Pair] = {
    p.key: p
    for p in (
        Pair("py2js", "Python", "JavaScript",
             "indentation-scoped blocks -> brace-delimited blocks", python_to_js.transpile),
        Pair("ts2js", "TypeScript", "JavaScript",
             "type erasure: strip type-level nodes from the AST", ts_to_js.transpile),
        Pair("md2html", "Markdown", "HTML",
             "linear block/inline markers -> nested tags", md_to_html.transpile),
        Pair("json2yaml", "JSON", "YAML",
             "bracket/comma structure -> indentation", json_to_yaml.transpile),
    )
}


def transpile(pair: str, source: str) -> str:
    try:
        return PAIRS[pair].transpile(source)
    except KeyError:
        raise ValueError(f"Unknown pair {pair!r}; choose from {', '.join(PAIRS)}") from None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="transpiler",
        description="Deterministic source-to-source transpiler (no ML, no network).",
    )
    parser.add_argument("pair", nargs="?", choices=sorted(PAIRS), help="translation pair")
    parser.add_argument("input", nargs="?", default="-", help="input file, or '-' for stdin")
    parser.add_argument("-o", "--output", help="output file (default: stdout)")
    parser.add_argument("--list", action="store_true", help="list available pairs and exit")
    args = parser.parse_args(argv)

    if args.list or args.pair is None:
        for pair in PAIRS.values():
            print(f"{pair.key:<10} {pair.source} -> {pair.target}: {pair.description}")
        return 0 if args.list else 2

    try:
        if args.input == "-":
            source = sys.stdin.read()
        else:
            with open(args.input, encoding="utf-8") as handle:
                source = handle.read()
        result = transpile(args.pair, source)
    except TranspileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(result)
    else:
        sys.stdout.write(result)
    return 0
