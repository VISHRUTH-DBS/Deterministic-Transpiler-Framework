"""Code generator: typed Python AST -> JavaScript source text.

Expression emission is precedence-driven: every expression returns its text and
its JavaScript precedence level, and parents add parentheses only where the
child binds more loosely than the position requires.
"""

from __future__ import annotations

import json
from typing import List, Sequence, Set, Tuple

from ..core import CodeWriter, TranspileError
from . import ast_nodes as ast
from .analysis import ScopePlan, assigned_names, plan_scope, walk_expr, walk_stmts

# JavaScript precedence levels (higher binds tighter)
P_OR, P_AND, P_EQ, P_REL, P_ADD, P_MUL, P_POW, P_UNARY, P_POSTFIX, P_ATOM = range(1, 11)

JS_RESERVED = frozenset({
    "arguments", "await", "case", "catch", "class", "const", "debugger", "default",
    "delete", "do", "enum", "eval", "export", "extends", "finally", "function",
    "implements", "import", "instanceof", "interface", "let", "new", "null",
    "package", "private", "protected", "public", "static", "super", "switch",
    "this", "throw", "try", "typeof", "var", "void", "with", "yield",
    "undefined", "NaN", "Infinity",
})

METHOD_MAP = {"append": "push", "upper": "toUpperCase", "lower": "toLowerCase", "strip": "trim"}
CMP_MAP = {"==": "===", "!=": "!==", "<": "<", ">": ">", "<=": "<=", ">=": ">="}

MOD_HELPER = (
    "function __mod(a, b) {\n"
    "  return ((a % b) + b) % b;\n"
    "}\n"
)


def ident(name: str) -> str:
    return f"{name}_" if name in JS_RESERVED else name


def _is_pure(expr: ast.Expr) -> bool:
    """True when evaluating `expr` twice cannot change behaviour."""
    if isinstance(expr, (ast.Name, ast.Number, ast.String, ast.Boolean)):
        return True
    if isinstance(expr, ast.Attribute):
        return _is_pure(expr.value)
    if isinstance(expr, ast.Subscript):
        return _is_pure(expr.value) and _is_pure(expr.index)
    if isinstance(expr, ast.UnaryOp):
        return _is_pure(expr.operand)
    return False


def _negative_literal(expr: ast.Expr) -> str | None:
    if isinstance(expr, ast.UnaryOp) and expr.op == "-" and isinstance(expr.operand, ast.Number):
        return expr.operand.text
    return None


