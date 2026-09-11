"""Turning a stage's markdown into painted, wrapped terminal lines.

Every stage writes markdown. A reader should see the document, not the
markers: headings stand out, tables line up, and a row too wide to line
up is laid out as labelled fields rather than cut off.
"""

import re

from . import ui

# Words the chain uses as verdicts, painted wherever they appear.
WORDS = (
    ("CANNOT WRITE THIS EMAIL", ui.red),
    ("DO NOT USE", ui.red),
    ("FROM PACK", ui.green),
    ("VERIFIED", ui.green),
    ("ASSERTED", ui.yellow),
    ("INFERRED", ui.yellow),
    ("GENERIC", ui.yellow),
    ("STALE", ui.yellow),
    ("MADE UP", ui.red),
    ("BANNED", ui.red),
)


def paint_words(text: str) -> str:
    for word, paint in WORDS:
        if word in text:
            text = text.replace(word, paint(word))
    return text


# --------------------------------------------------------------------------
# inline markers
# --------------------------------------------------------------------------

_INLINE_RE = re.compile(
    r"(?P<tick>`+)(?P<code>.+?)(?P=tick)"
    r"|\[(?P<ltext>[^\]\n]+)\]\((?P<lurl>[^)\s]+)\)"
    r"|\*\*(?P<b1>\S(?:.*?\S)?)\*\*"
    r"|(?<![A-Za-z0-9_])__(?P<b2>\S(?:.*?\S)?)__(?![A-Za-z0-9_])"
    r"|(?<![*\w])\*(?P<i1>[^*\s](?:[^*]*?[^*\s])?)\*(?![*\w])"
    r"|(?<![A-Za-z0-9_])_(?P<i2>[^_\s](?:[^_]*?[^_\s])?)_(?![A-Za-z0-9_])"
)


def _inline(text: str):
    """Strip the markers, and remember the paint for every character left.

    Measuring happens on the stripped text, so a bold run wraps at the
    width the reader actually sees."""
    plain = []
    paints = []

    def add(chunk, paint):
        if not chunk:
            return
        plain.append(chunk)
        paints.extend([paint] * len(chunk))

    pos = 0
    for match in _INLINE_RE.finditer(text):
        add(text[pos : match.start()], None)
        if match.group("code") is not None:
            add(match.group("code"), ui.magenta)
        elif match.group("ltext") is not None:
            add(match.group("ltext"), None)
            add(" (" + match.group("lurl") + ")", ui.dim)
        elif match.group("b1") is not None or match.group("b2") is not None:
            add(match.group("b1") or match.group("b2"), ui.bold)
        else:
            add(match.group("i1") or match.group("i2"), ui.italic)
        pos = match.end()
    add(text[pos:], None)
    return "".join(plain), paints


def _emit(plain, paints, start, end) -> str:
    """Paint one slice, one run of same-paint characters at a time."""
    out = []
    index = start
    while index < end:
        paint = paints[index]
        stop = index
        while stop < end and paints[stop] is paint:
            stop += 1
        chunk = plain[index:stop]
        out.append(paint(chunk) if paint else paint_words(chunk))
        index = stop
    return "".join(out)


def _spans(plain: str, first: int, rest: int):
    """Where to break the text: on a space when there is one, mid-word when
    a single word is wider than the line."""
    length = len(plain)
    if not length:
        return [(0, 0)]
    spans = []
    index = 0
    limit = first
    while index < length:
        if spans:
            while index < length and plain[index] == " ":
                index += 1
            if index >= length:
                break
        width = 0
        stop = index
        last_space = -1
        while stop < length:
            step = ui.visible_width(plain[stop])
            if width + step > limit:
                break
            if plain[stop] == " ":
                last_space = stop
            width += step
            stop += 1
        if stop >= length:
            spans.append((index, length))
            break
        if last_space > index:
            spans.append((index, last_space))
            index = last_space + 1
        else:
            stop = max(stop, index + 1)
            spans.append((index, stop))
            index = stop
        limit = rest
    return spans or [(0, 0)]


def _wrap_inline(text: str, width: int, prefix: str = "", indent: str = ""):
    plain, paints = _inline(text)
    first = max(1, width - ui.visible_width(prefix))
    rest = max(1, width - ui.visible_width(indent))
    lines = []
    for position, (start, end) in enumerate(_spans(plain, first, rest)):
        while end > start and plain[end - 1] == " ":
            end -= 1
        body = _emit(plain, paints, start, end)
        lines.append(((prefix if position == 0 else indent) + body).rstrip())
    return lines


def _wrap_styled(text: str, width: int, paint):
    """Wrap on the stripped text, then paint whole lines. Used where one
    style owns the line, so no escape ever lands inside another."""
    plain, _ = _inline(text)
    return [paint(plain[start:end].rstrip()) for start, end in _spans(plain, width, width)]


