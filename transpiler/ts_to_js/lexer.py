"""Regex lexer for the TypeScript subset.

Whitespace and comments are discarded. `>` is always emitted as a single-character
token: this is the classic fix for `Array<Array<number>>`, where a greedy `>>`
would otherwise swallow two generic closers. The expression parser re-joins
adjacent `>` tokens into `>>`, `>>>`, `>=` etc. when it is in operator position.
"""

from __future__ import annotations

from typing import List

from ..core import RegexLexer, Token, TranspileError

_RULES = [
    ("WS", r"\s+"),
    ("COMMENT", r"//[^\n]*|/\*[\s\S]*?\*/"),
    ("TEMPLATE", r"`(?:[^`\\]|\\[\s\S])*`"),
    ("STRING", r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'"),
    ("BADSTRING", r"[\"'`][\s\S]*"),
    ("NUMBER", r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?"),
    ("NAME", r"[A-Za-z_$][A-Za-z0-9_$]*"),
    ("OP", r"\.\.\.|=>|\?\?=|\?\?|\?\.(?!\d)|\*\*=|\*\*|===|!==|==|!=|<=|<<=|<<|&&=|\|\|=|&&|\|\||\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|[-+*/%<=!&|^~?:;,.(){}\[\]>@#]"),
]

_LEXER = RegexLexer(_RULES, skip={"WS", "COMMENT"})


def tokenize(source: str) -> List[Token]:
    tokens = _LEXER.tokenize(source.replace("\r\n", "\n"))
    for tok in tokens:
        if tok.kind == "BADSTRING":
            raise TranspileError("Unterminated string or template literal", tok.line, tok.col)
    return tokens
