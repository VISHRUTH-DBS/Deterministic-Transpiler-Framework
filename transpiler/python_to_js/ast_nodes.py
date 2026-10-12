"""Strictly typed AST for the supported Python subset.

All nodes are immutable dataclasses. Sequences are tuples so trees are hashable
and cannot be mutated by a later pass by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union


@dataclass(frozen=True, kw_only=True)
class Node:
    line: int = 0


# ----------------------------------------------------------------- expressions
@dataclass(frozen=True)
class Number(Node):
    text: str


@dataclass(frozen=True)
class String(Node):
    value: str  # already unescaped


@dataclass(frozen=True)
class Boolean(Node):
    value: bool


@dataclass(frozen=True)
class NoneLiteral(Node):
    pass


@dataclass(frozen=True)
class Name(Node):
    id: str


@dataclass(frozen=True)
class UnaryOp(Node):
    op: str  # '-', '+', 'not'
    operand: "Expr"


@dataclass(frozen=True)
class BinaryOp(Node):
    op: str  # '+', '-', '*', '/', '//', '%', '**'
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class BoolOp(Node):
    op: str  # 'and' | 'or'
    values: Tuple["Expr", ...]


@dataclass(frozen=True)
class Compare(Node):
    left: "Expr"
    ops: Tuple[str, ...]
    comparators: Tuple["Expr", ...]


@dataclass(frozen=True)
class Call(Node):
    func: "Expr"
    args: Tuple["Expr", ...]


@dataclass(frozen=True)
class ListLiteral(Node):
    elements: Tuple["Expr", ...]


@dataclass(frozen=True)
class Subscript(Node):
    value: "Expr"
    index: "Expr"


@dataclass(frozen=True)
class Attribute(Node):
    value: "Expr"
    attr: str


Expr = Union[
    Number, String, Boolean, NoneLiteral, Name, UnaryOp, BinaryOp, BoolOp,
    Compare, Call, ListLiteral, Subscript, Attribute,
]


# ------------------------------------------------------------------ statements
@dataclass(frozen=True)
class Assign(Node):
    target: Union[Name, Subscript, Attribute]
    value: Expr


@dataclass(frozen=True)
class AugAssign(Node):
    target: Union[Name, Subscript, Attribute]
    op: str  # '+', '-', '*', '/', '//', '%', '**'
    value: Expr


@dataclass(frozen=True)
class ExprStmt(Node):
    value: Expr


@dataclass(frozen=True)
class If(Node):
    test: Expr
    body: Tuple["Stmt", ...]
    orelse: Tuple["Stmt", ...]


@dataclass(frozen=True)
class While(Node):
    test: Expr
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class ForRange(Node):
    """`for target in range(start, stop, step)` with a literal integer step."""

    target: str
    start: Optional[Expr]
    stop: Expr
    step: int
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class ForIn(Node):
    target: str
    iterable: Expr
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class FunctionDef(Node):
    name: str
    params: Tuple[str, ...]
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class Return(Node):
    value: Optional[Expr]


@dataclass(frozen=True)
class Break(Node):
    pass


@dataclass(frozen=True)
class Continue(Node):
    pass


@dataclass(frozen=True)
class Pass(Node):
    pass


Stmt = Union[
    Assign, AugAssign, ExprStmt, If, While, ForRange, ForIn, FunctionDef,
    Return, Break, Continue, Pass,
]


@dataclass(frozen=True)
class Module(Node):
    body: Tuple[Stmt, ...]
