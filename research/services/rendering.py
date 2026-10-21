from __future__ import annotations

import re

import bleach
import markdown

CITATION_RE = re.compile(r"\[e:(\d+)\]")

ALLOWED_TAGS = [
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "em",
    "del",
    "ul",
    "ol",
    "li",
    "blockquote",
    "code",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "a",
    "sup",
    "span",
    "div",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "sup": ["class"],
    "code": ["class"],
    "span": ["class"],
    "div": ["class"],
    "th": ["align"],
    "td": ["align"],
    "table": ["class"],
}


def render_markdown(text: str) -> str:
    html = markdown.markdown(
        text or "", extensions=["tables", "fenced_code", "sane_lists"]
    )

    def replace(match: re.Match) -> str:
        evidence_id = match.group(1)
        return (
            f'<sup class="cite"><a href="#evidence-{evidence_id}" '
            f'title="查看证据 {evidence_id}">[{evidence_id}]</a></sup>'
        )

    html = CITATION_RE.sub(replace, html)
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
    )