def _styled(text: str) -> str:
    """One short piece of text, painted but not wrapped."""
    plain, paints = _inline(text)
    return _emit(plain, paints, 0, len(plain))


def _stripped(text: str) -> str:
    return _inline(text)[0]


def wrap(text: str, width: int):
    """Plain text wrapped to `width`: markers stripped, nothing painted.
    For callers that own the colour of the whole line themselves."""
    out = []
    for raw in (text or "").splitlines() or [""]:
        plain = _stripped(raw)
        out.extend(plain[start:end].rstrip() for start, end in _spans(plain, width, width))
    return out


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_RULE_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+](?:\s+(.*))?$")
_ORDERED_RE = re.compile(r"^\s*(\d{1,3}[.)])\s+(.*)$")
_FIELD_RE = re.compile(
    r"^(?P<label>[A-Z][A-Za-z0-9 +/()&'’-]{0,38}):(?:\s+(?P<value>.*))?$"
)
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")

QUOTE_BAR = "▏ "
BULLET = "• "
RULE_CHAR = "─"


def render(text: str, width: int):
    """The whole document, ready to print: painted, wrapped to `width`."""
    width = max(10, int(width))
    source = (text or "").splitlines()
    lines = []
    index = 0
    while index < len(source):
        raw = source[index]

        if _FENCE_RE.match(raw):
            index += 1
            while index < len(source) and not _FENCE_RE.match(source[index]):
                lines.append(ui.dim(ui.truncate(source[index], width)))
                index += 1
            index += 1
            continue

        if raw.strip().startswith("|"):
            block = []
            while index < len(source) and source[index].strip().startswith("|"):
                block.append(source[index])
                index += 1
            lines.extend(_table(block, width))
            continue

        heading = _HEADING_RE.match(raw)
        if heading and lines and lines[-1].strip():
            lines.append("")
        lines.extend(_block(raw, heading, width))
        index += 1
    return lines


def _block(raw: str, heading, width: int):
    stripped = raw.strip()
    if not stripped:
        return [""]
    if heading:
        return _wrap_styled(heading.group(2), width, lambda s: ui.bold(ui.cyan(s)))
    if _RULE_RE.match(raw):
        return [ui.dim(RULE_CHAR * width)]

    quote = _QUOTE_RE.match(raw)
    if quote:
        return _wrap_inline(
            quote.group(1), width, prefix=ui.dim(QUOTE_BAR), indent="  "
        )

    ordered = _ORDERED_RE.match(raw)
    if ordered:
        marker = ordered.group(1) + " "
        return _wrap_inline(
            ordered.group(2), width, prefix=ui.dim(marker), indent=" " * len(marker)
        )

    bullet = _BULLET_RE.match(raw)
    if bullet:
        return _wrap_inline(
            bullet.group(1) or "", width, prefix=ui.dim(BULLET), indent="  "
        )

    field = _FIELD_RE.match(raw)
    if field:
        return _wrap_inline(
            field.group("value") or "",
            width,
            prefix=ui.dim(field.group("label") + ": "),
            indent="  ",
        )

    return _wrap_inline(raw, width)


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------


def _cells(line: str):
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_separator(cells) -> bool:
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(cell or "") for cell in cells)


def _table(block, width: int):
    rows = [_cells(line) for line in block]
    rows = [row for row in rows if not _is_separator(row)]
    if not rows:
        return []

    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    header, body = (rows[0], rows[1:]) if len(rows) > 1 else (rows[0], [])

    widths = [
        max(ui.visible_width(_stripped(row[column])) for row in rows)
        for column in range(columns)
    ]
    if sum(widths) + 2 * (columns - 1) <= width:
        return _aligned(header, body, widths)
    return _records(header, body, width)


def _aligned(header, body, widths):
    lines = [
        "  ".join(
            ui.pad(ui.bold(_stripped(cell)), widths[i]) for i, cell in enumerate(header)
        ).rstrip()
    ]
    if body:
        lines.append(ui.dim("  ".join(RULE_CHAR * w for w in widths)))
    for row in body:
        lines.append(
            "  ".join(
                ui.pad(_styled(cell), widths[i]) for i, cell in enumerate(row)
            ).rstrip()
        )
    return lines


def _records(header, body, width: int):
    """One row per block of labelled lines. Nothing is cut: a cell too wide
    for the pane wraps under its own label."""
    labels = [_stripped(cell) for cell in header]
    label_width = min(max(ui.visible_width(cell) for cell in labels), max(8, width // 3))
    indent = " " * (label_width + 2)
    lines = []
    for row in body or [header]:
        if lines:
            lines.append("")
        for column, value in enumerate(row):
            if not value:
                continue
            label = labels[column] if body else ""
            prefix = ui.dim(ui.pad(ui.truncate(label, label_width), label_width) + "  ")
            lines.extend(_wrap_inline(value, width, prefix=prefix, indent=indent))
    return lines
