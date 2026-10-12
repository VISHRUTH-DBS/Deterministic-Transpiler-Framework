"""Recursive-descent parser: TypeScript tokens -> typed AST (types included)."""

from __future__ import annotations

from typing import List, Optional, Tuple, Union

from ..core import Token, TokenStream, TranspileError
from . import ts_ast as t
from .lexer import tokenize
from .type_parser import TypeParserMixin

BINARY_PREC = {
    "??": 1, "||": 2, "&&": 3, "|": 4, "^": 5, "&": 6,
    "==": 7, "!=": 7, "===": 7, "!==": 7,
    "<": 8, ">": 8, "<=": 8, ">=": 8, "instanceof": 8, "in": 8, "as": 8, "satisfies": 8,
    "<<": 9, ">>": 9, ">>>": 9,
    "+": 10, "-": 10, "*": 11, "/": 11, "%": 11, "**": 12,
}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "**=", "&&=", "||=", "??=",
              "<<=", ">>=", ">>>=", "&=", "|=", "^="}
UNARY_OPS = {"!", "-", "+", "~"}
UNARY_WORDS = {"typeof", "void", "delete"}
UNSUPPORTED = {
    "class": "classes", "enum": "enums (they are not erasable; they need code generation)",
    "namespace": "namespaces", "module": "modules", "abstract": "abstract classes",
}


