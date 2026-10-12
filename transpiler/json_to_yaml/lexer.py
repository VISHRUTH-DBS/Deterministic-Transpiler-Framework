"""Strict RFC 8259 lexer: no comments, no trailing commas, no single quotes."""

from __future__ import annotations

from typing import List

from ..core import RegexLexer, Token, TranspileError

_RULES = [
    ("WS", r"[ \t\r\n]+"),
    ("LBRACE", r"\{"),
    ("RBRACE", r"\}"),
    ("LBRACKET", r"\["),
    ("RBRACKET", r"\]"),
    ("COLON", r":"),
    ("COMMA", r","),
    ("STRING", r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'),
    ("NUMBER", r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?"),
    ("TRUE", r"true(?![A-Za-z0-9_])"),
    ("FALSE", r"false(?![A-Za-z0-9_])"),
    ("NULL", r"null(?![A-Za-z0-9_])"),
    ("BADSTRING", r'"'),
]

_LEXER = RegexLexer(_RULES, skip={"WS"})


def tokenize(source: str) -> List[Token]:
    tokens = _LEXER.tokenize(source)
    for tok in tokens:
        if tok.kind == "BADSTRING":
            raise TranspileError("Unterminated or invalid string literal", tok.line, tok.col)
    return tokens
