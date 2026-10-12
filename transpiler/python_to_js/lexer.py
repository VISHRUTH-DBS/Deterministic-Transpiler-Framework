"""Indentation-aware lexer for the Python subset.

Two cooperating layers:

1. A regex layer (`RegexLexer`) that tokenizes the content of one physical line.
2. A line-oriented state machine that owns the *indentation stack* and bracket
   depth, and converts leading whitespace into synthetic INDENT / DEDENT tokens.

The state machine is what turns Python's significant whitespace into explicit
block delimiters the parser can treat like `{` and `}`.
"""

from __future__ import annotations

from typing import List

from ..core import RegexLexer, Token, TranspileError

KEYWORDS = frozenset({
    "and", "or", "not", "if", "elif", "else", "while", "for", "in", "def",
    "return", "break", "continue", "pass", "True", "False", "None",
})

_RULES = [
    ("WS", r"[ \t]+"),
    ("COMMENT", r"\#[^\n]*"),
    ("NUMBER", r"(?:\d+\.\d+|\d+)(?:[eE][+-]?\d+)?"),
    ("STRING", r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'"),
    ("BADSTRING", r"[\"'][^\n]*"),
    ("NAME", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("OP", r"\*\*=|//=|\*\*|//|==|!=|<=|>=|\+=|-=|\*=|/=|%=|[-+*/%<>=(),:\[\].]"),
]

_LINE_LEXER = RegexLexer(_RULES, skip={"WS", "COMMENT"})
_OPEN = {"(", "["}
_CLOSE = {")", "]"}


def tokenize(source: str) -> List[Token]:
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    tokens: List[Token] = []
    indents = [0]
    depth = 0

    for lineno, raw in enumerate(source.split("\n"), start=1):
        if depth == 0:
            stripped = raw.lstrip(" ")
            if stripped == "" or stripped.startswith("#"):
                continue  # blank and comment-only lines never affect indentation
            leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
            if "\t" in leading:
                raise TranspileError("Tabs are not allowed for indentation", lineno, 1)
            width = len(raw) - len(stripped)
            if width > indents[-1]:
                indents.append(width)
                tokens.append(Token("INDENT", "", lineno, 1))
            else:
                while width < indents[-1]:
                    indents.pop()
                    tokens.append(Token("DEDENT", "", lineno, 1))
                if width != indents[-1]:
                    raise TranspileError("Inconsistent dedent", lineno, 1)

        for tok in _LINE_LEXER.tokenize(raw, lineno, 1):
            if tok.kind == "BADSTRING":
                raise TranspileError("Unterminated string literal", tok.line, tok.col)
            if tok.kind == "NAME" and tok.value in KEYWORDS:
                tok = Token("KEYWORD", tok.value, tok.line, tok.col)
            elif tok.kind == "OP":
                if tok.value in _OPEN:
                    depth += 1
                elif tok.value in _CLOSE:
                    depth -= 1
                    if depth < 0:
                        raise TranspileError(f"Unmatched {tok.value!r}", tok.line, tok.col)
            tokens.append(tok)

        if depth == 0:
            tokens.append(Token("NEWLINE", "", lineno, len(raw) + 1))

    if depth > 0:
        raise TranspileError("Unclosed bracket at end of input", len(source.split("\n")), 1)
    last_line = source.count("\n") + 1
    while len(indents) > 1:
        indents.pop()
        tokens.append(Token("DEDENT", "", last_line, 1))
    tokens.append(Token("EOF", "", last_line, 1))
    return tokens
