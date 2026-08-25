"""A tiny, dependency-free Markdown subset renderer.

Only what the repository's README and LICENSE actually use: headings, bold,
italics, inline code, links, bullet lists, horizontal rules and paragraphs.
Everything is HTML-escaped first, so untrusted text can never inject markup.
"""

from __future__ import annotations

import html
import re

_LINK = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)\s]+)\)")
_STRONG = re.compile(r"\*\*(?P<text>[^*\n]+)\*\*")
_EM = re.compile(r"(?<![\w*])[*_](?P<text>[^*_\n]+)[*_](?![\w*])")
_CODE = re.compile(r"`(?P<text>[^`\n]+)`")


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = _CODE.sub(lambda m: f"<code>{m.group('text')}</code>", out)
    out = _LINK.sub(_render_link, out)
    out = _STRONG.sub(lambda m: f"<strong>{m.group('text')}</strong>", out)
    out = _EM.sub(lambda m: f"<em>{m.group('text')}</em>", out)
    return out


def _render_link(match: re.Match) -> str:
    href = match.group("href")
    text = match.group("text")
    if href.startswith(("http://", "https://", "mailto:")):
        safe = html.escape(href, quote=True)
        return f'<a href="{safe}" rel="noopener noreferrer" target="_blank">{text}</a>'
    return text


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _alignments(separator: str) -> list[str] | None:
    """Read a `| --- | :--: |` row into per-column alignments, or None."""
    cells = _split_row(separator)
    if not cells:
        return None
    alignments = []
    for cell in cells:
        if not re.fullmatch(r":?-{1,}:?", cell):
            return None
        if cell.startswith(":") and cell.endswith(":"):
            alignments.append("center")
        elif cell.endswith(":"):
            alignments.append("right")
        elif cell.startswith(":"):
            alignments.append("left")
        else:
            alignments.append("")
    return alignments


def _render_table(header: list[str], alignments: list[str], rows: list[list[str]]) -> str:
    def cell(tag: str, text: str, index: int) -> str:
        align = alignments[index] if index < len(alignments) else ""
        style = f' style="text-align: {align}"' if align else ""
        return f"<{tag}{style}>{_inline(text)}</{tag}>"

    columns = max([len(header)] + [len(row) for row in rows])
    parts = ['<div class="table-wrap"><table>']

    # A table used purely for layout often has an empty header row; showing an
    # empty band of <th>s would look like a rendering fault, so skip it.
    if any(text.strip() for text in header):
        cells = "".join(cell("th", header[i] if i < len(header) else "", i) for i in range(columns))
        parts.append(f"<thead><tr>{cells}</tr></thead>")

    parts.append("<tbody>")
    for row in rows:
        cells = "".join(cell("td", row[i] if i < len(row) else "", i) for i in range(columns))
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_markdown(source: str) -> str:
    lines = source.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    buffer: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if buffer:
            out.append("<p>" + _inline(" ".join(buffer).strip()) + "</p>")
            buffer.clear()

    def flush_list() -> None:
        if list_items:
            out.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items.clear()

    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            index += 1
            continue

        # A table is a row of pipes followed by an alignment row; without the
        # lookahead a `| --- |` line would be mistaken for a horizontal rule.
        if "|" in stripped and index + 1 < len(lines):
            alignments = _alignments(lines[index + 1])
            if alignments is not None:
                flush_paragraph()
                flush_list()
                header = _split_row(stripped)
                rows = []
                index += 2
                while index < len(lines) and "|" in lines[index] and lines[index].strip():
                    rows.append(_split_row(lines[index]))
                    index += 1
                out.append(_render_table(header, alignments, rows))
                continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_paragraph()
            flush_list()
            out.append("<hr>")
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            flush_paragraph()
            flush_list()
            level = min(len(heading.group(1)) + 1, 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            flush_paragraph()
            list_items.append(_inline(bullet.group(1)))
            index += 1
            continue
        flush_list()
        buffer.append(stripped)
        index += 1

    flush_paragraph()
    flush_list()
    return "\n".join(out)


def render_plaintext(source: str) -> str:
    """Render a plain-text document, keeping its own line breaks intact."""
    text = source.replace("\r\n", "\n")
    chunks = [chunk for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    blocks = []
    for chunk in chunks:
        stripped = chunk.strip("\n")
        if re.fullmatch(r"\s*[-*_]{3,}\s*", stripped):
            blocks.append("<hr>")
            continue
        blocks.append('<p class="plain">' + _inline(stripped).replace("\n", "<br>") + "</p>")
    return "\n".join(blocks)


def render_document(source: str, file_name: str) -> str:
    if file_name.lower().endswith((".md", ".markdown")):
        return render_markdown(source)
    return render_plaintext(source)
