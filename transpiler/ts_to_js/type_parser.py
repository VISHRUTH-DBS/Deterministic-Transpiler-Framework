"""Type-syntax half of the TypeScript parser (a mixin used by `Parser`).

Types are parsed into real AST nodes (not skipped by bracket counting) so that
malformed type syntax is reported, and so the eraser operates on a faithful tree.
"""

from __future__ import annotations

from typing import List, Optional, Tuple, Union

from ..core import Token, TokenStream, TranspileError
from . import ts_ast as t

_LITERAL_WORDS = {"true", "false", "null"}


class TypeParserMixin:
    ts: TokenStream

    # -- helpers supplied by the concrete parser
    def _params(self) -> Tuple[t.Param, ...]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _matching_close(self, offset: int = 0) -> int:
        """Index offset (relative to peek) of the bracket matching the one at `offset`."""
        depth = 0
        i = offset
        while True:
            tok = self.ts.peek(i)
            if tok.kind == "EOF":
                return -1
            if tok.kind == "OP" and tok.value in "([{":
                depth += 1
            elif tok.kind == "OP" and tok.value in ")]}":
                depth -= 1
                if depth == 0:
                    return i
            i += 1

    # ----------------------------------------------------------------- generics
    def type_params(self) -> Tuple[t.TypeParameter, ...]:
        if not self.ts.at("OP", "<"):
            return ()
        self.ts.next()
        params: List[t.TypeParameter] = []
        while True:
            name_tok = self.ts.expect("NAME")
            constraint = default = None
            if self.ts.accept("NAME", "extends"):
                constraint = self.parse_type()
            if self.ts.accept("OP", "="):
                default = self.parse_type()
            params.append(t.TypeParameter(name=name_tok.value, constraint=constraint,
                                          default=default, line=name_tok.line))
            if not self.ts.accept("OP", ",") or self.ts.at("OP", ">"):
                break  # a trailing comma (`<T,>`) is legal
        self.ts.expect("OP", ">")
        return tuple(params)

    def type_args(self) -> Tuple[t.TypeNode, ...]:
        self.ts.expect("OP", "<")
        args = [self.parse_type()]
        while self.ts.accept("OP", ","):
            args.append(self.parse_type())
        self.ts.expect("OP", ">")
        return tuple(args)

    # -------------------------------------------------------------------- types
    def parse_type(self) -> t.TypeNode:
        if self.ts.at("OP", "<"):
            return self._function_type()
        if self.ts.at("OP", "("):
            close = self._matching_close()
            nxt = self.ts.peek(close + 1) if close >= 0 else None
            if nxt is not None and nxt.kind == "OP" and nxt.value == "=>":
                return self._function_type()
        return self._union_type()

    def _function_type(self) -> t.FunctionType:
        line = self.ts.peek().line
        type_params = self.type_params()
        self.ts.expect("OP", "(")
        params = self._params()
        self.ts.expect("OP", ")")
        self.ts.expect("OP", "=>")
        return t.FunctionType(type_params=type_params, params=params,
                              returns=self.parse_type(), line=line)

    def _union_type(self) -> t.TypeNode:
        self.ts.accept("OP", "|")  # leading bar is allowed
        first = self._intersection_type()
        members = [first]
        while self.ts.accept("OP", "|"):
            members.append(self._intersection_type())
        return first if len(members) == 1 else t.UnionType(types=tuple(members), line=first.line)

    def _intersection_type(self) -> t.TypeNode:
        self.ts.accept("OP", "&")
        first = self._postfix_type()
        members = [first]
        while self.ts.accept("OP", "&"):
            members.append(self._postfix_type())
        return first if len(members) == 1 else t.IntersectionType(types=tuple(members), line=first.line)

    def _postfix_type(self) -> t.TypeNode:
        node = self._primary_type()
        while self.ts.at("OP", "["):
            prev = self.ts.previous()
            if prev is not None and self.ts.peek().line != prev.line:
                break  # `[` on a new line starts the next member, not an array suffix
            self.ts.next()
            if self.ts.accept("OP", "]"):
                node = t.ArrayType(element=node, line=node.line)
            else:
                index = self.parse_type()
                self.ts.expect("OP", "]")
                node = t.IndexedAccessType(obj=node, index=index, line=node.line)
        return node

    def _dotted_name(self) -> str:
        parts = [self.ts.expect("NAME").value]
        while self.ts.at("OP", ".") and self.ts.peek(1).kind == "NAME":
            self.ts.next()
            parts.append(self.ts.next().value)
        return ".".join(parts)

    def _primary_type(self) -> t.TypeNode:
        tok = self.ts.peek()
        if tok.kind in ("NUMBER", "STRING", "TEMPLATE"):
            self.ts.next()
            return t.LiteralType(text=tok.value, line=tok.line)
        if tok.kind == "OP":
            if tok.value == "-" and self.ts.peek(1).kind == "NUMBER":
                self.ts.next()
                return t.LiteralType(text="-" + self.ts.next().value, line=tok.line)
            if tok.value == "(":
                self.ts.next()
                inner = self.parse_type()
                self.ts.expect("OP", ")")
                return inner
            if tok.value == "[":
                return self._tuple_type()
            if tok.value == "{":
                return t.ObjectType(members=self.type_members(), line=tok.line)
        if tok.kind == "NAME":
            if tok.value == "keyof":
                self.ts.next()
                return t.TypeOperator(op="keyof", operand=self._postfix_type(), line=tok.line)
            if tok.value == "readonly" and self.ts.peek(1).kind in ("NAME", "OP"):
                self.ts.next()
                return t.TypeOperator(op="readonly", operand=self._postfix_type(), line=tok.line)
            if tok.value == "typeof":
                self.ts.next()
                return t.TypeQuery(name=self._dotted_name(), line=tok.line)
            if tok.value in _LITERAL_WORDS:
                self.ts.next()
                return t.LiteralType(text=tok.value, line=tok.line)
            name = self._dotted_name()
            args: Tuple[t.TypeNode, ...] = ()
            if self.ts.at("OP", "<"):
                args = self.type_args()
            return t.TypeReference(name=name, args=args, line=tok.line)
        found = f"{tok.kind} {tok.value!r}" if tok.value else tok.kind
        raise TranspileError(f"Expected a type but found {found}", tok.line, tok.col)

    def _tuple_type(self) -> t.TupleType:
        open_tok = self.ts.expect("OP", "[")
        elements: List[t.TypeNode] = []
        while not self.ts.at("OP", "]"):
            self.ts.accept("OP", "...")
            if self.ts.peek().kind == "NAME" and (
                self.ts.peek(1).value == ":" or
                (self.ts.peek(1).value == "?" and self.ts.peek(2).value == ":")
            ):
                self.ts.next()          # element label
                self.ts.accept("OP", "?")
                self.ts.expect("OP", ":")
            elements.append(self.parse_type())
            self.ts.accept("OP", "?")
            if not self.ts.accept("OP", ","):
                break
        self.ts.expect("OP", "]")
        return t.TupleType(elements=tuple(elements), line=open_tok.line)

    # ------------------------------------------------------------ object types
    def type_members(self) -> Tuple[Union[t.PropertySignature, t.IndexSignature, t.MethodSignature], ...]:
        self.ts.expect("OP", "{")
        members: List[Union[t.PropertySignature, t.IndexSignature, t.MethodSignature]] = []
        while not self.ts.at("OP", "}"):
            members.append(self._type_member())
            if not (self.ts.accept("OP", ";") or self.ts.accept("OP", ",")):
                prev = self.ts.previous()
                nxt = self.ts.peek()
                if not (nxt.kind == "OP" and nxt.value == "}") and prev is not None \
                        and nxt.line == prev.line:
                    raise TranspileError("Expected ';', ',' or '}' after member", nxt.line, nxt.col)
        self.ts.expect("OP", "}")
        return tuple(members)

    def _type_member(self) -> Union[t.PropertySignature, t.IndexSignature, t.MethodSignature]:
        first = self.ts.peek()
        readonly = False
        if first.kind == "NAME" and first.value == "readonly" and not (
            self.ts.peek(1).kind == "OP" and self.ts.peek(1).value in (":", "?", "(", ";", ",", "}")
        ):
            self.ts.next()
            readonly = True
        if self.ts.at("OP", "["):
            self.ts.next()
            key_name = self.ts.expect("NAME").value
            self.ts.expect("OP", ":")
            key_type = self.parse_type()
            self.ts.expect("OP", "]")
            self.ts.expect("OP", ":")
            return t.IndexSignature(key_name=key_name, key_type=key_type,
                                    value_type=self.parse_type(), line=first.line)
        name_tok = self.ts.next()
        if name_tok.kind not in ("NAME", "STRING", "NUMBER"):
            raise TranspileError("Expected a member name", name_tok.line, name_tok.col)
        optional = self.ts.accept("OP", "?") is not None
        if self.ts.at("OP", "(") or self.ts.at("OP", "<"):
            type_params = self.type_params()
            self.ts.expect("OP", "(")
            params = self._params()
            self.ts.expect("OP", ")")
            returns = self.parse_type() if self.ts.accept("OP", ":") else None
            return t.MethodSignature(name=name_tok.value, optional=optional,
                                     type_params=type_params, params=params,
                                     returns=returns, line=name_tok.line)
        annotation = self.parse_type() if self.ts.accept("OP", ":") else None
        return t.PropertySignature(name=name_tok.value, optional=optional, readonly=readonly,
                                   type=annotation, line=name_tok.line)
