"""Safe, dependency-free Markdown → HTML rendering for the chat panel.

Supports the subset that matters for an agent chat UI: fenced code blocks
(with language label), headings, bold/italic, inline code, links (http/https
only — everything else is neutralised), unordered/ordered lists, blockquotes
and horizontal rules. All input is HTML-escaped first, so model output can
never inject markup into the UI.
"""

from __future__ import annotations

import html
import re
from typing import List

_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_ULIST_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_OLIST_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_HR_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")


def _safe_url(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return "#"


def _inline(text: str) -> str:
    """Apply inline formatting to already-escaped text."""

    def code_sub(m: re.Match) -> str:
        return f'<code class="inline-code">{m.group(1)}</code>'

    # Protect inline code spans from bold/italic mangling.
    spans: List[str] = []

    def stash_code(m: re.Match) -> str:
        spans.append(f'<code class="inline-code">{m.group(1)}</code>')
        return f"\x00{len(spans) - 1}\x00"

    text = _INLINE_CODE_RE.sub(stash_code, text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)

    def link_sub(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        return f'<a href="{_safe_url(url)}">{label}</a>'

    text = _LINK_RE.sub(link_sub, text)
    for i, span in enumerate(spans):
        text = text.replace(f"\x00{i}\x00", span)
    return text


def md_to_html(markdown: str) -> str:
    """Convert a Markdown string into themed HTML."""
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    out: List[str] = []
    in_code = False
    code_lang = ""
    code_buf: List[str] = []
    paragraph: List[str] = []
    list_kind: str | None = None  # "ul" | "ol"

    def flush_paragraph() -> None:
        if paragraph:
            joined = "<br/>".join(_inline(html.escape(p)) for p in paragraph)
            out.append(f"<p>{joined}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            out.append(f"</{list_kind}>")
            list_kind = None

    for line in lines:
        fence = _FENCE_RE.match(line.strip())
        if fence and not in_code:
            flush_paragraph()
            close_list()
            in_code = True
            code_lang = fence.group(1) or ""
            code_buf = []
            continue
        if in_code:
            if line.strip().startswith("```"):
                lang_label = (
                    f'<div class="code-lang">{html.escape(code_lang)}</div>' if code_lang else ""
                )
                body = html.escape("\n".join(code_buf))
                out.append(f'<div class="code-block">{lang_label}<pre>{body}</pre></div>')
                in_code = False
            else:
                code_buf.append(line)
            continue

        if not line.strip():
            flush_paragraph()
            close_list()
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(html.escape(heading.group(2)))}</h{level}>")
            continue

        if _HR_RE.match(line):
            flush_paragraph()
            close_list()
            out.append("<hr/>")
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            flush_paragraph()
            close_list()
            out.append(f"<blockquote>{_inline(html.escape(quote.group(1)))}</blockquote>")
            continue

        ulist = _ULIST_RE.match(line)
        olist = _OLIST_RE.match(line)
        if ulist or olist:
            flush_paragraph()
            kind = "ul" if ulist else "ol"
            if list_kind != kind:
                close_list()
                out.append(f"<{kind}>")
                list_kind = kind
            item = (ulist or olist).group(1)
            out.append(f"<li>{_inline(html.escape(item))}</li>")
            continue

        paragraph.append(line)

    if in_code:  # unterminated fence — render what we have
        body = html.escape("\n".join(code_buf))
        out.append(f'<div class="code-block"><pre>{body}</pre></div>')
    flush_paragraph()
    close_list()
    return "\n".join(out)