class Parser(TypeParserMixin):
    def __init__(self, tokens: List[Token]) -> None:
        self.ts = TokenStream(tokens)

    # ------------------------------------------------------------------ helpers
    def _error(self, message: str, tok: Optional[Token] = None) -> TranspileError:
        tok = tok or self.ts.peek()
        return TranspileError(message, tok.line, tok.col)

    def _consume_semicolon(self) -> None:
        if self.ts.accept("OP", ";"):
            return
        tok, prev = self.ts.peek(), self.ts.previous()
        if tok.kind == "EOF" or (tok.kind == "OP" and tok.value == "}") \
                or (prev is not None and tok.line > prev.line):
            return  # automatic semicolon insertion
        raise self._error(f"Expected ';' but found {tok.value!r}", tok)

    def _is_name(self, value: str, offset: int = 0) -> bool:
        tok = self.ts.peek(offset)
        return tok.kind == "NAME" and tok.value == value

    # --------------------------------------------------------------- statements
    def parse_program(self) -> t.Program:
        body: List[t.Stmt] = []
        while not self.ts.at("EOF"):
            if self.ts.accept("OP", ";"):
                continue
            body.append(self.statement())
        return t.Program(body=tuple(body), line=1)

    def block(self) -> Tuple[t.Stmt, ...]:
        self.ts.expect("OP", "{")
        body: List[t.Stmt] = []
        while not self.ts.at("OP", "}"):
            if self.ts.at("EOF"):
                raise self._error("Unterminated block: expected '}'")
            if self.ts.accept("OP", ";"):
                continue
            body.append(self.statement())
        self.ts.expect("OP", "}")
        return tuple(body)

    def _body(self) -> Tuple[t.Stmt, ...]:
        if self.ts.at("OP", "{"):
            return self.block()
        return (self.statement(),)

    def statement(self) -> t.Stmt:
        tok = self.ts.peek()
        if tok.kind == "OP" and tok.value == "{":
            return t.BlockStatement(body=self.block(), line=tok.line)
        if tok.kind == "NAME":
            word = tok.value
            exported = False
            if word == "export":
                self.ts.next()
                exported = True
                word = self.ts.peek().value
                if word == "default":
                    raise self._error("'export default' is not supported")
            if word in ("let", "const", "var") and not (word == "const" and self._is_name("enum", 1)):
                decl = self._variable_declaration(exported)
                self._consume_semicolon()
                return decl
            if word == "function":
                return self._function_declaration(exported)
            if word == "interface" and self.ts.peek(1).kind == "NAME":
                return self._interface(exported)
            if word == "type" and self.ts.peek(1).kind == "NAME" and \
                    self.ts.peek(2).kind == "OP" and self.ts.peek(2).value in ("=", "<"):
                return self._type_alias(exported)
            if word == "declare" and not exported:
                self.ts.next()
                return t.AmbientDeclaration(inner=self.statement(), line=tok.line)
            if word == "import" and not exported:
                return self._import()
            if word in UNSUPPORTED:
                raise self._error(f"{UNSUPPORTED[word]} are not supported by this subset", self.ts.peek())
            if exported:
                raise self._error("Unsupported export form")
            if word == "if":
                return self._if()
            if word == "while":
                self.ts.next()
                self.ts.expect("OP", "(")
                test = self.expression()
                self.ts.expect("OP", ")")
                return t.WhileStatement(test=test, body=self._body(), line=tok.line)
            if word == "for":
                return self._for()
            if word == "return":
                self.ts.next()
                nxt = self.ts.peek()
                if (nxt.kind == "OP" and nxt.value in (";", "}")) or nxt.kind == "EOF" or nxt.line > tok.line:
                    value = None
                else:
                    value = self.expression()
                self._consume_semicolon()
                return t.ReturnStatement(value=value, line=tok.line)
            if word in ("break", "continue"):
                self.ts.next()
                self._consume_semicolon()
                cls = t.BreakStatement if word == "break" else t.ContinueStatement
                return cls(line=tok.line)
        expr = self.expression()
        self._consume_semicolon()
        return t.ExpressionStatement(expression=expr, line=tok.line)

    def _variable_declaration(self, exported: bool = False) -> t.VariableDeclaration:
        kind_tok = self.ts.next()
        decls: List[t.Declarator] = []
        while True:
            name_tok = self.ts.peek()
            if name_tok.kind != "NAME":
                raise self._error("Destructuring patterns are not supported; expected a variable name", name_tok)
            self.ts.next()
            definite = self.ts.accept("OP", "!") is not None
            annotation = self.parse_type() if self.ts.accept("OP", ":") else None
            init = self.assignment() if self.ts.accept("OP", "=") else None
            decls.append(t.Declarator(name=name_tok.value, annotation=annotation, init=init,
                                      definite=definite, line=name_tok.line))
            if not self.ts.accept("OP", ","):
                break
        return t.VariableDeclaration(kind=kind_tok.value, declarations=tuple(decls),
                                     exported=exported, line=kind_tok.line)

    def _function_declaration(self, exported: bool) -> t.FunctionDeclaration:
        kw = self.ts.expect("NAME", "function")
        name = self.ts.expect("NAME").value
        type_params = self.type_params()
        self.ts.expect("OP", "(")
        params = self._params()
        self.ts.expect("OP", ")")
        return_type = self.parse_type() if self.ts.accept("OP", ":") else None
        body: Optional[Tuple[t.Stmt, ...]] = None
        if self.ts.at("OP", "{"):
            body = self.block()
        else:
            self._consume_semicolon()  # overload signature
        return t.FunctionDeclaration(name=name, type_params=type_params, params=params,
                                     return_type=return_type, body=body, exported=exported,
                                     line=kw.line)

    def _params(self) -> Tuple[t.Param, ...]:
        params: List[t.Param] = []
        while not self.ts.at("OP", ")"):
            rest = self.ts.accept("OP", "...") is not None
            name_tok = self.ts.expect("NAME")
            optional = self.ts.accept("OP", "?") is not None
            annotation = self.parse_type() if self.ts.accept("OP", ":") else None
            default = self.assignment() if self.ts.accept("OP", "=") else None
            params.append(t.Param(name=name_tok.value, optional=optional, annotation=annotation,
                                  default=default, rest=rest, line=name_tok.line))
            if not self.ts.accept("OP", ","):
                break
        return tuple(params)

    def _interface(self, exported: bool) -> t.InterfaceDeclaration:
        kw = self.ts.next()
        name = self.ts.expect("NAME").value
        type_params = self.type_params()
        extends: List[t.TypeNode] = []
        if self.ts.accept("NAME", "extends"):
            extends.append(self.parse_type())
            while self.ts.accept("OP", ","):
                extends.append(self.parse_type())
        return t.InterfaceDeclaration(name=name, type_params=type_params, extends=tuple(extends),
                                      members=self.type_members(), exported=exported, line=kw.line)

    def _type_alias(self, exported: bool) -> t.TypeAliasDeclaration:
        kw = self.ts.next()
        name = self.ts.expect("NAME").value
        type_params = self.type_params()
        self.ts.expect("OP", "=")
        aliased = self.parse_type()
        self._consume_semicolon()
        return t.TypeAliasDeclaration(name=name, type_params=type_params, type=aliased,
                                      exported=exported, line=kw.line)

    def _import(self) -> t.ImportDeclaration:
        kw = self.ts.next()
        type_only = False
        if self._is_name("type") and (self.ts.peek(1).value == "{" or
                                      (self.ts.peek(1).kind == "NAME" and self.ts.peek(1).value != "from")):
            self.ts.next()
            type_only = True
        default: Optional[str] = None
        specifiers: List[t.ImportSpecifier] = []
        if self.ts.peek().kind == "STRING":
            source = self.ts.next().value
            self._consume_semicolon()
            return t.ImportDeclaration(type_only=False, default=None, specifiers=(),
                                       source=source, line=kw.line)
        if self.ts.peek().kind == "NAME":
            default = self.ts.next().value
            self.ts.accept("OP", ",")
        if self.ts.at("OP", "*"):
            raise self._error("Namespace imports are not supported")
        if self.ts.accept("OP", "{"):
            while not self.ts.at("OP", "}"):
                spec_type_only = False
                if self._is_name("type") and self.ts.peek(1).kind == "NAME" \
                        and self.ts.peek(1).value != "as":
                    self.ts.next()
                    spec_type_only = True
                name = self.ts.expect("NAME").value
                alias = self.ts.expect("NAME").value if self.ts.accept("NAME", "as") else None
                specifiers.append(t.ImportSpecifier(name=name, alias=alias, type_only=spec_type_only))
                if not self.ts.accept("OP", ","):
                    break
            self.ts.expect("OP", "}")
        self.ts.expect("NAME", "from")
        source = self.ts.expect("STRING").value
        self._consume_semicolon()
        return t.ImportDeclaration(type_only=type_only, default=default,
                                   specifiers=tuple(specifiers), source=source, line=kw.line)

    def _if(self) -> t.IfStatement:
        kw = self.ts.next()
        self.ts.expect("OP", "(")
        test = self.expression()
        self.ts.expect("OP", ")")
        consequent = self._body()
        alternate: Optional[Tuple[t.Stmt, ...]] = None
        if self.ts.accept("NAME", "else"):
            alternate = (self._if(),) if self._is_name("if") else self._body()
        return t.IfStatement(test=test, consequent=consequent, alternate=alternate, line=kw.line)

    def _for(self) -> t.Stmt:
        kw = self.ts.next()
        self.ts.expect("OP", "(")
        init: Optional[Union[t.VariableDeclaration, t.Expr]] = None
        if self.ts.peek().kind == "NAME" and self.ts.peek().value in ("let", "const", "var") \
                and self.ts.peek(1).kind == "NAME" and self.ts.peek(2).kind == "NAME" \
                and self.ts.peek(2).value in ("of", "in"):
            kind = self.ts.next().value
            name = self.ts.next().value
            iteration = self.ts.next().value
            iterable = self.expression()
            self.ts.expect("OP", ")")
            return t.ForEachStatement(kind=kind, name=name, iteration=iteration,
                                      iterable=iterable, body=self._body(), line=kw.line)
        if not self.ts.at("OP", ";"):
            if self.ts.peek().kind == "NAME" and self.ts.peek().value in ("let", "const", "var"):
                init = self._variable_declaration()
            else:
                init = self.expression()
        self.ts.expect("OP", ";")
        test = None if self.ts.at("OP", ";") else self.expression()
        self.ts.expect("OP", ";")
        update = None if self.ts.at("OP", ")") else self.expression()
        self.ts.expect("OP", ")")
        return t.ForStatement(init=init, test=test, update=update, body=self._body(), line=kw.line)

    # -------------------------------------------------------------- expressions
    def expression(self) -> t.Expr:
        return self.assignment()

    def _looks_like_arrow(self) -> bool:
        tok = self.ts.peek()
        if tok.kind == "NAME":
            return self.ts.peek(1).kind == "OP" and self.ts.peek(1).value == "=>"
        if tok.kind == "OP" and tok.value == "<":
            return True
        if tok.kind == "OP" and tok.value == "(":
            close = self._matching_close()
            if close < 0:
                return False
            nxt = self.ts.peek(close + 1)
            return nxt.kind == "OP" and nxt.value in ("=>", ":")
        return False

    def _try_arrow(self) -> Optional[t.ArrowFunction]:
        mark = self.ts.mark()
        first = self.ts.peek()
        try:
            type_params = self.type_params()
            if self.ts.peek().kind == "NAME" and not type_params:
                name_tok = self.ts.next()
                params: Tuple[t.Param, ...] = (t.Param(name=name_tok.value, line=name_tok.line),)
                return_type = None
            else:
                self.ts.expect("OP", "(")
                params = self._params()
                self.ts.expect("OP", ")")
                return_type = self.parse_type() if self.ts.accept("OP", ":") else None
            self.ts.expect("OP", "=>")
        except TranspileError:
            self.ts.reset(mark)
            return None
        if self.ts.at("OP", "{"):
            return t.ArrowFunction(type_params=type_params, params=params, return_type=return_type,
                                   body=self.block(), expression_body=False, line=first.line)
        return t.ArrowFunction(type_params=type_params, params=params, return_type=return_type,
                               body=self.assignment(), expression_body=True, line=first.line)

    def assignment(self) -> t.Expr:
        if self._looks_like_arrow():
            arrow = self._try_arrow()
            if arrow is not None:
                return arrow
        left = self._conditional()
        tok = self.ts.peek()
        op = self._assign_operator()
        if op is not None:
            if not isinstance(left, (t.Identifier, t.Member, t.Index)):
                raise self._error("Invalid assignment target", tok)
            return t.Assignment(op=op[0], target=left, value=self.assignment(), line=left.line)
        return left

    def _assign_operator(self) -> Optional[Tuple[str, int]]:
        tok = self.ts.peek()
        if tok.kind != "OP":
            return None
        if tok.value in ASSIGN_OPS:
            self.ts.next()
            return tok.value, 1
        merged = self._merged_greater(consume=False)
        if merged is not None and merged[0] in (">>=", ">>>="):
            self._merged_greater(consume=True)
            return merged
        return None

    def _merged_greater(self, consume: bool) -> Optional[Tuple[str, int]]:
        """Re-join adjacent '>' / '=' tokens into >>, >>>, >=, >>=, >>>=."""
        first = self.ts.peek()
        if not (first.kind == "OP" and first.value == ">"):
            return None
        text, count, last = ">", 1, first
        while count < 3:
            nxt = self.ts.peek(count)
            if nxt.kind == "OP" and nxt.value == ">" and nxt.line == last.line and nxt.col == last.col + 1:
                text += ">"
                count += 1
                last = nxt
            else:
                break
        nxt = self.ts.peek(count)
        if nxt.kind == "OP" and nxt.value == "=" and nxt.line == last.line and nxt.col == last.col + 1:
            text += "="
            count += 1
        if consume:
            for _ in range(count):
                self.ts.next()
        return text, count

    def _conditional(self) -> t.Expr:
        test = self._binary(1)
        if self.ts.at("OP", "?"):
            self.ts.next()
            consequent = self.assignment()
            self.ts.expect("OP", ":")
            alternate = self.assignment()
            return t.Conditional(test=test, consequent=consequent, alternate=alternate, line=test.line)
        return test

    def _binary_operator(self) -> Optional[Tuple[str, int]]:
        tok = self.ts.peek()
        if tok.kind == "NAME" and tok.value in ("instanceof", "in", "as", "satisfies"):
            return tok.value, 1
        if tok.kind != "OP":
            return None
        if tok.value == ">":
            merged = self._merged_greater(consume=False)
            if merged is not None and merged[0] in (">", ">=", ">>", ">>>"):
                return merged
            return None
        if tok.value in BINARY_PREC:
            return tok.value, 1
        return None

    def _binary(self, min_prec: int) -> t.Expr:
        left = self._unary()
        while True:
            found = self._binary_operator()
            if found is None:
                return left
            op, count = found
            prec = BINARY_PREC[op]
            if prec < min_prec:
                return left
            for _ in range(count):
                self.ts.next()
            if op in ("as", "satisfies"):
                left = t.AsExpression(expression=left, type=self.parse_type(), keyword=op, line=left.line)
                continue
            right = self._binary(prec if op == "**" else prec + 1)
            left = t.Binary(op=op, left=left, right=right, line=left.line)

    def _unary(self) -> t.Expr:
        tok = self.ts.peek()
        if tok.kind == "OP" and tok.value in UNARY_OPS:
            self.ts.next()
            return t.Unary(op=tok.value, operand=self._unary(), line=tok.line)
        if tok.kind == "NAME" and tok.value in UNARY_WORDS:
            self.ts.next()
            return t.Unary(op=tok.value, operand=self._unary(), line=tok.line)
        if tok.kind == "OP" and tok.value in ("++", "--"):
            self.ts.next()
            return t.Update(op=tok.value, operand=self._unary(), prefix=True, line=tok.line)
        return self._postfix()

    def _arguments(self) -> Tuple[t.Expr, ...]:
        self.ts.expect("OP", "(")
        args: List[t.Expr] = []
        while not self.ts.at("OP", ")"):
            if self.ts.accept("OP", "..."):
                args.append(t.SpreadElement(argument=self.assignment()))
            else:
                args.append(self.assignment())
            if not self.ts.accept("OP", ","):
                break
        self.ts.expect("OP", ")")
        return tuple(args)

    def _try_type_arguments(self) -> Optional[Tuple[t.TypeNode, ...]]:
        """Speculatively parse `<T, U>` that must be followed by '(' (a generic call)."""
        mark = self.ts.mark()
        try:
            args = self.type_args()
            if self.ts.at("OP", "("):
                return args
        except TranspileError:
            pass
        self.ts.reset(mark)
        return None

    def _postfix(self) -> t.Expr:
        if self._is_name("new"):
            expr = self._new()
        else:
            expr = self._primary()
        while True:
            tok = self.ts.peek()
            if tok.kind != "OP":
                return expr
            prev = self.ts.previous()
            same_line = prev is not None and tok.line == prev.line
            if tok.value == ".":
                self.ts.next()
                expr = t.Member(obj=expr, prop=self.ts.expect("NAME").value, line=expr.line)
            elif tok.value == "?.":
                self.ts.next()
                if self.ts.peek().kind != "NAME":
                    raise self._error("Only `?.name` optional chaining is supported")
                expr = t.Member(obj=expr, prop=self.ts.next().value, optional=True, line=expr.line)
            elif tok.value == "[":
                self.ts.next()
                index = self.expression()
                self.ts.expect("OP", "]")
                expr = t.Index(obj=expr, index=index, line=expr.line)
            elif tok.value == "(":
                expr = t.Call(callee=expr, type_args=(), args=self._arguments(), line=expr.line)
            elif tok.value == "<":
                type_args = self._try_type_arguments()
                if type_args is None:
                    return expr
                expr = t.Call(callee=expr, type_args=type_args, args=self._arguments(), line=expr.line)
            elif tok.value == "!" and same_line:
                self.ts.next()
                expr = t.NonNullExpression(expression=expr, line=expr.line)
            elif tok.value in ("++", "--") and same_line:
                self.ts.next()
                expr = t.Update(op=tok.value, operand=expr, prefix=False, line=expr.line)
            else:
                return expr

    def _new(self) -> t.Expr:
        kw = self.ts.expect("NAME", "new")
        callee: t.Expr = self._primary()
        while self.ts.at("OP", ".") or self.ts.at("OP", "["):
            if self.ts.accept("OP", "."):
                callee = t.Member(obj=callee, prop=self.ts.expect("NAME").value, line=kw.line)
            else:
                self.ts.next()
                index = self.expression()
                self.ts.expect("OP", "]")
                callee = t.Index(obj=callee, index=index, line=kw.line)
        type_args: Tuple[t.TypeNode, ...] = ()
        if self.ts.at("OP", "<"):
            found = self._try_type_arguments()
            if found is not None:
                type_args = found
        args = self._arguments() if self.ts.at("OP", "(") else ()
        return t.New(callee=callee, type_args=type_args, args=args, line=kw.line)

    def _primary(self) -> t.Expr:
        tok = self.ts.next()
        if tok.kind == "NUMBER":
            return t.NumberLiteral(text=tok.value, line=tok.line)
        if tok.kind == "STRING":
            return t.StringLiteral(raw=tok.value, line=tok.line)
        if tok.kind == "TEMPLATE":
            return t.TemplateLiteral(raw=tok.value, line=tok.line)
        if tok.kind == "NAME":
            if tok.value in ("true", "false"):
                return t.BooleanLiteral(value=tok.value == "true", line=tok.line)
            if tok.value == "null":
                return t.NullLiteral(line=tok.line)
            if tok.value == "function":
                return self._function_expression(tok)
            return t.Identifier(name=tok.value, line=tok.line)
        if tok.kind == "OP" and tok.value == "(":
            inner = self.expression()
            self.ts.expect("OP", ")")
            return inner
        if tok.kind == "OP" and tok.value == "[":
            elements: List[t.Expr] = []
            while not self.ts.at("OP", "]"):
                if self.ts.accept("OP", "..."):
                    elements.append(t.SpreadElement(argument=self.assignment()))
                else:
                    elements.append(self.assignment())
                if not self.ts.accept("OP", ","):
                    break
            self.ts.expect("OP", "]")
            return t.ArrayLiteral(elements=tuple(elements), line=tok.line)
        if tok.kind == "OP" and tok.value == "{":
            return self._object_literal(tok)
        found = f"{tok.kind} {tok.value!r}" if tok.value else tok.kind
        raise TranspileError(f"Unexpected {found} in expression", tok.line, tok.col)

    def _function_expression(self, kw: Token) -> t.FunctionExpression:
        name = self.ts.next().value if self.ts.peek().kind == "NAME" else None
        type_params = self.type_params()
        self.ts.expect("OP", "(")
        params = self._params()
        self.ts.expect("OP", ")")
        return_type = self.parse_type() if self.ts.accept("OP", ":") else None
        return t.FunctionExpression(name=name, type_params=type_params, params=params,
                                    return_type=return_type, body=self.block(), line=kw.line)

    def _object_literal(self, open_tok: Token) -> t.ObjectLiteral:
        props: List[Union[t.Property, t.SpreadElement]] = []
        while not self.ts.at("OP", "}"):
            if self.ts.accept("OP", "..."):
                props.append(t.SpreadElement(argument=self.assignment()))
            else:
                key_tok = self.ts.next()
                if key_tok.kind not in ("NAME", "STRING", "NUMBER"):
                    raise self._error("Unsupported object literal key", key_tok)
                if self.ts.accept("OP", ":"):
                    props.append(t.Property(key=key_tok.value, value=self.assignment(), line=key_tok.line))
                elif key_tok.kind == "NAME" and self.ts.peek().kind == "OP" \
                        and self.ts.peek().value in (",", "}"):
                    props.append(t.Property(key=key_tok.value,
                                            value=t.Identifier(name=key_tok.value, line=key_tok.line),
                                            shorthand=True, line=key_tok.line))
                else:
                    raise self._error("Object methods and accessors are not supported; use `key: value`")
            if not self.ts.accept("OP", ","):
                break
        self.ts.expect("OP", "}")
        return t.ObjectLiteral(properties=tuple(props), line=open_tok.line)


def parse(source: str) -> t.Program:
    return Parser(tokenize(source)).parse_program()
