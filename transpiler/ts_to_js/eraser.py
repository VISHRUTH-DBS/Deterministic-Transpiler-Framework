"""Type erasure: TypeScript AST -> JavaScript AST (an AST-to-AST pass).

Two kinds of removal happen here, which is the heart of the TS->JS problem:

* **Dropping nodes**: whole statements that exist only for the type checker
  (interfaces, type aliases, `declare ...`, overload signatures, `import type`).
* **Unwrapping / blanking nodes**: wrappers such as `x as T` and `x!` are replaced
  by the inner expression; type slots (annotations, generics, `?` markers,
  `this` parameters, definite-assignment `!`) are cleared.

The pass is a pure function: it never mutates the input tree.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any, Optional, Tuple

from . import ts_ast as t


class TypeEraser:
    def erase_program(self, program: t.Program) -> t.Program:
        return replace(program, body=self._stmts(program.body))

    # ------------------------------------------------------------- statements
    def _stmts(self, stmts: Tuple[t.Stmt, ...]) -> Tuple[t.Stmt, ...]:
        out = []
        for stmt in stmts:
            erased = self._stmt(stmt)
            if erased is not None:
                out.append(erased)
        return tuple(out)

    def _stmt(self, node: t.Stmt) -> Optional[t.Stmt]:
        if isinstance(node, (t.InterfaceDeclaration, t.TypeAliasDeclaration, t.AmbientDeclaration)):
            return None
        if isinstance(node, t.ImportDeclaration):
            return self._import(node)
        if isinstance(node, t.FunctionDeclaration):
            if node.body is None:
                return None  # overload signature: no runtime presence
            return replace(node, type_params=(), params=self._params(node.params),
                           return_type=None, body=self._stmts(node.body))
        if isinstance(node, t.VariableDeclaration):
            return replace(node, declarations=tuple(self._declarator(d) for d in node.declarations))
        if isinstance(node, t.ForStatement):
            init = node.init
            if isinstance(init, t.VariableDeclaration):
                init = self._stmt(init)
            elif init is not None:
                init = self._expr(init)
            return replace(node, init=init,
                           test=self._opt_expr(node.test), update=self._opt_expr(node.update),
                           body=self._stmts(node.body))
        if isinstance(node, t.IfStatement):
            alternate = None if node.alternate is None else self._stmts(node.alternate)
            return replace(node, test=self._expr(node.test),
                           consequent=self._stmts(node.consequent), alternate=alternate)
        return self._generic(node)

    def _import(self, node: t.ImportDeclaration) -> Optional[t.ImportDeclaration]:
        if node.type_only:
            return None
        kept = tuple(replace(s, type_only=False) for s in node.specifiers if not s.type_only)
        if node.specifiers and not kept and node.default is None:
            return None  # every binding was type-only
        return replace(node, specifiers=kept)

    def _declarator(self, d: t.Declarator) -> t.Declarator:
        return replace(d, annotation=None, definite=False, init=self._opt_expr(d.init))

    def _params(self, params: Tuple[t.Param, ...]) -> Tuple[t.Param, ...]:
        return tuple(
            replace(p, optional=False, annotation=None, default=self._opt_expr(p.default))
            for p in params if p.name != "this"  # TS `this` parameter is type-only
        )

    # ------------------------------------------------------------ expressions
    def _opt_expr(self, expr: Optional[t.Expr]) -> Optional[t.Expr]:
        return None if expr is None else self._expr(expr)

    def _expr(self, node: t.Expr) -> t.Expr:
        if isinstance(node, (t.AsExpression, t.NonNullExpression)):
            return self._expr(node.expression)
        if isinstance(node, (t.Call, t.New)):
            return replace(node, callee=self._expr(node.callee), type_args=(),
                           args=tuple(self._expr(a) for a in node.args))
        if isinstance(node, t.ArrowFunction):
            body = self._stmts(node.body) if not node.expression_body else self._expr(node.body)
            return replace(node, type_params=(), params=self._params(node.params),
                           return_type=None, body=body)
        if isinstance(node, t.FunctionExpression):
            return replace(node, type_params=(), params=self._params(node.params),
                           return_type=None, body=self._stmts(node.body))
        return self._generic(node)

    # ------------------------------------------------------- structural walker
    def _generic(self, node: Any) -> Any:
        """Rebuild `node`, erasing every child node reachable through its fields."""
        changes = {}
        for f in fields(node):
            value = getattr(node, f.name)
            if is_dataclass(value):
                changes[f.name] = self._child(value)
            elif isinstance(value, tuple) and value and all(is_dataclass(v) for v in value):
                kids = (self._child(v) for v in value if self._keep(v))
                changes[f.name] = tuple(k for k in kids if k is not None)
        return replace(node, **changes) if changes else node

    @staticmethod
    def _keep(node: Any) -> bool:
        return not isinstance(node, (t.InterfaceDeclaration, t.TypeAliasDeclaration, t.AmbientDeclaration))

    def _child(self, node: Any) -> Any:
        stmt_types = (
            t.VariableDeclaration, t.FunctionDeclaration, t.ReturnStatement, t.IfStatement,
            t.WhileStatement, t.ForStatement, t.ForEachStatement, t.BreakStatement,
            t.ContinueStatement, t.ExpressionStatement, t.BlockStatement, t.ImportDeclaration,
        )
        if isinstance(node, stmt_types):
            return self._stmt(node)
        if isinstance(node, (t.Property, t.SpreadElement)):
            return self._generic(node)
        return self._expr(node)


def erase_types(program: t.Program) -> t.Program:
    return TypeEraser().erase_program(program)
