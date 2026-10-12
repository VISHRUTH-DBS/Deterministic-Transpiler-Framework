"""Recursive-descent parser: Python tokens -> typed AST.

Expression grammar, lowest to highest precedence:

    or_expr    := and_expr ('or' and_expr)*
    and_expr   := not_expr ('and' not_expr)*
    not_expr   := 'not' not_expr | comparison
    comparison := arith (CMP arith)*              # chains allowed: a < b < c
    arith      := term (('+'|'-') term)*
    term       := factor (('*'|'/'|'//'|'%') factor)*
    factor     := ('-'|'+') factor | power
    power      := postfix ['**' factor]           # right associative
    postfix    := atom ( '(' args ')' | '[' expr ']' | '.' NAME )*
    atom       := NUMBER | STRING | True | False | None | NAME | '(' expr ')' | '[' list ']'
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..core import Token, TokenStream, TranspileError
from . import ast_nodes as ast
from .lexer import tokenize

_COMPARE_OPS = {"==", "!=", "<", ">", "<=", ">="}
_AUG_OPS = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "//=": "//", "%=": "%", "**=": "**"}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", "'": "'", '"': '"'}


def unescape_string(literal: str, token: Token) -> str:
    """Decode the body of a quoted Python string literal."""
    body = literal[1:-1]
    out: List[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        esc = body[i]
        if esc not in _ESCAPES:
            raise TranspileError(f"Unsupported escape sequence '\\{esc}'", token.line, token.col)
        out.append(_ESCAPES[esc])
        i += 1
    return "".join(out)


class Parser:
    def __init__(self, tokens: List[Token]) -> None:
        self.ts = TokenStream(tokens)
        self._function_depth = 0
        self._loop_depth = 0

    # ------------------------------------------------------------- statements
    def parse_module(self) -> ast.Module:
        body: List[ast.Stmt] = []
        while not self.ts.at("EOF"):
            body.append(self.statement())
        return ast.Module(body=tuple(body), line=1)

    def block(self) -> Tuple[ast.Stmt, ...]:
        self.ts.expect("OP", ":")
        if self.ts.accept("NEWLINE"):
            self.ts.expect("INDENT")
            body: List[ast.Stmt] = []
            while not self.ts.at("DEDENT") and not self.ts.at("EOF"):
                body.append(self.statement())
            self.ts.expect("DEDENT")
            return tuple(body)
        return (self.simple_statement(),)  # one-line suite: `if x: y = 1`

    def statement(self) -> ast.Stmt:
        tok = self.ts.peek()
        if tok.kind == "INDENT":
            raise TranspileError("Unexpected indent", tok.line, tok.col)
        if tok.kind == "KEYWORD":
            if tok.value == "if":
                return self.if_statement()
            if tok.value == "while":
                return self.while_statement()
            if tok.value == "for":
                return self.for_statement()
            if tok.value == "def":
                return self.function_def()
        return self.simple_statement()

    def simple_statement(self) -> ast.Stmt:
        tok = self.ts.peek()
        stmt: ast.Stmt
        if tok.kind == "KEYWORD" and tok.value in ("return", "break", "continue", "pass"):
            self.ts.next()
            if tok.value == "return":
                if self._function_depth == 0:
                    raise TranspileError("'return' outside function", tok.line, tok.col)
                value = None if self.ts.at("NEWLINE") else self.expression()
                stmt = ast.Return(value=value, line=tok.line)
            elif tok.value == "pass":
                stmt = ast.Pass(line=tok.line)
            else:
                if self._loop_depth == 0:
                    raise TranspileError(f"'{tok.value}' outside loop", tok.line, tok.col)
                stmt = ast.Break(line=tok.line) if tok.value == "break" else ast.Continue(line=tok.line)
        else:
            stmt = self.expression_or_assignment()
        self.ts.expect("NEWLINE")
        return stmt

    def expression_or_assignment(self) -> ast.Stmt:
        first = self.ts.peek()
        expr = self.expression()
        if self.ts.at("OP", "="):
            self.ts.next()
            self._check_target(expr, first)
            return ast.Assign(target=expr, value=self.expression(), line=first.line)  # type: ignore[arg-type]
        op_tok = self.ts.peek()
        if op_tok.kind == "OP" and op_tok.value in _AUG_OPS:
            self.ts.next()
            self._check_target(expr, first)
            return ast.AugAssign(target=expr, op=_AUG_OPS[op_tok.value],  # type: ignore[arg-type]
                                 value=self.expression(), line=first.line)
        return ast.ExprStmt(value=expr, line=first.line)

    @staticmethod
    def _check_target(expr: ast.Expr, tok: Token) -> None:
        if not isinstance(expr, (ast.Name, ast.Subscript, ast.Attribute)):
            raise TranspileError("Invalid assignment target", tok.line, tok.col)

    def if_statement(self) -> ast.If:
        kw = self.ts.next()  # 'if' or 'elif'
        test = self.expression()
        body = self.block()
        orelse: Tuple[ast.Stmt, ...] = ()
        if self.ts.at("KEYWORD", "elif"):
            orelse = (self.if_statement(),)
        elif self.ts.accept("KEYWORD", "else"):
            orelse = self.block()
        return ast.If(test=test, body=body, orelse=orelse, line=kw.line)

    def while_statement(self) -> ast.While:
        kw = self.ts.next()
        test = self.expression()
        self._loop_depth += 1
        body = self.block()
        self._loop_depth -= 1
        return ast.While(test=test, body=body, line=kw.line)

    def for_statement(self) -> ast.Stmt:
        kw = self.ts.next()
        target = self.ts.expect("NAME").value
        self.ts.expect("KEYWORD", "in")
        iterable = self.expression()
        self._loop_depth += 1
        body = self.block()
        self._loop_depth -= 1
        if isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Name) \
                and iterable.func.id == "range":
            return self._range_loop(kw, target, iterable, body)
        return ast.ForIn(target=target, iterable=iterable, body=body, line=kw.line)

    @staticmethod
    def _range_loop(kw: Token, target: str, call: ast.Call, body: Tuple[ast.Stmt, ...]) -> ast.ForRange:
        args = call.args
        if not 1 <= len(args) <= 3:
            raise TranspileError("range() takes 1 to 3 arguments", kw.line, kw.col)
        start: Optional[ast.Expr] = None
        step = 1
        if len(args) == 1:
            stop = args[0]
        else:
            start, stop = args[0], args[1]
        if len(args) == 3:
            step_expr = args[2]
            sign = 1
            if isinstance(step_expr, ast.UnaryOp) and step_expr.op in ("-", "+"):
                sign = -1 if step_expr.op == "-" else 1
                step_expr = step_expr.operand
            if not (isinstance(step_expr, ast.Number) and step_expr.text.isdigit()
                    and int(step_expr.text) != 0):
                raise TranspileError("range() step must be a non-zero integer literal", kw.line, kw.col)
            step = sign * int(step_expr.text)
        return ast.ForRange(target=target, start=start, stop=stop, step=step, body=body, line=kw.line)

    def function_def(self) -> ast.FunctionDef:
        kw = self.ts.next()
        name = self.ts.expect("NAME").value
        self.ts.expect("OP", "(")
        params: List[str] = []
        if not self.ts.at("OP", ")"):
            params.append(self.ts.expect("NAME").value)
            while self.ts.accept("OP", ","):
                params.append(self.ts.expect("NAME").value)
        self.ts.expect("OP", ")")
        if len(set(params)) != len(params):
            raise TranspileError(f"Duplicate parameter in '{name}'", kw.line, kw.col)
        saved_loop, self._loop_depth = self._loop_depth, 0
        self._function_depth += 1
        body = self.block()
        self._function_depth -= 1
        self._loop_depth = saved_loop
        return ast.FunctionDef(name=name, params=tuple(params), body=body, line=kw.line)

    # ------------------------------------------------------------ expressions
    def expression(self) -> ast.Expr:
        return self.or_expr()

    def or_expr(self) -> ast.Expr:
        first = self.and_expr()
        values = [first]
        while self.ts.accept("KEYWORD", "or"):
            values.append(self.and_expr())
        return first if len(values) == 1 else ast.BoolOp(op="or", values=tuple(values), line=first.line)

    def and_expr(self) -> ast.Expr:
        first = self.not_expr()
        values = [first]
        while self.ts.accept("KEYWORD", "and"):
            values.append(self.not_expr())
        return first if len(values) == 1 else ast.BoolOp(op="and", values=tuple(values), line=first.line)

    def not_expr(self) -> ast.Expr:
        tok = self.ts.accept("KEYWORD", "not")
        if tok:
            return ast.UnaryOp(op="not", operand=self.not_expr(), line=tok.line)
        return self.comparison()

    def comparison(self) -> ast.Expr:
        left = self.arith()
        ops: List[str] = []
        rights: List[ast.Expr] = []
        while self.ts.peek().kind == "OP" and self.ts.peek().value in _COMPARE_OPS:
            ops.append(self.ts.next().value)
            rights.append(self.arith())
        if not ops:
            return left
        return ast.Compare(left=left, ops=tuple(ops), comparators=tuple(rights), line=left.line)

    def arith(self) -> ast.Expr:
        left = self.term()
        while self.ts.peek().kind == "OP" and self.ts.peek().value in ("+", "-"):
            op = self.ts.next().value
            left = ast.BinaryOp(op=op, left=left, right=self.term(), line=left.line)
        return left

    def term(self) -> ast.Expr:
        left = self.factor()
        while self.ts.peek().kind == "OP" and self.ts.peek().value in ("*", "/", "//", "%"):
            op = self.ts.next().value
            left = ast.BinaryOp(op=op, left=left, right=self.factor(), line=left.line)
        return left

    def factor(self) -> ast.Expr:
        tok = self.ts.peek()
        if tok.kind == "OP" and tok.value in ("-", "+"):
            self.ts.next()
            return ast.UnaryOp(op=tok.value, operand=self.factor(), line=tok.line)
        return self.power()

    def power(self) -> ast.Expr:
        base = self.postfix()
        if self.ts.accept("OP", "**"):
            return ast.BinaryOp(op="**", left=base, right=self.factor(), line=base.line)
        return base

    def postfix(self) -> ast.Expr:
        expr = self.atom()
        while True:
            if self.ts.accept("OP", "("):
                args: List[ast.Expr] = []
                if not self.ts.at("OP", ")"):
                    args.append(self.expression())
                    while self.ts.accept("OP", ","):
                        if self.ts.at("OP", ")"):
                            break
                        args.append(self.expression())
                self.ts.expect("OP", ")")
                expr = ast.Call(func=expr, args=tuple(args), line=expr.line)
            elif self.ts.accept("OP", "["):
                index = self.expression()
                self.ts.expect("OP", "]")
                expr = ast.Subscript(value=expr, index=index, line=expr.line)
            elif self.ts.accept("OP", "."):
                expr = ast.Attribute(value=expr, attr=self.ts.expect("NAME").value, line=expr.line)
            else:
                return expr

    def atom(self) -> ast.Expr:
        tok = self.ts.next()
        if tok.kind == "NUMBER":
            return ast.Number(text=tok.value, line=tok.line)
        if tok.kind == "STRING":
            return ast.String(value=unescape_string(tok.value, tok), line=tok.line)
        if tok.kind == "NAME":
            return ast.Name(id=tok.value, line=tok.line)
        if tok.kind == "KEYWORD" and tok.value in ("True", "False"):
            return ast.Boolean(value=tok.value == "True", line=tok.line)
        if tok.kind == "KEYWORD" and tok.value == "None":
            return ast.NoneLiteral(line=tok.line)
        if tok.kind == "OP" and tok.value == "(":
            inner = self.expression()
            self.ts.expect("OP", ")")
            return inner
        if tok.kind == "OP" and tok.value == "[":
            elements: List[ast.Expr] = []
            if not self.ts.at("OP", "]"):
                elements.append(self.expression())
                while self.ts.accept("OP", ","):
                    if self.ts.at("OP", "]"):
                        break
                    elements.append(self.expression())
            self.ts.expect("OP", "]")
            return ast.ListLiteral(elements=tuple(elements), line=tok.line)
        found = f"{tok.kind} {tok.value!r}" if tok.value else tok.kind
        raise TranspileError(f"Unexpected {found} in expression", tok.line, tok.col)


def parse(source: str) -> ast.Module:
    return Parser(tokenize(source)).parse_module()
