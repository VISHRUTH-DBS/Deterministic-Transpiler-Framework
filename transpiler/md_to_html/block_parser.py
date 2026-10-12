"""Block parser: MdToken stream -> block-level AST.

Container blocks (block quotes, list items) are handled by collecting the lines
that belong to the container, stripping its prefix, and recursively lexing and
parsing that smaller document. This mirrors how Markdown nesting is defined and
keeps every function small: nesting depth equals recursion depth.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from . import md_ast as ast
from .inline_parser import parse_inlines
from .lexer import MdToken, tokenize

_BLOCK_STARTERS = {"HEADING", "HR", "QUOTE", "ULIST", "OLIST", "FENCE_OPEN"}


def parse_document(source: str) -> ast.Document:
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the newline that terminates the last line is not a blank line
    blocks, _ = _parse_blocks(tokenize(lines))
    return ast.Document(children=tuple(blocks))


def _parse_blocks(tokens: Sequence[MdToken]) -> Tuple[List[ast.Block], bool]:
    """Return (blocks, loose) where `loose` means a blank line separated sibling blocks."""
    blocks: List[ast.Block] = []
    loose = False
    i = 0
    pending_blank = False
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.kind == "BLANK":
            pending_blank = True
            i += 1
            continue
        if pending_blank and blocks:
            loose = True
        pending_blank = False
        if tok.kind == "HEADING":
            blocks.append(ast.Heading(level=tok.level, children=parse_inlines(tok.text)))
            i += 1
        elif tok.kind == "HR":
            blocks.append(ast.ThematicBreak())
            i += 1
        elif tok.kind == "FENCE_OPEN":
            i, block = _fenced_code(tokens, i)
            blocks.append(block)
        elif tok.kind == "QUOTE":
            i, block = _block_quote(tokens, i)
            blocks.append(block)
        elif tok.kind in ("ULIST", "OLIST"):
            i, block = _list(tokens, i)
            blocks.append(block)
        else:
            i, block = _paragraph(tokens, i)
            blocks.append(block)
    return blocks, loose


def _fenced_code(tokens: Sequence[MdToken], i: int) -> Tuple[int, ast.CodeBlock]:
    info = tokens[i].info
    i += 1
    code: List[str] = []
    while i < len(tokens) and tokens[i].kind == "CODE_LINE":
        code.append(tokens[i].text)
        i += 1
    if i < len(tokens) and tokens[i].kind == "FENCE_CLOSE":
        i += 1
    return i, ast.CodeBlock(info=info, code="".join(f"{line}\n" for line in code))


def _paragraph(tokens: Sequence[MdToken], i: int) -> Tuple[int, ast.Paragraph]:
    lines: List[str] = []
    while i < len(tokens) and tokens[i].kind == "TEXT":
        lines.append(tokens[i].raw.lstrip(" "))
        i += 1
        if i < len(tokens) and tokens[i].kind in _BLOCK_STARTERS:
            break
    text = "\n".join(lines).rstrip()
    return i, ast.Paragraph(children=parse_inlines(text))


def _block_quote(tokens: Sequence[MdToken], i: int) -> Tuple[int, ast.BlockQuote]:
    inner: List[str] = []
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "QUOTE":
            inner.append(tok.text)
        elif tok.kind == "TEXT" and inner and inner[-1].strip() != "":
            inner.append(tok.raw.strip())  # lazy paragraph continuation
        else:
            break
        i += 1
    blocks, _ = _parse_blocks(tokenize(inner))
    return i, ast.BlockQuote(children=tuple(blocks))


def _list(tokens: Sequence[MdToken], i: int) -> Tuple[int, ast.ListBlock]:
    first = tokens[i]
    ordered = first.kind == "OLIST"
    items: List[ast.ListItem] = []
    loose = False
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.kind != first.kind or tok.marker != first.marker:
            break
        i, item, item_loose = _list_item(tokens, i)
        items.append(item)
        loose = loose or item_loose
        # blank lines between items make the list loose if another item follows
        j = i
        while j < n and tokens[j].kind == "BLANK":
            j += 1
        if j < n and tokens[j].kind == first.kind and tokens[j].marker == first.marker and j > i:
            loose = True
            i = j
    return i, ast.ListBlock(ordered=ordered, start=first.number if ordered else 1,
                            tight=not loose, items=tuple(items))


def _list_item(tokens: Sequence[MdToken], i: int) -> Tuple[int, ast.ListItem, bool]:
    head = tokens[i]
    width = head.content_indent
    body: List[str] = [head.text]
    i += 1
    n = len(tokens)
    in_fence = False
    while i < n:
        tok = tokens[i]
        if in_fence:  # fenced code keeps every line, however little it is indented
            body.append(tok.raw[min(width, _indent_of(tok)):])
            in_fence = tok.kind != "FENCE_CLOSE" and tok.kind in ("CODE_LINE",)
            i += 1
            continue
        if tok.kind == "BLANK":
            # a blank line stays inside the item only if indented content follows
            j = i
            while j < n and tokens[j].kind == "BLANK":
                j += 1
            if j < n and _indent_of(tokens[j]) >= width and tokens[j].kind != "BLANK":
                body.extend("" for _ in range(j - i))
                i = j
                continue
            break
        if _indent_of(tok) >= width:
            body.append(tok.raw[width:])
            in_fence = tok.kind == "FENCE_OPEN"
            i += 1
        elif tok.kind == "TEXT" and body and body[-1].strip() != "":
            body.append(tok.raw.strip())  # lazy continuation of the item's paragraph
            i += 1
        else:
            break
    blocks, loose = _parse_blocks(tokenize(body))
    return i, ast.ListItem(children=tuple(blocks)), loose


def _indent_of(tok: MdToken) -> int:
    return len(tok.raw) - len(tok.raw.lstrip(" "))
