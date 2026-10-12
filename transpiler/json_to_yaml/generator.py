"""YAML generator: JSON AST -> block-style YAML (2-space indentation).

Containers are rendered recursively as lists of lines. A sequence item whose value
is a container reuses the child's own lines, folding its first line onto the
`- ` marker (`- key: value`, `- - nested`), which is how bracket nesting becomes
pure indentation.
"""

from __future__ import annotations

import re
from typing import List

from . import json_ast as ast

_RESERVED = {"true", "false", "yes", "no", "on", "off", "y", "n", "null", "~", "<<", "="}
_NUMERIC = re.compile(
    r"^[-+]?(?:\d[\d_]*(?::[0-5]?\d)*(?:\.[\d_]*)?(?:[eE][-+]?\d+)?"
    r"|\.\d[\d_]*(?:[eE][-+]?\d+)?|\.(?:inf|Inf|INF|nan|NaN|NAN))$"
)
_BASED = re.compile(r"^[-+]?0(?:[xX][0-9a-fA-F_]+|[oO]?[0-7_]+|[bB][01_]+)$")
_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}(?:[Tt ].*)?$")
_INDICATORS = set("[]{},#&*!|>'\"%@`")
_NUMBER_PARTS = re.compile(r"^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?)(\d+))?$")

INDENT = 2


def needs_quotes(s: str) -> bool:
    if s == "" or s != s.strip():
        return True
    if not s.isprintable():
        return True
    if s[0] in _INDICATORS:
        return True
    if s[0] in "-?:" and (len(s) == 1 or s[1] == " "):
        return True
    if s.startswith("---") or s.startswith("..."):
        return True
    if ": " in s or " #" in s or s.endswith(":"):
        return True
    if s.lower() in _RESERVED:
        return True
    if _NUMERIC.match(s) or _BASED.match(s) or _DATE.match(s):
        return True
    return False


def quote(s: str) -> str:
    out = ['"']
    for ch in s:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch.isprintable():
            out.append(ch)
        elif code < 0x100:
            out.append(f"\\x{code:02x}")
        elif code < 0x10000:
            out.append(f"\\u{code:04x}")
        else:
            out.append(f"\\U{code:08x}")
    out.append('"')
    return "".join(out)


def scalar_text(s: str) -> str:
    return quote(s) if needs_quotes(s) else s


def number_text(text: str) -> str:
    """Normalise so both YAML 1.1 and 1.2 parsers read a float, not a string."""
    m = _NUMBER_PARTS.match(text)
    assert m is not None  # the lexer already validated the shape
    sign, whole, frac, exp_sign, exp = m.groups()
    if frac is None and exp is None:
        return text
    mantissa = f"{sign}{whole}.{frac if frac is not None else '0'}"
    if exp is None:
        return mantissa
    return f"{mantissa}e{exp_sign or '+'}{exp}"


def _is_container(node: ast.JsonValue) -> bool:
    return isinstance(node, (ast.JsonObject, ast.JsonArray)) and bool(
        node.members if isinstance(node, ast.JsonObject) else node.items
    )


def _inline(node: ast.JsonValue) -> str:
    if isinstance(node, ast.JsonString):
        return scalar_text(node.value)
    if isinstance(node, ast.JsonNumber):
        return number_text(node.text)
    if isinstance(node, ast.JsonBool):
        return "true" if node.value else "false"
    if isinstance(node, ast.JsonNull):
        return "null"
    if isinstance(node, ast.JsonObject):
        return "{}"
    return "[]"


def _lines(node: ast.JsonValue, indent: int) -> List[str]:
    pad = " " * indent
    out: List[str] = []
    if isinstance(node, ast.JsonObject):
        for key, value in node.members:
            if _is_container(value):
                out.append(f"{pad}{scalar_text(key)}:")
                out.extend(_lines(value, indent + INDENT))
            else:
                out.append(f"{pad}{scalar_text(key)}: {_inline(value)}")
    elif isinstance(node, ast.JsonArray):
        for item in node.items:
            if _is_container(item):
                child = _lines(item, indent + INDENT)
                out.append(f"{pad}- {child[0][indent + INDENT:]}")
                out.extend(child[1:])
            else:
                out.append(f"{pad}- {_inline(item)}")
    return out


def generate(node: ast.JsonValue) -> str:
    if _is_container(node):
        return "\n".join(_lines(node, 0)) + "\n"
    return _inline(node) + "\n"
