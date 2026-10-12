"""Scope analysis used by the generator to place `let` declarations correctly.

Python has function-level scoping with no declarations; JavaScript's `let` is
block-scoped and must precede use. For every scope (module or function body)
this module decides, per assigned name, between:

* a **local site**: the first assignment may itself be emitted as `let x = ...`
  because every occurrence of `x` in the scope lies inside the block that
  contains that assignment, at or after it (so a fresh per-block binding is
  indistinguishable from Python's behaviour);
* a **hoist**: otherwise a single `let x;` is emitted at the top of the scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterator, List, Optional, Sequence, Tuple

from . import ast_nodes as ast


# ------------------------------------------------------------------ traversal
def sub_blocks(stmt: ast.Stmt) -> Tuple[Tuple[ast.Stmt, ...], ...]:
    if isinstance(stmt, ast.If):
        return (stmt.body, stmt.orelse)
    if isinstance(stmt, (ast.While, ast.ForRange, ast.ForIn, ast.FunctionDef)):
        return (stmt.body,)
    return ()


def header_exprs(stmt: ast.Stmt) -> Tuple[ast.Expr, ...]:
    """Expressions that belong to the statement itself, not to a nested block."""
    if isinstance(stmt, ast.Assign):
        return (stmt.target, stmt.value)
    if isinstance(stmt, ast.AugAssign):
        return (stmt.target, stmt.value)
    if isinstance(stmt, ast.ExprStmt):
        return (stmt.value,)
    if isinstance(stmt, (ast.If, ast.While)):
        return (stmt.test,)
    if isinstance(stmt, ast.ForRange):
        return tuple(e for e in (stmt.start, stmt.stop) if e is not None)
    if isinstance(stmt, ast.ForIn):
        return (stmt.iterable,)
    if isinstance(stmt, ast.Return):
        return (stmt.value,) if stmt.value is not None else ()
    return ()


def child_exprs(expr: ast.Expr) -> Tuple[ast.Expr, ...]:
    if isinstance(expr, ast.UnaryOp):
        return (expr.operand,)
    if isinstance(expr, ast.BinaryOp):
        return (expr.left, expr.right)
    if isinstance(expr, ast.BoolOp):
        return expr.values
    if isinstance(expr, ast.Compare):
        return (expr.left, *expr.comparators)
    if isinstance(expr, ast.Call):
        return (expr.func, *expr.args)
    if isinstance(expr, ast.ListLiteral):
        return expr.elements
    if isinstance(expr, ast.Subscript):
        return (expr.value, expr.index)
    if isinstance(expr, ast.Attribute):
        return (expr.value,)
    return ()


def walk_expr(expr: ast.Expr) -> Iterator[ast.Expr]:
    yield expr
    for child in child_exprs(expr):
        yield from walk_expr(child)


def walk_stmts(stmts: Sequence[ast.Stmt], into_functions: bool = True) -> Iterator[ast.Stmt]:
    for stmt in stmts:
        yield stmt
        if isinstance(stmt, ast.FunctionDef) and not into_functions:
            continue
        for block in sub_blocks(stmt):
            yield from walk_stmts(block, into_functions)


# ----------------------------------------------------------------- name facts
def _stmt_direct_mentions(stmt: ast.Stmt, name: str) -> int:
    count = 0
    for expr in header_exprs(stmt):
        count += sum(1 for e in walk_expr(expr) if isinstance(e, ast.Name) and e.id == name)
    if isinstance(stmt, (ast.ForRange, ast.ForIn)) and stmt.target == name:
        count += 1
    if isinstance(stmt, ast.FunctionDef) and stmt.name == name:
        count += 1
    return count


def _shadows(func: ast.FunctionDef, name: str) -> bool:
    """A nested function with its own binding of `name` never touches ours."""
    return name in func.params or name in assigned_names(func.body)


def occurrences(stmts: Sequence[ast.Stmt], name: str) -> int:
    """Every mention of `name`, including closures that read it from this scope."""
    total = 0
    for stmt in stmts:
        total += _stmt_direct_mentions(stmt, name)
        if isinstance(stmt, ast.FunctionDef) and _shadows(stmt, name):
            continue
        for block in sub_blocks(stmt):
            total += occurrences(block, name)
    return total


def free_occurrences(stmts: Sequence[ast.Stmt], name: str) -> int:
    """Mentions of `name` that are not inside a loop which itself binds `name`."""
    total = 0
    for stmt in stmts:
        if isinstance(stmt, (ast.ForRange, ast.ForIn)) and stmt.target == name:
            total += sum(1 for expr in header_exprs(stmt) for e in walk_expr(expr)
                         if isinstance(e, ast.Name) and e.id == name)
            continue
        total += _stmt_direct_mentions(stmt, name)
        if isinstance(stmt, ast.FunctionDef) and _shadows(stmt, name):
            continue
        for block in sub_blocks(stmt):
            total += free_occurrences(block, name)
    return total


def assigned_names(stmts: Sequence[ast.Stmt], into_functions: bool = False) -> List[str]:
    """Names bound by assignment or loop target, in first-appearance order."""
    seen: List[str] = []
    for stmt in walk_stmts(stmts, into_functions):
        name: Optional[str] = None
        if isinstance(stmt, (ast.Assign, ast.AugAssign)) and isinstance(stmt.target, ast.Name):
            name = stmt.target.id
        elif isinstance(stmt, (ast.ForRange, ast.ForIn)):
            name = stmt.target
        if name is not None and name not in seen:
            seen.append(name)
    return seen


def _first_mention(
    block: Sequence[ast.Stmt], name: str
) -> Optional[Tuple[Sequence[ast.Stmt], int]]:
    for index, stmt in enumerate(block):
        if _stmt_direct_mentions(stmt, name):
            return block, index
        if isinstance(stmt, ast.FunctionDef):
            continue
        for sub in sub_blocks(stmt):
            found = _first_mention(sub, name)
            if found is not None:
                return found
    return None


# ----------------------------------------------------------------------- plan
@dataclass(frozen=True)
class ScopePlan:
    hoisted: Tuple[str, ...]
    let_sites: FrozenSet[int]  # id() of Assign / ForRange / ForIn nodes that declare with `let`


def plan_scope(body: Sequence[ast.Stmt], params: Sequence[str] = ()) -> ScopePlan:
    hoisted: List[str] = []
    sites: set[int] = set()
    function_names = {s.name for s in walk_stmts(body, into_functions=False)
                      if isinstance(s, ast.FunctionDef)}
    for name in assigned_names(body):
        if name in params or name in function_names:
            continue
        total = occurrences(body, name)
        found = _first_mention(body, name)
        local = False
        if found is not None:
            block, index = found
            stmt = block[index]
            if isinstance(stmt, ast.Assign) and isinstance(stmt.target, ast.Name) \
                    and stmt.target.id == name:
                value_mentions = sum(1 for e in walk_expr(stmt.value)
                                     if isinstance(e, ast.Name) and e.id == name)
                if value_mentions == 0 and occurrences(block[index:], name) == total:
                    sites.add(id(stmt))
                    local = True
            elif isinstance(stmt, (ast.ForRange, ast.ForIn)) and stmt.target == name:
                # Loop variables never read outside their own loops can use the
                # loop-scoped `for (let i ...)` form, independently per loop.
                if free_occurrences(body, name) == 0:
                    for loop in walk_stmts(body, into_functions=False):
                        if isinstance(loop, (ast.ForRange, ast.ForIn)) and loop.target == name:
                            sites.add(id(loop))
                    local = True
        if not local:
            hoisted.append(name)
    return ScopePlan(hoisted=tuple(hoisted), let_sites=frozenset(sites))
