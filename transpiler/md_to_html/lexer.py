"""Block-level lexer: a line-oriented state machine.

States:  NORMAL  -- classify each line with an ordered list of regular expressions
         FENCED  -- inside a ``` / ~~~ code fence; every line is literal CODE_LINE
                    until a closing fence of the same character and sufficient length.

Each physical line becomes exactly one token (plus FENCE_CLOSE markers), carrying
the raw line so container blocks (quotes, list items) can be re-lexed recursively
after their prefix has been stripped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^`]*?)[ \t]*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_QUOTE = re.compile(r"^ {0,3}>[ ]?(.*)$")
_ULIST = re.compile(r"^( *)([-*+])(?:([ ]{1,4})(.*)|[ \t]*)$")
_OLIST = re.compile(r"^( *)(\d{1,9})([.)])(?:([ ]{1,4})(.*)|[ \t]*)$")


@dataclass(frozen=True)
class MdToken:
    kind: str          # BLANK HEADING HR QUOTE ULIST OLIST TEXT FENCE_OPEN CODE_LINE FENCE_CLOSE
    line: int
    raw: str
    text: str = ""     # payload: heading text, quote body, list-item first line, code line
    indent: int = 0    # leading spaces of the marker (lists)
    level: int = 0     # heading level
    marker: str = ""   # '-', '*', '+' for bullets; '.', ')' for ordered
    number: int = 0    # ordered list number
    content_indent: int = 0  # column where list-item content begins
    info: str = ""     # fence info string


def _classify(raw: str, lineno: int) -> MdToken:
    if raw.strip() == "":
        return MdToken("BLANK", lineno, raw)
    m = _HEADING.match(raw)
    if m:
        return MdToken("HEADING", lineno, raw, text=(m.group(2) or "").strip(), level=len(m.group(1)))
    if _HR.match(raw):
        return MdToken("HR", lineno, raw)
    m = _QUOTE.match(raw)
    if m:
        return MdToken("QUOTE", lineno, raw, text=m.group(1))
    m = _ULIST.match(raw)
    if m:
        indent, marker, gap, body = len(m.group(1)), m.group(2), m.group(3), m.group(4)
        return MdToken("ULIST", lineno, raw, text=body or "", indent=indent, marker=marker,
                       content_indent=indent + 1 + (len(gap) if gap else 1))
    m = _OLIST.match(raw)
    if m:
        indent, number, marker, gap, body = len(m.group(1)), int(m.group(2)), m.group(3), m.group(4), m.group(5)
        width = len(m.group(2)) + 1
        return MdToken("OLIST", lineno, raw, text=body or "", indent=indent, marker=marker,
                       number=number, content_indent=indent + width + (len(gap) if gap else 1))
    return MdToken("TEXT", lineno, raw, text=raw.strip(), indent=len(raw) - len(raw.lstrip(" ")))


def tokenize(lines: Sequence[str]) -> List[MdToken]:
    tokens: List[MdToken] = []
    fence: Optional[re.Match[str]] = None
    fence_start = 0
    for lineno, raw in enumerate((ln.expandtabs(4) for ln in lines), start=1):
        if fence is not None:
            marker = fence.group(2)
            closing = re.match(rf"^ {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$", raw)
            if closing:
                tokens.append(MdToken("FENCE_CLOSE", lineno, raw))
                fence = None
            else:
                strip = min(len(fence.group(1)), len(raw) - len(raw.lstrip(" ")))
                tokens.append(MdToken("CODE_LINE", lineno, raw, text=raw[strip:]))
            continue
        m = _FENCE.match(raw)
        if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
            fence = m
            fence_start = lineno
            tokens.append(MdToken("FENCE_OPEN", lineno, raw, info=m.group(3).split(" ")[0] if m.group(3) else ""))
            continue
        tokens.append(_classify(raw, lineno))
    if fence is not None:  # an unclosed fence runs to the end of its container
        tokens.append(MdToken("FENCE_CLOSE", fence_start, ""))
    return tokens
