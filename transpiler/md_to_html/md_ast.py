"""Typed AST for the Markdown subset (block level and inline level)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union


# ------------------------------------------------------------------ inline nodes
@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class CodeSpan:
    value: str


@dataclass(frozen=True)
class Emphasis:
    children: Tuple["Inline", ...]


@dataclass(frozen=True)
class Strong:
    children: Tuple["Inline", ...]


@dataclass(frozen=True)
class Link:
    children: Tuple["Inline", ...]
    url: str
    title: str = ""


@dataclass(frozen=True)
class Image:
    alt: str
    url: str
    title: str = ""


@dataclass(frozen=True)
class SoftBreak:
    pass


@dataclass(frozen=True)
class HardBreak:
    pass


Inline = Union[Text, CodeSpan, Emphasis, Strong, Link, Image, SoftBreak, HardBreak]


# ------------------------------------------------------------------- block nodes
@dataclass(frozen=True)
class Heading:
    level: int
    children: Tuple[Inline, ...]


@dataclass(frozen=True)
class Paragraph:
    children: Tuple[Inline, ...]


@dataclass(frozen=True)
class CodeBlock:
    info: str
    code: str


@dataclass(frozen=True)
class ThematicBreak:
    pass


@dataclass(frozen=True)
class BlockQuote:
    children: Tuple["Block", ...]


@dataclass(frozen=True)
class ListItem:
    children: Tuple["Block", ...]


@dataclass(frozen=True)
class ListBlock:
    ordered: bool
    start: int
    tight: bool
    items: Tuple[ListItem, ...]


Block = Union[Heading, Paragraph, CodeBlock, ThematicBreak, BlockQuote, ListBlock]


@dataclass(frozen=True)
class Document:
    children: Tuple[Block, ...]
