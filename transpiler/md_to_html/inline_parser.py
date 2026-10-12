"""Inline parser: a single left-to-right scanner plus a delimiter stack.

Phase 1 scans the text once, emitting plain text, code spans, links/images (via a
bracket stack) and *delimiter runs* of `*` / `_` with their flanking properties.
Phase 2 (`_process_emphasis`) resolves delimiter runs into Emphasis / Strong nodes
by repeatedly pairing the nearest compatible opener with each closer -- the
standard delimiter-stack algorithm, which is what lets `***a** b*` nest correctly
without backtracking.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from . import md_ast as ast

_ESCAPABLE = set("\\`*_{}[]()#+-.!<>~|\"'&")
_PLAIN = re.compile(r"[^\\`*_\[\]!\n<]+")
_DELIM_RUN = re.compile(r"\*+|_+")
_TICKS = re.compile(r"`+")
_AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.\-]*:[^\s<>]*)>")
_LINK_TAIL = re.compile(
    r"""\(\s*(?:<([^<>\n]*)>|((?:[^\s()\\]|\\.|\((?:[^\s()\\]|\\.)*\))*))"""
    r"""(?:\s+(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'))?\s*\)"""
)
_UNSAFE_SCHEME = re.compile(r"^\s*(?:javascript|vbscript|data):", re.IGNORECASE)


@dataclass
class _Delim:
    char: str
    count: int
    can_open: bool
    can_close: bool
    origin_count: int


@dataclass
class _Bracket:
    image: bool
    active: bool = True


_Item = Union[ast.Inline, _Delim, _Bracket]


def _is_space(ch: str) -> bool:
    return ch == "" or ch.isspace()


def _is_punct(ch: str) -> bool:
    return ch != "" and (unicodedata.category(ch).startswith("P") or unicodedata.category(ch).startswith("S"))


def _flanking(before: str, after: str, char: str) -> Tuple[bool, bool]:
    left = not _is_space(after) and (not _is_punct(after) or _is_space(before) or _is_punct(before))
    right = not _is_space(before) and (not _is_punct(before) or _is_space(after) or _is_punct(after))
    if char == "*":
        return left, right
    return (left and (not right or _is_punct(before)),
            right and (not left or _is_punct(after)))


def _unescape(text: str) -> str:
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!<>~|\"'&])", r"\1", text)


def parse_inlines(text: str) -> Tuple[ast.Inline, ...]:
    items = _scan(text)
    _process_emphasis(items, 0)
    return tuple(_finalize(items))


# ---------------------------------------------------------------------- phase 1
def _scan(text: str) -> List[_Item]:
    items: List[_Item] = []
    pos, n = 0, len(text)

    def add_text(value: str) -> None:
        if value:
            if items and isinstance(items[-1], ast.Text):
                items[-1] = ast.Text(items[-1].value + value)
            else:
                items.append(ast.Text(value))

    while pos < n:
        ch = text[pos]
        if ch == "\\":
            nxt = text[pos + 1: pos + 2]
            if nxt == "\n":
                items.append(ast.HardBreak())
                pos += 2
            elif nxt and nxt in _ESCAPABLE:
                add_text(nxt)
                pos += 2
            else:
                add_text("\\")
                pos += 1
        elif ch == "`":
            pos = _code_span(text, pos, items, add_text)
        elif ch in "*_":
            run = _DELIM_RUN.match(text, pos)
            assert run is not None
            before = text[pos - 1] if pos > 0 else ""
            after = text[run.end()] if run.end() < n else ""
            can_open, can_close = _flanking(before, after, ch)
            items.append(_Delim(ch, len(run.group()), can_open, can_close, len(run.group())))
            pos = run.end()
        elif ch == "!" and text[pos + 1: pos + 2] == "[":
            items.append(_Bracket(image=True))
            pos += 2
        elif ch == "[":
            items.append(_Bracket(image=False))
            pos += 1
        elif ch == "]":
            pos = _close_bracket(text, pos, items, add_text)
        elif ch == "\n":
            trailing = 0
            if items and isinstance(items[-1], ast.Text):
                value = items[-1].value
                stripped = value.rstrip(" ")
                trailing = len(value) - len(stripped)
                if stripped:
                    items[-1] = ast.Text(stripped)
                else:
                    items.pop()
            items.append(ast.HardBreak() if trailing >= 2 else ast.SoftBreak())
            pos += 1
        elif ch == "<":
            auto = _AUTOLINK.match(text, pos)
            if auto:
                url = auto.group(1)
                items.append(ast.Link(children=(ast.Text(url),), url=url))
                pos = auto.end()
            else:
                add_text("<")
                pos += 1
        else:
            plain = _PLAIN.match(text, pos)
            if plain:
                add_text(plain.group())
                pos = plain.end()
            else:
                add_text(ch)  # a lone '!'
                pos += 1
    return items


def _code_span(text: str, pos: int, items: List[_Item], add_text) -> int:
    opener = _TICKS.match(text, pos)
    assert opener is not None
    length = len(opener.group())
    search = opener.end()
    while True:
        close = _TICKS.search(text, search)
        if close is None:
            add_text(opener.group())
            return opener.end()
        if len(close.group()) == length:
            body = text[opener.end(): close.start()].replace("\n", " ")
            if body.strip(" ") and body[0] == " " and body[-1] == " ":
                body = body[1:-1]
            items.append(ast.CodeSpan(body))
            return close.end()
        search = close.end()


def _close_bracket(text: str, pos: int, items: List[_Item], add_text) -> int:
    opener_index: Optional[int] = None
    for idx in range(len(items) - 1, -1, -1):
        if isinstance(items[idx], _Bracket):
            opener_index = idx
            break
    if opener_index is None:
        add_text("]")
        return pos + 1
    bracket = items[opener_index]
    assert isinstance(bracket, _Bracket)
    tail = _LINK_TAIL.match(text, pos + 1) if bracket.active else None
    if tail is None:
        items[opener_index] = ast.Text("![" if bracket.image else "[")
        add_text("]")
        return pos + 1
    url = _unescape(tail.group(1) if tail.group(1) is not None else (tail.group(2) or ""))
    title = _unescape(tail.group(3) if tail.group(3) is not None else (tail.group(4) or ""))
    inner = items[opener_index + 1:]
    del items[opener_index:]
    _process_emphasis(inner, 0)
    children = tuple(_finalize(inner))
    if bracket.image:
        items.append(ast.Image(alt=_plain_text(children), url=url, title=title))
    else:
        items.append(ast.Link(children=children, url=url, title=title))
        for other in items:  # links may not contain links: deactivate earlier '['
            if isinstance(other, _Bracket) and not other.image:
                other.active = False
    return tail.end()


# ---------------------------------------------------------------------- phase 2
def _process_emphasis(items: List[_Item], bottom: int) -> None:
    i = bottom
    while i < len(items):
        closer = items[i]
        if not (isinstance(closer, _Delim) and closer.can_close and closer.count > 0):
            i += 1
            continue
        found: Optional[int] = None
        for j in range(i - 1, bottom - 1, -1):
            opener = items[j]
            if not (isinstance(opener, _Delim) and opener.char == closer.char
                    and opener.can_open and opener.count > 0):
                continue
            if (opener.can_close or closer.can_open) and \
                    (opener.origin_count + closer.origin_count) % 3 == 0 and \
                    not (opener.origin_count % 3 == 0 and closer.origin_count % 3 == 0):
                continue  # the "rule of three"
            found = j
            break
        if found is None:
            i += 1
            continue
        opener = items[found]
        assert isinstance(opener, _Delim)
        used = 2 if opener.count >= 2 and closer.count >= 2 else 1
        children = tuple(_finalize(items[found + 1: i]))
        node: ast.Inline = ast.Strong(children) if used == 2 else ast.Emphasis(children)
        opener.count -= used
        closer.count -= used
        items[found + 1: i] = [node]
        i = found + 2
        if opener.count == 0:
            del items[found]
            i -= 1
        if closer.count == 0:
            del items[i]


def _finalize(items: List[_Item]) -> List[ast.Inline]:
    """Turn leftover delimiters/brackets into literal text and merge adjacent text."""
    out: List[ast.Inline] = []
    for item in items:
        node: ast.Inline
        if isinstance(item, _Delim):
            node = ast.Text(item.char * item.count)
        elif isinstance(item, _Bracket):
            node = ast.Text("![" if item.image else "[")
        else:
            node = item
        if isinstance(node, ast.Text) and out and isinstance(out[-1], ast.Text):
            out[-1] = ast.Text(out[-1].value + node.value)
        elif not (isinstance(node, ast.Text) and node.value == ""):
            out.append(node)
    return out


def _plain_text(nodes: Tuple[ast.Inline, ...]) -> str:
    parts: List[str] = []
    for node in nodes:
        if isinstance(node, ast.Text):
            parts.append(node.value)
        elif isinstance(node, ast.CodeSpan):
            parts.append(node.value)
        elif isinstance(node, (ast.Emphasis, ast.Strong, ast.Link)):
            parts.append(_plain_text(node.children))
        elif isinstance(node, ast.Image):
            parts.append(node.alt)
        elif isinstance(node, (ast.SoftBreak, ast.HardBreak)):
            parts.append(" ")
    return "".join(parts)


def is_unsafe_url(url: str) -> bool:
    return bool(_UNSAFE_SCHEME.match(url))