class Generator:
    def __init__(self) -> None:
        self.w = CodeWriter("  ")
        self._plans: List[ScopePlan] = []
        self._uses_mod = False
        self._stop_counter = 0

    # ----------------------------------------------------------------- driver
    def generate(self, module: ast.Module) -> str:
        self._scope(module.body, ())
        body = self.w.render()
        return (MOD_HELPER + "\n" + body) if self._uses_mod else body

    # ------------------------------------------------------------- statements
    def _scope(self, body: Sequence[ast.Stmt], params: Sequence[str]) -> None:
        plan = plan_scope(body, params)
        self._plans.append(plan)
        if plan.hoisted:
            self.w.line("let " + ", ".join(ident(n) for n in plan.hoisted) + ";")
        self._statements(body, separate_defs=True)
        self._plans.pop()

    def _statements(self, stmts: Sequence[ast.Stmt], separate_defs: bool = False) -> None:
        prev_was_def = False
        for index, stmt in enumerate(stmts):
            is_def = isinstance(stmt, ast.FunctionDef)
            if separate_defs and index > 0 and (is_def or prev_was_def):
                self.w.line()
            self._statement(stmt)
            prev_was_def = is_def

    def _indented(self, stmts: Sequence[ast.Stmt]) -> None:
        self.w.indent()
        self._statements(stmts)
        self.w.dedent()

    def _statement(self, node: ast.Stmt) -> None:
        method = getattr(self, f"_stmt_{type(node).__name__}")
        method(node)

    @property
    def _plan(self) -> ScopePlan:
        return self._plans[-1]

    def _stmt_Pass(self, node: ast.Pass) -> None:
        return  # an empty block is already a valid JavaScript no-op

    def _stmt_Break(self, node: ast.Break) -> None:
        self.w.line("break;")

    def _stmt_Continue(self, node: ast.Continue) -> None:
        self.w.line("continue;")

    def _stmt_Return(self, node: ast.Return) -> None:
        if node.value is None:
            self.w.line("return;")
        else:
            self.w.line(f"return {self._text(node.value)};")

    def _stmt_ExprStmt(self, node: ast.ExprStmt) -> None:
        self.w.line(f"{self._text(node.value)};")

    def _target(self, target: ast.Expr) -> str:
        if isinstance(target, ast.Subscript):
            neg = _negative_literal(target.index)
            if neg is not None:
                if not _is_pure(target.value):
                    raise TranspileError("Negative index store needs a simple base expression", target.line)
                base = self._text(target.value)
                return f"{self._child(target.value, P_POSTFIX)}[{base}.length - {neg}]"
        return self._text(target)

    def _stmt_Assign(self, node: ast.Assign) -> None:
        keyword = "let " if id(node) in self._plan.let_sites else ""
        self.w.line(f"{keyword}{self._target(node.target)} = {self._text(node.value)};")

    def _stmt_AugAssign(self, node: ast.AugAssign) -> None:
        if node.op in ("//", "%"):
            if not _is_pure(node.target):
                raise TranspileError(f"'{node.op}=' needs a side-effect-free target", node.line)
            combined = ast.BinaryOp(op=node.op, left=node.target, right=node.value, line=node.line)
            self.w.line(f"{self._target(node.target)} = {self._text(combined)};")
        else:
            self.w.line(f"{self._target(node.target)} {node.op}= {self._text(node.value)};")

    @staticmethod
    def _meaningful(stmts: Sequence[ast.Stmt]) -> Sequence[ast.Stmt]:
        """An `else:` holding only `pass` carries no behaviour; drop it."""
        return stmts if any(not isinstance(s, ast.Pass) for s in stmts) else ()

    def _stmt_If(self, node: ast.If) -> None:
        self.w.line(f"if ({self._text(node.test)}) {{")
        self._indented(node.body)
        current = node
        while True:
            orelse = self._meaningful(current.orelse)
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                current = orelse[0]
                self.w.line(f"}} else if ({self._text(current.test)}) {{")
                self._indented(current.body)
                continue
            if orelse:
                self.w.line("} else {")
                self._indented(orelse)
            break
        self.w.line("}")

    def _stmt_While(self, node: ast.While) -> None:
        self.w.line(f"while ({self._text(node.test)}) {{")
        self._indented(node.body)
        self.w.line("}")

    def _is_invariant(self, expr: ast.Expr, mutated: Set[str]) -> bool:
        if isinstance(expr, ast.Number):
            return True
        if isinstance(expr, ast.Name):
            return expr.id not in mutated
        if isinstance(expr, ast.UnaryOp):
            return self._is_invariant(expr.operand, mutated)
        if isinstance(expr, ast.BinaryOp):
            return self._is_invariant(expr.left, mutated) and self._is_invariant(expr.right, mutated)
        return False

    def _stmt_ForRange(self, node: ast.ForRange) -> None:
        var = ident(node.target)
        keyword = "let " if id(node) in self._plan.let_sites else ""
        start = "0" if node.start is None else self._text(node.start)
        mutated = set(assigned_names(node.body, into_functions=True)) | {node.target}
        stop = self._text(node.stop)
        if not self._is_invariant(node.stop, mutated):
            self._stop_counter += 1
            bound = f"__stop{self._stop_counter}"
            self.w.line(f"const {bound} = {stop};")
            stop = bound
        compare = "<" if node.step > 0 else ">"
        magnitude = abs(node.step)
        if magnitude == 1:
            update = f"{var}++" if node.step > 0 else f"{var}--"
        else:
            update = f"{var} {'+=' if node.step > 0 else '-='} {magnitude}"
        self.w.line(f"for ({keyword}{var} = {start}; {var} {compare} {stop}; {update}) {{")
        self._indented(node.body)
        self.w.line("}")

    def _stmt_ForIn(self, node: ast.ForIn) -> None:
        keyword = "let " if id(node) in self._plan.let_sites else ""
        self.w.line(f"for ({keyword}{ident(node.target)} of {self._text(node.iterable)}) {{")
        self._indented(node.body)
        self.w.line("}")

    def _stmt_FunctionDef(self, node: ast.FunctionDef) -> None:
        params = ", ".join(ident(p) for p in node.params)
        self.w.line(f"function {ident(node.name)}({params}) {{")
        self.w.indent()
        self._scope(node.body, node.params)
        self.w.dedent()
        self.w.line("}")

    # ------------------------------------------------------------ expressions
    def _text(self, expr: ast.Expr) -> str:
        return self._expr(expr)[0]

    def _child(self, expr: ast.Expr, min_prec: int) -> str:
        text, prec = self._expr(expr)
        return f"({text})" if prec < min_prec else text

    def _expr(self, expr: ast.Expr) -> Tuple[str, int]:
        return getattr(self, f"_expr_{type(expr).__name__}")(expr)

    def _expr_Number(self, e: ast.Number) -> Tuple[str, int]:
        return e.text, P_ATOM

    def _expr_String(self, e: ast.String) -> Tuple[str, int]:
        return json.dumps(e.value, ensure_ascii=False), P_ATOM

    def _expr_Boolean(self, e: ast.Boolean) -> Tuple[str, int]:
        return ("true" if e.value else "false"), P_ATOM

    def _expr_NoneLiteral(self, e: ast.NoneLiteral) -> Tuple[str, int]:
        return "null", P_ATOM

    def _expr_Name(self, e: ast.Name) -> Tuple[str, int]:
        return ident(e.id), P_ATOM

    def _expr_ListLiteral(self, e: ast.ListLiteral) -> Tuple[str, int]:
        return "[" + ", ".join(self._text(x) for x in e.elements) + "]", P_ATOM

    def _expr_Attribute(self, e: ast.Attribute) -> Tuple[str, int]:
        return f"{self._child(e.value, P_POSTFIX)}.{e.attr}", P_POSTFIX

    def _expr_Subscript(self, e: ast.Subscript) -> Tuple[str, int]:
        base = self._child(e.value, P_POSTFIX)
        neg = _negative_literal(e.index)
        if neg is not None:
            return f"{base}.at(-{neg})", P_POSTFIX
        return f"{base}[{self._text(e.index)}]", P_POSTFIX

    def _expr_UnaryOp(self, e: ast.UnaryOp) -> Tuple[str, int]:
        operand = self._child(e.operand, P_UNARY)
        if e.op == "not":
            return f"!{operand}", P_UNARY
        if operand.startswith(e.op):  # avoid emitting `--x` / `++x`
            operand = f"({operand})"
        return f"{e.op}{operand}", P_UNARY

    def _expr_BinaryOp(self, e: ast.BinaryOp) -> Tuple[str, int]:
        if e.op == "//":
            left = self._child(e.left, P_MUL)
            right = self._child(e.right, P_MUL + 1)
            return f"Math.floor({left} / {right})", P_POSTFIX
        if e.op == "%":
            self._uses_mod = True
            return f"__mod({self._text(e.left)}, {self._text(e.right)})", P_POSTFIX
        if e.op == "**":
            left = self._child(e.left, P_POW + 1)
            if isinstance(e.left, ast.UnaryOp):  # JS forbids a bare unary base before **
                left = f"({self._text(e.left)})"
            return f"{left} ** {self._child(e.right, P_POW)}", P_POW
        prec = P_ADD if e.op in ("+", "-") else P_MUL
        return f"{self._child(e.left, prec)} {e.op} {self._child(e.right, prec + 1)}", prec

    def _expr_BoolOp(self, e: ast.BoolOp) -> Tuple[str, int]:
        prec, op = (P_AND, "&&") if e.op == "and" else (P_OR, "||")
        return f" {op} ".join(self._child(v, prec) for v in e.values), prec

    def _expr_Compare(self, e: ast.Compare) -> Tuple[str, int]:
        operands = (e.left, *e.comparators)
        if len(e.ops) > 1:
            for middle in operands[1:-1]:
                if not _is_pure(middle):
                    raise TranspileError(
                        "Chained comparison needs side-effect-free middle operands", e.line)
        parts: List[str] = []
        for index, op in enumerate(e.ops):
            prec = P_EQ if op in ("==", "!=") else P_REL
            left = self._child(operands[index], prec)
            right = self._child(operands[index + 1], prec + 1)
            parts.append(f"{left} {CMP_MAP[op]} {right}")
        if len(parts) == 1:
            return parts[0], (P_EQ if e.ops[0] in ("==", "!=") else P_REL)
        return " && ".join(parts), P_AND

    def _expr_Call(self, e: ast.Call) -> Tuple[str, int]:
        args = [self._text(a) for a in e.args]
        func = e.func
        if isinstance(func, ast.Name):
            name = func.id
            if name == "print":
                return f"console.log({', '.join(args)})", P_POSTFIX
            if name == "len":
                self._require_args(e, 1, 1)
                return f"{self._child(e.args[0], P_POSTFIX)}.length", P_POSTFIX
            if name in ("abs", "str", "float"):
                self._require_args(e, 1, 1)
                js = {"abs": "Math.abs", "str": "String", "float": "Number"}[name]
                return f"{js}({args[0]})", P_POSTFIX
            if name == "int":
                self._require_args(e, 1, 1)
                return f"Math.trunc(Number({args[0]}))", P_POSTFIX
            if name in ("min", "max"):
                self._require_args(e, 2, None)
                return f"Math.{name}({', '.join(args)})", P_POSTFIX
            if name == "range":
                raise TranspileError("range() is only supported as a for-loop iterable", e.line)
            return f"{ident(name)}({', '.join(args)})", P_POSTFIX
        if isinstance(func, ast.Attribute):
            attr = METHOD_MAP.get(func.attr, func.attr)
            return f"{self._child(func.value, P_POSTFIX)}.{attr}({', '.join(args)})", P_POSTFIX
        return f"{self._child(func, P_POSTFIX)}({', '.join(args)})", P_POSTFIX

    @staticmethod
    def _require_args(call: ast.Call, low: int, high: int | None) -> None:
        count = len(call.args)
        if count < low or (high is not None and count > high):
            name = call.func.id if isinstance(call.func, ast.Name) else "call"
            raise TranspileError(f"Wrong number of arguments to {name}()", call.line)


def generate(module: ast.Module) -> str:
    return Generator().generate(module)
