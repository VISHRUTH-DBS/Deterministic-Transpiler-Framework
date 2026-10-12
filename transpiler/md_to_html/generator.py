"""HTML generator: Markdown AST -> HTML text (CommonMark-style layout)."""

from __future__ import annotations

import html
from typing import List, Sequence

from . import md_ast as ast
from .inline_parser import is_unsafe_url


def _esc(text: str) -> str:
    return html.escape(text, quote=True).replace("&#x27;", "&#39;")


def _url(url: str) -> str:
    return "" if is_unsafe_url(url) else _esc(url)


class HtmlGenerator:
    def generate(self, doc: ast.Document) -> str:
        out = self._blocks(doc.children)
        return out + "\n" if out else ""

    # ------------------------------------------------------------------ blocks
    def _blocks(self, blocks: Sequence[ast.Block]) -> str:
        return "\n".join(self._block(b) for b in blocks)

    def _block(self, block: ast.Block) -> str:
        if isinstance(block, ast.Heading):
            return f"<h{block.level}>{self._inlines(block.children)}</h{block.level}>"
        if isinstance(block, ast.Paragraph):
            return f"<p>{self._inlines(block.children)}</p>"
        if isinstance(block, ast.CodeBlock):
            cls = f' class="language-{_esc(block.info)}"' if block.info else ""
            return f"<pre><code{cls}>{_esc(block.code)}</code></pre>"
        if isinstance(block, ast.ThematicBreak):
            return "<hr />"
        if isinstance(block, ast.BlockQuote):
            inner = self._blocks(block.children)
            return f"<blockquote>\n{inner}\n</blockquote>" if inner else "<blockquote>\n</blockquote>"
        if isinstance(block, ast.ListBlock):
            return self._list(block)
        raise TypeError(f"Unknown block node {type(block).__name__}")

    def _list(self, block: ast.ListBlock) -> str:
        tag = "ol" if block.ordered else "ul"
        start = f' start="{block.start}"' if block.ordered and block.start != 1 else ""
        lines: List[str] = [f"<{tag}{start}>"]
        for item in block.items:
            lines.append(self._item(item, block.tight))
        lines.append(f"</{tag}>")
        return "\n".join(lines)

    def _item(self, item: ast.ListItem, tight: bool) -> str:
        if not item.children:
            return "<li></li>"
        if not tight:
            return "<li>\n" + self._blocks(item.children) + "\n</li>"
        parts: List[str] = []
        last_is_paragraph = False
        for index, child in enumerate(item.children):
            if isinstance(child, ast.Paragraph):
                text = self._inlines(child.children)
                parts.append(text if index == 0 else "\n" + text)
                last_is_paragraph = True
            else:
                parts.append("\n" + self._block(child))
                last_is_paragraph = False
        return "<li>" + "".join(parts) + ("" if last_is_paragraph else "\n") + "</li>"

    # ----------------------------------------------------------------- inlines
    def _inlines(self, nodes: Sequence[ast.Inline]) -> str:
        return "".join(self._inline(n) for n in nodes)

    def _inline(self, node: ast.Inline) -> str:
        if isinstance(node, ast.Text):
            return _esc(node.value)
        if isinstance(node, ast.CodeSpan):
            return f"<code>{_esc(node.value)}</code>"
        if isinstance(node, ast.Emphasis):
            return f"<em>{self._inlines(node.children)}</em>"
        if isinstance(node, ast.Strong):
            return f"<strong>{self._inlines(node.children)}</strong>"
        if isinstance(node, ast.Link):
            title = f' title="{_esc(node.title)}"' if node.title else ""
            return f'<a href="{_url(node.url)}"{title}>{self._inlines(node.children)}</a>'
        if isinstance(node, ast.Image):
            title = f' title="{_esc(node.title)}"' if node.title else ""
            return f'<img src="{_url(node.url)}" alt="{_esc(node.alt)}"{title} />'
        if isinstance(node, ast.SoftBreak):
            return "\n"
        if isinstance(node, ast.HardBreak):
            return "<br />\n"
        raise TypeError(f"Unknown inline node {type(node).__name__}")


def generate(doc: ast.Document) -> str:
    return HtmlGenerator().generate(doc)
