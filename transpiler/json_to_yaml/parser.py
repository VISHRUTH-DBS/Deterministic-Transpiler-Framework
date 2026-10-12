"""Recursive-descent JSON parser (grammar: value := object | array | scalar)."""

from __future__ import annotations

from typing import List, Tuple

from ..core import Token, TokenStream, TranspileError
from . import json_ast as ast
from .lexer import tokenize

MAX_DEPTH = 200  # stay well inside Python's recursion limit

_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def decode_string(literal: str) -> str:
    """Decode a quoted JSON string literal, combining UTF-16 surrogate pairs."""
    body = literal[1:-1]
    out: List[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        esc = body[i + 1]
        if esc != "u":
            out.append(_SIMPLE_ESCAPES[esc])
            i += 2
            continue
        code = int(body[i + 2: i + 6], 16)
        i += 6
        if 0xD800 <= code <= 0xDBFF and body[i: i + 2] == "\\u":
            low = int(body[i + 2: i + 6], 16)
            if 0xDC00 <= low <= 0xDFFF:
                code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                i += 6
        out.append(chr(code))
    return "".join(out)


class Parser:
    def __init__(self, tokens: List[Token]) -> None:
        self.ts = TokenStream(tokens)

    def parse_document(self) -> ast.JsonValue:
        value = self.value(0)
        tok = self.ts.peek()
        if tok.kind != "EOF":
            raise TranspileError(f"Unexpected trailing {tok.kind} {tok.value!r}", tok.line, tok.col)
        return value

    def value(self, depth: int) -> ast.JsonValue:
        if depth > MAX_DEPTH:
            tok = self.ts.peek()
            raise TranspileError("Document nests too deeply", tok.line, tok.col)
        tok = self.ts.next()
        kind = tok.kind
        if kind == "LBRACE":
            return self._object(depth)
        if kind == "LBRACKET":
            return self._array(depth)
        if kind == "STRING":
            return ast.JsonString(decode_string(tok.value))
        if kind == "NUMBER":
            return ast.JsonNumber(tok.value)
        if kind == "TRUE":
            return ast.JsonBool(True)
        if kind == "FALSE":
            return ast.JsonBool(False)
        if kind == "NULL":
            return ast.JsonNull()
        found = f"{kind} {tok.value!r}" if tok.value else "end of input"
        raise TranspileError(f"Unexpected {found}; expected a JSON value", tok.line, tok.col)

    def _object(self, depth: int) -> ast.JsonObject:
        members: List[Tuple[str, ast.JsonValue]] = []
        seen = set()
        if self.ts.accept("RBRACE"):
            return ast.JsonObject(())
        while True:
            key_tok = self.ts.expect("STRING")
            key = decode_string(key_tok.value)
            if key in seen:
                raise TranspileError(f"Duplicate key {key!r} cannot be represented in YAML",
                                     key_tok.line, key_tok.col)
            seen.add(key)
            self.ts.expect("COLON")
            members.append((key, self.value(depth + 1)))
            if self.ts.accept("COMMA"):
                continue
            self.ts.expect("RBRACE")
            return ast.JsonObject(tuple(members))

    def _array(self, depth: int) -> ast.JsonArray:
        items: List[ast.JsonValue] = []
        if self.ts.accept("RBRACKET"):
            return ast.JsonArray(())
        while True:
            items.append(self.value(depth + 1))
            if self.ts.accept("COMMA"):
                continue
            self.ts.expect("RBRACKET")
            return ast.JsonArray(tuple(items))


def parse(source: str) -> ast.JsonValue:
    return Parser(tokenize(source)).parse_document()
