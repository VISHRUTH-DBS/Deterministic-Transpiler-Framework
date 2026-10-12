"""JavaScript printer: erased AST -> source text.

Expressions are printed by precedence so parentheses appear only where required.
Statement bodies nested inside expressions (function expressions, block-bodied
arrows) are rendered through `_block_text`, which temporarily swaps the output
buffer so multi-line text can be embedded in a single expression string.

The printer refuses any node that is still type-level, so a forgotten case in
the eraser fails loudly instead of leaking TypeScript syntax into the output.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from ..core import TranspileError
from . import ts_ast as t

BINARY_PREC = {
    "??": 3, "||": 4, "&&": 5, "|": 6, "^": 7, "&": 8,
    "==": 9, "!=": 9, "===": 9, "!==": 9,
    "<": 10, ">": 10, "<=": 10, ">=": 10, "instanceof": 10, "in": 10,
    "<<": 11, ">>": 11, ">>>": 11,
    "+": 12, "-": 12, "*": 13, "/": 13, "%": 13, "**": 14,
}
P_ASSIGN, P_COND, P_UNARY, P_POSTFIX, P_CALL, P_ATOM = 1, 2, 15, 16, 17, 18


class Printer:
    def __init__(self, indent: str = "  ") -> None:
        self._unit = indent
        self._depth = 0
        self._lines: List[str] = []

    # ----------------------------------------------------------------- driver
    def print_program(self, program: t.Program) -> str:
        self._statements(program.body)
        return "\n".join(self._lines) + "\n" if self._lines else ""

    def _emit(self, text: str) -> None:
        self._lines.append(f"{self._unit * self._depth}{text}" if text else "")

    def _statements(self, stmts: Sequence[t.Stmt]) -> None:
        prev_was_fn = False
        for index, stmt in enumerate(stmts):
            is_fn = isinstance(stmt, t.FunctionDeclaration)
            if index > 0 and (is_fn or prev_was_fn):
                self._emit("")
            self._statement(stmt)
            prev_was_fn = is_fn

    def _nested(self, stmts: Sequence[t.Stmt]) -> None:
        self._depth += 1
        self._statements(stmts)
        self._depth -= 1

    def _block_text(self, stmts: Sequence[t.Stmt]) -> str:
        """Render `{ ...statements... }` at the current depth as one string."""
        saved, self._lines = self._lines, []
        self._nested(stmts)
        inner = self._lines
        self._lines = saved
        if not inner:
            return "{}"
        return "{\n" + "\n".join(inner) + "\n" + self._unit * self._depth + "}"

    # -------------------------------------------------------------- statements
    def _statement(self, node: t.Stmt) -> None:
        if isinstance(node, t.TYPE_LEVEL_NODES):
            raise TranspileError(f"Type-level node {type(node).__name__} survived erasure", node.line)
        getattr(self, f"_stmt_{type(node).__name__}")(node)

    def _stmt_VariableDeclaration(self, n: t.VariableDeclaration) -> None:
        self._emit(f"{'export ' if n.exported else ''}{self._var_text(n)};")

    def _var_text(self, n: t.VariableDeclaration) -> str:
        parts = []
        for d in n.declarations:
            parts.append(d.name if d.init is None else f"{d.name} = {self._text(d.init, P_ASSIGN)}")
        return f"{n.kind} " + ", ".join(parts)

    def _stmt_FunctionDeclaration(self, n: t.FunctionDeclaration) -> None:
        assert n.body is not None
        head = f"{'export ' if n.exported else ''}function {n.name}({self._params(n.params)}) "
        self._emit(head + self._block_text(n.body))

    def _stmt_ReturnStatement(self, n: t.ReturnStatement) -> None:
        self._emit("return;" if n.value is None else f"return {self._text(n.value)};")

    def _stmt_BreakStatement(self, n: t.BreakStatement) -> None:
        self._emit("break;")

    def _stmt_ContinueStatement(self, n: t.ContinueStatement) -> None:
        self._emit("continue;")

    def _stmt_ExpressionStatement(self, n: t.ExpressionStatement) -> None:
        text = self._text(n.expression)
        if isinstance(n.expression, (t.ObjectLiteral, t.FunctionExpression)):
            text = f"({text})"  # otherwise parsed as a block / declaration
        self._emit(f"{text};")

    def _stmt_BlockStatement(self, n: t.BlockStatement) -> None:
        self._emit("{")
        self._nested(n.body)
        self._emit("}")

    def _stmt_ImportDeclaration(self, n: t.ImportDeclaration) -> None:
        clauses: List[str] = []
        if n.default:
            clauses.append(n.default)
        if n.specifiers:
            names = ", ".join(s.name if s.alias is None else f"{s.name} as {s.alias}"
                              for s in n.specifiers)
            clauses.append("{ " + names + " }")
        if clauses:
            self._emit(f"import {', '.join(clauses)} from {n.source};")
        else:
            self._emit(f"import {n.source};")

    def _stmt_IfStatement(self, n: t.IfStatement) -> None:
        self._emit(f"if ({self._text(n.test)}) {{")
        self._nested(n.consequent)
        current = n
        while current.alternate is not None and len(current.alternate) == 1 \
                and isinstance(current.alternate[0], t.IfStatement):
            current = current.alternate[0]
            self._emit(f"}} else if ({self._text(current.test)}) {{")
            self._nested(current.consequent)
        if current.alternate is not None:
            self._emit("} else {")
            self._nested(current.alternate)
        self._emit("}")

    def _stmt_WhileStatement(self, n: t.WhileStatement) -> None:
        self._emit(f"while ({self._text(n.test)}) {{")
        self._nested(n.body)
        self._emit("}")

    def _stmt_ForStatement(self, n: t.ForStatement) -> None:
        if n.init is None:
            init = ""
        elif isinstance(n.init, t.VariableDeclaration):
            init = self._var_text(n.init)
        else:
            init = self._text(n.init)
        test = "" if n.test is None else self._text(n.test)
        update = "" if n.update is None else self._text(n.update)
        header = f"{init}; {test}; {update}".rstrip()
        self._emit(f"for ({header}) {{")
        self._nested(n.body)
        self._emit("}")

    def _stmt_ForEachStatement(self, n: t.ForEachStatement) -> None:
        self._emit(f"for ({n.kind} {n.name} {n.iteration} {self._text(n.iterable)}) {{")
        self._nested(n.body)
        self._emit("}")

    # ------------------------------------------------------------- expressions
    def _params(self, params: Sequence[t.Param]) -> str:
        out = []
        for p in params:
            text = ("..." if p.rest else "") + p.name
            if p.default is not None:
                text += f" = {self._text(p.default, P_ASSIGN)}"
            out.append(text)
        return ", ".join(out)

    def _text(self, expr: t.Expr, min_prec: int = 0) -> str:
        if isinstance(expr, t.TYPE_LEVEL_NODES):
            raise TranspileError(f"Type-level node {type(expr).__name__} survived erasure", expr.line)
        text, prec = getattr(self, f"_expr_{type(expr).__name__}")(expr)
        return f"({text})" if prec < min_prec else text

    def _expr_NumberLiteral(self, e: t.NumberLiteral) -> Tuple[str, int]:
        return e.text, P_ATOM

    def _expr_StringLiteral(self, e: t.StringLiteral) -> Tuple[str, int]:
        return e.raw, P_ATOM

    def _expr_TemplateLiteral(self, e: t.TemplateLiteral) -> Tuple[str, int]:
        return e.raw, P_ATOM

    def _expr_BooleanLiteral(self, e: t.BooleanLiteral) -> Tuple[str, int]:
        return ("true" if e.value else "false"), P_ATOM

    def _expr_NullLiteral(self, e: t.NullLiteral) -> Tuple[str, int]:
        return "null", P_ATOM

    def _expr_Identifier(self, e: t.Identifier) -> Tuple[str, int]:
        return e.name, P_ATOM

    def _expr_SpreadElement(self, e: t.SpreadElement) -> Tuple[str, int]:
        return f"...{self._text(e.argument, P_ASSIGN)}", P_ASSIGN

    def _expr_ArrayLiteral(self, e: t.ArrayLiteral) -> Tuple[str, int]:
        return "[" + ", ".join(self._text(x, P_ASSIGN) for x in e.elements) + "]", P_ATOM

    def _expr_ObjectLiteral(self, e: t.ObjectLiteral) -> Tuple[str, int]:
        if not e.properties:
            return "{}", P_ATOM
        parts = []
        for prop in e.properties:
            if isinstance(prop, t.SpreadElement):
                parts.append(self._text(prop))
            elif prop.shorthand:
                parts.append(prop.key)
            else:
                parts.append(f"{prop.key}: {self._text(prop.value, P_ASSIGN)}")
        return "{ " + ", ".join(parts) + " }", P_ATOM

    def _expr_Member(self, e: t.Member) -> Tuple[str, int]:
        dot = "?." if e.optional else "."
        return f"{self._text(e.obj, P_CALL)}{dot}{e.prop}", P_CALL

    def _expr_Index(self, e: t.Index) -> Tuple[str, int]:
        return f"{self._text(e.obj, P_CALL)}[{self._text(e.index)}]", P_CALL

    def _args(self, args: Sequence[t.Expr]) -> str:
        return ", ".join(self._text(a, P_ASSIGN) for a in args)

    def _expr_Call(self, e: t.Call) -> Tuple[str, int]:
        return f"{self._text(e.callee, P_CALL)}({self._args(e.args)})", P_CALL

    def _expr_New(self, e: t.New) -> Tuple[str, int]:
        callee = self._text(e.callee, P_CALL)
        if isinstance(e.callee, t.Call):
            callee = f"({callee})"  # `new (f())()` differs from `new f()()`
        return f"new {callee}({self._args(e.args)})", P_CALL

    def _expr_Update(self, e: t.Update) -> Tuple[str, int]:
        if e.prefix:
            return f"{e.op}{self._text(e.operand, P_UNARY)}", P_UNARY
        return f"{self._text(e.operand, P_CALL)}{e.op}", P_POSTFIX

    def _expr_Unary(self, e: t.Unary) -> Tuple[str, int]:
        operand = self._text(e.operand, P_UNARY)
        if e.op.isalpha():
            return f"{e.op} {operand}", P_UNARY
        if operand.startswith(e.op[0]) and e.op in ("-", "+"):
            operand = f"({operand})"  # keep `- -x` from fusing into `--x`
        return f"{e.op}{operand}", P_UNARY

    def _expr_Binary(self, e: t.Binary) -> Tuple[str, int]:
        prec = BINARY_PREC[e.op]
        right_assoc = e.op == "**"
        left = self._text(e.left, prec + 1 if right_assoc else prec)
        right = self._text(e.right, prec if right_assoc else prec + 1)
        if right_assoc and isinstance(e.left, (t.Unary,)) or \
                (right_assoc and isinstance(e.left, t.Update) and e.left.prefix):
            left = f"({self._text(e.left)})"  # `-a ** b` is a syntax error in JS
        if e.op == "??":
            left, right = self._wrap_logical(e.left, left), self._wrap_logical(e.right, right)
        elif e.op in ("||", "&&"):
            left = self._wrap_nullish(e.left, left)
            right = self._wrap_nullish(e.right, right)
        return f"{left} {e.op} {right}", prec

    @staticmethod
    def _wrap_logical(node: t.Expr, text: str) -> str:
        if isinstance(node, t.Binary) and node.op in ("||", "&&") and not text.startswith("("):
            return f"({text})"
        return text

    @staticmethod
    def _wrap_nullish(node: t.Expr, text: str) -> str:
        if isinstance(node, t.Binary) and node.op == "??" and not text.startswith("("):
            return f"({text})"
        return text

    def _expr_Assignment(self, e: t.Assignment) -> Tuple[str, int]:
        return f"{self._text(e.target, P_CALL)} {e.op} {self._text(e.value, P_ASSIGN)}", P_ASSIGN

    def _expr_Conditional(self, e: t.Conditional) -> Tuple[str, int]:
        test = self._text(e.test, P_COND + 1)
        return (f"{test} ? {self._text(e.consequent, P_ASSIGN)} : "
                f"{self._text(e.alternate, P_ASSIGN)}"), P_COND

    def _expr_ArrowFunction(self, e: t.ArrowFunction) -> Tuple[str, int]:
        head = f"({self._params(e.params)}) => "
        if e.expression_body:
            assert not isinstance(e.body, tuple)
            body = self._text(e.body, P_ASSIGN)
            if isinstance(e.body, t.ObjectLiteral):
                body = f"({body})"
            return head + body, P_ASSIGN
        assert isinstance(e.body, tuple)
        return head + self._block_text(e.body), P_ASSIGN

    def _expr_FunctionExpression(self, e: t.FunctionExpression) -> Tuple[str, int]:
        name = f" {e.name}" if e.name else ""
        return f"function{name}({self._params(e.params)}) " + self._block_text(e.body), P_ATOM


def print_js(program: t.Program) -> str:
    return Printer().print_program(program)
