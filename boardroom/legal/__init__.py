"""Terms of Service and Privacy Policy, rendered from Markdown templates.

These are starting templates, not legal advice. Have them reviewed before launch.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

HERE = Path(__file__).parent


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"(?<![\w])_(.+?)_(?![\w])", r"<em>\1</em>", text)


def markdown_to_html(md: str) -> str:
    out: list[str] = []
    para: list[str] = []
    in_list = False

    def flush() -> None:
        nonlocal para
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para = []

    for raw in md.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            flush()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if not line:
            flush()
        elif line.startswith("## "):
            flush()
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            flush()
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        else:
            para.append(line)
    flush()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def render(doc: str, product: str, company: str, contact: str, updated: str) -> str:
    md = (HERE / f"{doc}.md").read_text()
    for key, value in {"product": product, "company": company, "contact": contact, "updated": updated}.items():
        md = md.replace("{" + key + "}", value)
    body = markdown_to_html(md)
    title = "Terms of Service" if doc == "terms" else "Privacy Policy"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · {html.escape(product)}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/styles.css"></head>
<body><div class="public">
<header class="public-bar"><a class="brand" href="/"><img src="/static/favicon.svg" alt=""> {html.escape(product)}</a>
<nav class="legal-nav"><a href="/terms">Terms</a><a href="/privacy">Privacy</a></nav></header>
<main class="main"><article class="container legal">{body}</article></main>
</div></body></html>"""
