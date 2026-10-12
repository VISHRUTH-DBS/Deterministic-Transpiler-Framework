"""Shared compiler infrastructure: tokens, regex lexer, token stream, writer, errors.

Everything here is deterministic and dependency-free (standard library only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


class TranspileError(Exception):
    """Raised for any lexical, syntactic, or semantic error in the source."""

    def __init__(self, message: str, line: int = 0, col: int = 0) -> None:
        self.message = message
        self.line = line
        self.col = col
        location = f" (line {line}, col {col})" if line else ""
        super().__init__(f"{message}{location}")


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    col: int

    def __repr__(self) -> str:  # compact form helps when debugging token streams
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


class RegexLexer:
    """Longest-rule-order lexer built from an ordered list of (kind, regex).

    Rules are tried in the order given (first match wins), compiled into a
    single alternation of named groups so scanning is one linear pass.
    Kinds listed in `skip` are consumed but not emitted. Newlines inside any
    matched lexeme advance the line counter correctly.
    """

    def __init__(self, rules: Sequence[Tuple[str, str]], skip: Iterable[str] = ()) -> None:
        self._skip = frozenset(skip)
        self._kinds = [kind for kind, _ in rules]
        if len(set(self._kinds)) != len(self._kinds):
            raise ValueError("duplicate token kind in lexer rules")
        pattern = "|".join(f"(?P<{kind}>{regex})" for kind, regex in rules)
        self._master = re.compile(pattern)

    def tokenize(self, text: str, line: int = 1, col: int = 1) -> List[Token]:
        tokens: List[Token] = []
        pos = 0
        end = len(text)
        while pos < end:
            match = self._master.match(text, pos)
            if match is None or match.end() == pos:
                raise TranspileError(f"Unexpected character {text[pos]!r}", line, col)
            kind = match.lastgroup
            assert kind is not None
            lexeme = match.group()
            if kind not in self._skip:
                tokens.append(Token(kind, lexeme, line, col))
            newlines = lexeme.count("\n")
            if newlines:
                line += newlines
                col = len(lexeme) - lexeme.rfind("\n")
            else:
                col += len(lexeme)
            pos = match.end()
        return tokens


class TokenStream:
    """Cursor over a token list with the usual recursive-descent helpers."""

    def __init__(self, tokens: Sequence[Token], eof_kind: str = "EOF") -> None:
        self._tokens = list(tokens)
        self._pos = 0
        last = self._tokens[-1] if self._tokens else Token(eof_kind, "", 1, 1)
        self._eof = Token(eof_kind, "", last.line, last.col)

    def peek(self, offset: int = 0) -> Token:
        index = self._pos + offset
        return self._tokens[index] if index < len(self._tokens) else self._eof

    def next(self) -> Token:
        token = self.peek()
        if self._pos < len(self._tokens):
            self._pos += 1
        return token

    def at(self, kind: str, value: Optional[str] = None) -> bool:
        token = self.peek()
        return token.kind == kind and (value is None or token.value == value)

    def accept(self, kind: str, value: Optional[str] = None) -> Optional[Token]:
        if self.at(kind, value):
            return self.next()
        return None

    def expect(self, kind: str, value: Optional[str] = None) -> Token:
        token = self.peek()
        if token.kind != kind or (value is not None and token.value != value):
            wanted = f"{kind} {value!r}" if value is not None else kind
            found = f"{token.kind} {token.value!r}" if token.value else token.kind
            raise TranspileError(f"Expected {wanted} but found {found}", token.line, token.col)
        return self.next()

    def mark(self) -> int:
        """Snapshot the cursor so speculative parses can `reset` on failure."""
        return self._pos

    def reset(self, mark: int) -> None:
        self._pos = mark

    def previous(self) -> Optional[Token]:
        return self._tokens[self._pos - 1] if self._pos > 0 else None

    @property
    def exhausted(self) -> bool:
        return self._pos >= len(self._tokens)


class CodeWriter:
    """Line-oriented emitter that tracks indentation depth."""

    def __init__(self, indent: str = "  ") -> None:
        self._indent = indent
        self._depth = 0
        self._lines: List[str] = []

    def line(self, text: str = "") -> None:
        self._lines.append(f"{self._indent * self._depth}{text}" if text else "")

    def indent(self) -> None:
        self._depth += 1

    def dedent(self) -> None:
        if self._depth == 0:
            raise ValueError("dedent below zero")
        self._depth -= 1

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"
