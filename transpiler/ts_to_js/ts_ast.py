"""Strictly typed AST for the TypeScript subset.

One node hierarchy serves both the TypeScript tree (produced by the parser) and
the erased JavaScript tree (produced by the type eraser). After erasure every
type slot is `None`/empty and no *type-level node* remains; the printer
verifies this and refuses to emit anything that still carries type syntax.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union


@dataclass(frozen=True, kw_only=True)
class Node:
    line: int = 0


# ============================================================ type-level nodes
@dataclass(frozen=True)
class TypeReference(Node):
    name: str  # dotted names allowed: `ns.Type`
    args: Tuple["TypeNode", ...] = ()


@dataclass(frozen=True)
class LiteralType(Node):
    text: str  # raw source text: 'a', 42, true, null ...


@dataclass(frozen=True)
class UnionType(Node):
    types: Tuple["TypeNode", ...]


@dataclass(frozen=True)
class IntersectionType(Node):
    types: Tuple["TypeNode", ...]


@dataclass(frozen=True)
class ArrayType(Node):
    element: "TypeNode"


@dataclass(frozen=True)
class TupleType(Node):
    elements: Tuple["TypeNode", ...]


@dataclass(frozen=True)
class IndexedAccessType(Node):
    obj: "TypeNode"
    index: "TypeNode"


@dataclass(frozen=True)
class TypeOperator(Node):
    op: str  # 'keyof'
    operand: "TypeNode"


@dataclass(frozen=True)
class TypeQuery(Node):
    name: str  # typeof x


@dataclass(frozen=True)
class FunctionType(Node):
    type_params: Tuple["TypeParameter", ...]
    params: Tuple["Param", ...]
    returns: "TypeNode"


@dataclass(frozen=True)
class PropertySignature(Node):
    name: str
    optional: bool
    readonly: bool
    type: Optional["TypeNode"]


@dataclass(frozen=True)
class IndexSignature(Node):
    key_name: str
    key_type: "TypeNode"
    value_type: "TypeNode"


@dataclass(frozen=True)
class MethodSignature(Node):
    name: str
    optional: bool
    type_params: Tuple["TypeParameter", ...]
    params: Tuple["Param", ...]
    returns: Optional["TypeNode"]


@dataclass(frozen=True)
class ObjectType(Node):
    members: Tuple[Union[PropertySignature, IndexSignature, MethodSignature], ...]


TypeNode = Union[
    TypeReference, LiteralType, UnionType, IntersectionType, ArrayType, TupleType,
    IndexedAccessType, TypeOperator, TypeQuery, FunctionType, ObjectType,
]


@dataclass(frozen=True)
class TypeParameter(Node):
    name: str
    constraint: Optional[TypeNode] = None
    default: Optional[TypeNode] = None


# ================================================================== expressions
@dataclass(frozen=True)
class NumberLiteral(Node):
    text: str


@dataclass(frozen=True)
class StringLiteral(Node):
    raw: str  # includes the original quotes


@dataclass(frozen=True)
class TemplateLiteral(Node):
    raw: str  # includes backticks; substitutions are passed through verbatim


@dataclass(frozen=True)
class BooleanLiteral(Node):
    value: bool


@dataclass(frozen=True)
class NullLiteral(Node):
    pass


@dataclass(frozen=True)
class Identifier(Node):
    name: str


@dataclass(frozen=True)
class SpreadElement(Node):
    argument: "Expr"


@dataclass(frozen=True)
class ArrayLiteral(Node):
    elements: Tuple["Expr", ...]


@dataclass(frozen=True)
class Property(Node):
    key: str  # raw key text (identifier, string literal, or number)
    value: "Expr"
    shorthand: bool = False


@dataclass(frozen=True)
class ObjectLiteral(Node):
    properties: Tuple[Union[Property, SpreadElement], ...]


@dataclass(frozen=True)
class Unary(Node):
    op: str  # '!', '-', '+', '~', 'typeof', 'void', 'delete'
    operand: "Expr"


@dataclass(frozen=True)
class Update(Node):
    op: str  # '++' | '--'
    operand: "Expr"
    prefix: bool


@dataclass(frozen=True)
class Binary(Node):
    op: str
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class Assignment(Node):
    op: str  # '=', '+=', ...
    target: "Expr"
    value: "Expr"


@dataclass(frozen=True)
class Conditional(Node):
    test: "Expr"
    consequent: "Expr"
    alternate: "Expr"


@dataclass(frozen=True)
class Call(Node):
    callee: "Expr"
    type_args: Tuple[TypeNode, ...]
    args: Tuple["Expr", ...]


@dataclass(frozen=True)
class New(Node):
    callee: "Expr"
    type_args: Tuple[TypeNode, ...]
    args: Tuple["Expr", ...]


@dataclass(frozen=True)
class Member(Node):
    obj: "Expr"
    prop: str
    optional: bool = False  # `a?.b`


@dataclass(frozen=True)
class Index(Node):
    obj: "Expr"
    index: "Expr"


@dataclass(frozen=True)
class Param(Node):
    name: str
    optional: bool = False
    annotation: Optional[TypeNode] = None
    default: Optional["Expr"] = None
    rest: bool = False


@dataclass(frozen=True)
class ArrowFunction(Node):
    type_params: Tuple[TypeParameter, ...]
    params: Tuple[Param, ...]
    return_type: Optional[TypeNode]
    body: Union["Expr", Tuple["Stmt", ...]]  # expression body or statement list
    expression_body: bool


@dataclass(frozen=True)
class FunctionExpression(Node):
    name: Optional[str]
    type_params: Tuple[TypeParameter, ...]
    params: Tuple[Param, ...]
    return_type: Optional[TypeNode]
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class AsExpression(Node):
    """`expr as T` / `expr satisfies T` -- type-level, removed by erasure."""

    expression: "Expr"
    type: TypeNode
    keyword: str = "as"


@dataclass(frozen=True)
class NonNullExpression(Node):
    """`expr!` -- type-level, removed by erasure."""

    expression: "Expr"


Expr = Union[
    NumberLiteral, StringLiteral, TemplateLiteral, BooleanLiteral, NullLiteral, Identifier,
    SpreadElement, ArrayLiteral, ObjectLiteral, Unary, Update, Binary, Assignment,
    Conditional, Call, New, Member, Index, ArrowFunction, FunctionExpression,
    AsExpression, NonNullExpression,
]


# =================================================================== statements
@dataclass(frozen=True)
class Declarator(Node):
    name: str
    annotation: Optional[TypeNode] = None
    init: Optional[Expr] = None
    definite: bool = False  # `let x!: T`


@dataclass(frozen=True)
class VariableDeclaration(Node):
    kind: str  # 'let' | 'const' | 'var'
    declarations: Tuple[Declarator, ...]
    exported: bool = False


@dataclass(frozen=True)
class FunctionDeclaration(Node):
    name: str
    type_params: Tuple[TypeParameter, ...]
    params: Tuple[Param, ...]
    return_type: Optional[TypeNode]
    body: Optional[Tuple["Stmt", ...]]  # None => overload signature
    exported: bool = False


@dataclass(frozen=True)
class ReturnStatement(Node):
    value: Optional[Expr]


@dataclass(frozen=True)
class IfStatement(Node):
    test: Expr
    consequent: Tuple["Stmt", ...]
    alternate: Optional[Tuple["Stmt", ...]]


@dataclass(frozen=True)
class WhileStatement(Node):
    test: Expr
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class ForStatement(Node):
    init: Optional[Union[VariableDeclaration, Expr]]
    test: Optional[Expr]
    update: Optional[Expr]
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class ForEachStatement(Node):
    kind: str  # declaration keyword: let/const/var
    name: str
    iteration: str  # 'of' | 'in'
    iterable: Expr
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class BreakStatement(Node):
    pass


@dataclass(frozen=True)
class ContinueStatement(Node):
    pass


@dataclass(frozen=True)
class ExpressionStatement(Node):
    expression: Expr


@dataclass(frozen=True)
class BlockStatement(Node):
    body: Tuple["Stmt", ...]


@dataclass(frozen=True)
class ImportSpecifier(Node):
    name: str
    alias: Optional[str] = None
    type_only: bool = False


@dataclass(frozen=True)
class ImportDeclaration(Node):
    type_only: bool
    default: Optional[str]
    specifiers: Tuple[ImportSpecifier, ...]
    source: str  # raw string literal


@dataclass(frozen=True)
class InterfaceDeclaration(Node):
    name: str
    type_params: Tuple[TypeParameter, ...]
    extends: Tuple[TypeNode, ...]
    members: Tuple[Union[PropertySignature, IndexSignature, MethodSignature], ...]
    exported: bool = False


@dataclass(frozen=True)
class TypeAliasDeclaration(Node):
    name: str
    type_params: Tuple[TypeParameter, ...]
    type: TypeNode
    exported: bool = False


@dataclass(frozen=True)
class AmbientDeclaration(Node):
    """`declare ...` -- describes something that exists elsewhere; emits nothing."""

    inner: "Stmt"


Stmt = Union[
    VariableDeclaration, FunctionDeclaration, ReturnStatement, IfStatement, WhileStatement,
    ForStatement, ForEachStatement, BreakStatement, ContinueStatement, ExpressionStatement,
    BlockStatement, ImportDeclaration, InterfaceDeclaration, TypeAliasDeclaration,
    AmbientDeclaration,
]


@dataclass(frozen=True)
class Program(Node):
    body: Tuple[Stmt, ...]


# Node classes that exist only at the type level; the printer rejects them.
TYPE_LEVEL_NODES = (
    TypeReference, LiteralType, UnionType, IntersectionType, ArrayType, TupleType,
    IndexedAccessType, TypeOperator, TypeQuery, FunctionType, ObjectType, TypeParameter,
    PropertySignature, IndexSignature, MethodSignature, AsExpression, NonNullExpression,
    InterfaceDeclaration, TypeAliasDeclaration, AmbientDeclaration,
)
