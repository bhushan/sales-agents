"""A run, as a page.

The terminal viewer shows one stage at a time to one person. This writes
the same material — every stage's output, its counters, and the verdicts
the workshop grades on — into a single HTML file that can be opened
without this tool, and read side by side across accounts.

Nothing is loaded from the network: the page is the file.
"""

import html as _html
import re
import time

from . import markdown, scoreboard

SAFE_URL_RE = re.compile(r"^(?:https?:|mailto:|#|/)", re.IGNORECASE)
COUNTER_LINE_RE = re.compile(r"^\s*[A-Z][A-Z ]*:\s*\d+(?:\s*\|\s*[A-Z][A-Z ]*:\s*\d+)+\s*$")

LEVEL_OF_COUNTER = {
    "VERIFIED": "good",
    "FROM PACK": "good",
    "ASSERTED": "warn",
    "INFERRED": "warn",
    "GENERIC": "warn",
    "FAILED A": "bad",
    "FAILED B": "bad",
    "FAILED C": "bad",
    "FAILED D": "bad",
    "MADE UP": "bad",
    "BANNED": "bad",
}


def escape(text) -> str:
    return _html.escape(str(text if text is not None else ""), quote=True)


def _mark_words(escaped: str) -> str:
    """The chain's verdict words, readable at a glance wherever they land."""
    for word, level in markdown.WORD_LEVEL:
        if word in escaped:
            escaped = escaped.replace(
                word, f'<mark class="verdict-{level}">{word}</mark>'
            )
    return escaped


def _text(raw: str) -> str:
    return _mark_words(escape(raw))


def inline(text: str) -> str:
    """One line of markdown, as HTML: emphasis, code and links kept, every
    other character escaped."""
    out = []
    pos = 0
    for match in markdown.INLINE_RE.finditer(text or ""):
        out.append(_text(text[pos : match.start()]))
        if match.group("code") is not None:
            out.append("<code>" + escape(match.group("code")) + "</code>")
        elif match.group("ltext") is not None:
            label = _text(match.group("ltext"))
            url = match.group("lurl") or ""
            if SAFE_URL_RE.match(url):
                out.append(
                    f'<a href="{escape(url)}" target="_blank" rel="noreferrer">{label}</a>'
                )
            else:
                out.append(label)
        elif match.group("b1") is not None or match.group("b2") is not None:
            out.append("<strong>" + _text(match.group("b1") or match.group("b2")) + "</strong>")
        else:
            out.append("<em>" + _text(match.group("i1") or match.group("i2")) + "</em>")
        pos = match.end()
    out.append(_text(text[pos:]))
    return "".join(out)


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------


def _counter_chips(counts, *, extra_class="") -> str:
    """The counters a stage ends with, as one strip. This is the number the
    workshop marks, so it is never buried in a paragraph."""
    if not counts:
        return ""
    chips = []
    for name in scoreboard.COUNTER_NAMES:
        if name not in counts:
            continue
        level = LEVEL_OF_COUNTER.get(name, "flat")
        chips.append(
            f'<li class="chip chip-{level}">'
            f'<span class="chip-value">{counts[name]}</span>'
            f'<span class="chip-name">{escape(name)}</span></li>'
        )
    if not chips:
        return ""
    classes = ("counters " + extra_class).strip()
    return f'<ul class="{classes}">' + "".join(chips) + "</ul>"


def _table(block) -> str:
    rows = [markdown.cells(line) for line in block]
    rows = [row for row in rows if not markdown.is_separator(row)]
    if not rows:
        return ""
    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    header, body = rows[0], rows[1:]

    head = "<tr>" + "".join(f"<th>{inline(cell)}</th>" for cell in header) + "</tr>"
    rest = "".join(
        "<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>"
        for row in body
    )
    return (
        '<div class="table-wrap"><table><thead>'
        + head
        + "</thead><tbody>"
        + rest
        + "</tbody></table></div>"
    )


RUN_ON_FIELD_RE = re.compile(r"\s{2,}(?=[A-Z][A-Za-z0-9 +/()&'\u2019-]{0,38}:)")


def _field_pairs(raw: str):
    """`Label: value` — or, as the pack's header line writes it, three of
    them on one line, separated by runs of spaces."""
    pairs = []
    for part in RUN_ON_FIELD_RE.split(raw.strip()):
        field = markdown.FIELD_RE.match(part.strip())
        if field:
            pairs.append((field.group("label"), field.group("value") or ""))
        elif pairs:
            label, value = pairs[-1]
            pairs[-1] = (label, (value + " " + part.strip()).strip())
    return pairs


def _field_lines(source) -> set:
    """Which lines to read as `Label: value`.

    The pack writes fields in blocks, one per line; an email sentence can
    open the same way ("One thing worth flagging: ...") and is prose. A
    labelled line counts as a field when it sits next to another one, when
    its label is short enough to be a field name, or when it carries
    several labels itself, as the pack's header line does.
    """
    labelled = {}
    for index, line in enumerate(source):
        match = markdown.FIELD_RE.match(line)
        if match and not line.strip().startswith("|"):
            labelled[index] = match.group("label")
    return {
        index
        for index, label in labelled.items()
        if index - 1 in labelled
        or index + 1 in labelled
        or len(label.split()) <= 3
        or len(_field_pairs(source[index])) > 1
    }


def render_markdown(text: str) -> str:
    """A stage's markdown as HTML, with the same reading of it the terminal
    viewer uses: headings, tables, and `Label: value` lines as fields."""
    source = (text or "").splitlines()
    field_lines = _field_lines(source)
    out = []
    para = []
    items = []
    fields = []
    quotes = []
    list_kind = [None]

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(inline(line) for line in para) + "</p>")
            para.clear()

    def flush_items():
        if items:
            tag = list_kind[0] or "ul"
            out.append(
                f"<{tag}>" + "".join(f"<li>{item}</li>" for item in items) + f"</{tag}>"
            )
            items.clear()
            list_kind[0] = None

    def flush_fields():
        if fields:
            body = "".join(
                f"<dt>{inline(label)}</dt><dd>{inline(value)}</dd>"
                for label, value in fields
            )
            out.append('<dl class="fields">' + body + "</dl>")
            fields.clear()

    def flush_quotes():
        if quotes:
            body = "".join(f"<p>{inline(line)}</p>" for line in quotes)
            out.append("<blockquote>" + body + "</blockquote>")
            quotes.clear()

    def flush():
        flush_para()
        flush_items()
        flush_fields()
        flush_quotes()

    index = 0
    while index < len(source):
        raw = source[index]

        if markdown.FENCE_RE.match(raw):
            flush()
            index += 1
            code = []
            while index < len(source) and not markdown.FENCE_RE.match(source[index]):
                code.append(source[index])
                index += 1
            index += 1
            out.append("<pre><code>" + escape("\n".join(code)) + "</code></pre>")
            continue

        if raw.strip().startswith("|"):
            flush()
            block = []
            while index < len(source) and source[index].strip().startswith("|"):
                block.append(source[index])
                index += 1
            out.append(_table(block))
            continue

        index += 1
        stripped = raw.strip()

        if not stripped:
            flush()
            continue

        if COUNTER_LINE_RE.match(stripped):
            flush()
            out.append(_counter_chips(scoreboard.parse_counts(stripped), extra_class="inline-counters"))
            continue

        heading = markdown.HEADING_RE.match(raw)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue

        if markdown.RULE_RE.match(raw):
            flush()
            out.append('<hr class="break">')
            continue

        quote = markdown.QUOTE_RE.match(raw)
        if quote:
            flush_para()
            flush_items()
            flush_fields()
            quotes.append(quote.group(1))
            continue

        ordered = markdown.ORDERED_RE.match(raw)
        if ordered:
            flush_para()
            flush_fields()
            flush_quotes()
            if list_kind[0] != "ol":
                flush_items()
                list_kind[0] = "ol"
            items.append(inline(ordered.group(2)))
            continue

        bullet = markdown.BULLET_RE.match(raw)
        if bullet:
            flush_para()
            flush_fields()
            flush_quotes()
            if list_kind[0] != "ul":
                flush_items()
                list_kind[0] = "ul"
            items.append(inline(bullet.group(1) or ""))
            continue

        if index - 1 in field_lines:
            flush_para()
            flush_items()
            flush_quotes()
            fields.extend(_field_pairs(raw))
            continue

        flush_items()
        flush_fields()
        flush_quotes()
        para.append(raw.strip())

    flush()
    return "".join(part for part in out if part)


# --------------------------------------------------------------------------
# what a run adds up to
# --------------------------------------------------------------------------


def _plural(count, word) -> str:
    return word if count == 1 else word + "s"


def _percent(part, whole):
    return 0.0 if not whole else round(100.0 * part / whole, 1)


def metrics(summary, stages) -> dict:
    """The numbers the workshop marks a run on, gathered from its stages."""
    research, messages = {}, {}
    verified = asserted = 0
    for stage in stages:
        counts = stage.counts
        if "ROWS" in counts:
            research = counts
        elif "SENTENCES" in counts:
            messages = counts
        elif counts:
            verified += counts.get("VERIFIED", 0)
            asserted += counts.get("ASSERTED", 0)

    rows = research.get("ROWS", 0)
    unsourced = research.get("FAILED A", 0)
    sentences = messages.get("SENTENCES", 0)
    invented = messages.get("MADE UP", 0) + messages.get("BANNED", 0)
    return {
        "done": sum(1 for stage in stages if stage.exists),
        "total": len(stages),
        "verified": verified,
        "asserted": asserted,
        "rows": rows,
        "sourced": rows - unsourced,
        "unsourced": unsourced,
        "sourced_pct": _percent(rows - unsourced, rows),
        "sentences": sentences,
        "from_pack": messages.get("FROM PACK", 0),
        "inferred": messages.get("INFERRED", 0),
        "generic": messages.get("GENERIC", 0),
        "invented": invented,
        "research_verdict": scoreboard.research_verdict(research) if research else None,
        "message_verdict": scoreboard.message_verdict(messages) if messages else None,
    }


def _bar(segments) -> str:
    """One row of evidence, to scale: every segment is a share of the same
    hundred percent, so a weak run is visible before it is read."""
    total = sum(value for _, value, _ in segments) or 1
    parts = []
    for level, value, label in segments:
        if not value:
            continue
        width = 100.0 * value / total
        parts.append(
            f'<span class="seg seg-{level}" style="width:{width:.4f}%" '
            f'title="{escape(label)}: {value}"></span>'
        )
    return '<div class="bar">' + "".join(parts) + "</div>"


def _key(segments) -> str:
    parts = [
        f'<li class="key key-{level}"><b>{value}</b> {escape(label)}</li>'
        for level, value, label in segments
        if value
    ]
    return '<ul class="keys">' + "".join(parts) + "</ul>"


def _verdict_line(verdict, prefix) -> str:
    if not verdict:
        return ""
    level, message = verdict
    return (
        f'<p class="verdict verdict-{level}"><span class="verdict-dot"></span>'
        f"{escape(prefix)} {escape(message)}</p>"
    )


def _ledger(numbers) -> str:
    """The hero of a run: how much of it is sourced, and whether the
    messages can go out."""
    blocks = []
    if numbers["rows"]:
        segments = [
            ("good", numbers["sourced"], _plural(numbers["sourced"], "row") + " with a source"),
            ("bad", numbers["unsourced"], _plural(numbers["unsourced"], "row") + " without one"),
        ]
        blocks.append(
            '<div class="ledger-block">'
            f'<p class="ledger-figure">{numbers["sourced_pct"]:g}<span>%</span></p>'
            f'<p class="ledger-caption">of {numbers["rows"]} graded rows name a source '
            "you could check</p>"
            + _bar(segments)
            + _key(segments)
            + _verdict_line(numbers["research_verdict"], "Research:")
            + "</div>"
        )
    if numbers["sentences"]:
        segments = [
            ("good", numbers["from_pack"], "from the pack"),
            ("warn", numbers["inferred"], "inferred from it"),
            ("flat", numbers["generic"], "generic"),
            ("bad", numbers["invented"], "invented"),
        ]
        traceable = numbers["from_pack"] + numbers["inferred"]
        blocks.append(
            '<div class="ledger-block">'
            f'<p class="ledger-figure">{traceable}<span>/{numbers["sentences"]}</span></p>'
            "<p class=\"ledger-caption\">sentences in the emails and messages trace back "
            "to a pack field</p>"
            + _bar(segments)
            + _key(segments)
            + _verdict_line(numbers["message_verdict"], "Messages:")
            + "</div>"
        )
    if not blocks:
        blocks.append(
            '<div class="ledger-block"><p class="ledger-caption">This run has not '
            "reached a graded stage yet.</p></div>"
        )
    return '<div class="ledger">' + "".join(blocks) + "</div>"


# --------------------------------------------------------------------------
# a run, and the page around it
# --------------------------------------------------------------------------


def _stage_level(stage) -> str:
    if not stage.exists:
        return "pending"
    verdict = stage.verdict
    return verdict[0] if verdict else "done"


def _rail(stages, run_id) -> str:
    items = []
    for index, stage in enumerate(stages):
        level = _stage_level(stage)
        badge = stage.badge or ("not run yet" if not stage.exists else "")
        items.append(
            f'<li><button class="rail-item level-{level}" type="button" '
            f'data-stage="{index}" aria-controls="{run_id}-stage-{index}" '
            f'aria-selected="{"true" if index == 0 else "false"}">'
            f'<span class="rail-step">{index}</span>'
            f'<span class="rail-body"><span class="rail-title">{escape(stage.step.title)}</span>'
            f'<span class="rail-badge">{escape(badge)}</span></span>'
            f'<span class="rail-hits" hidden></span>'
            "</button></li>"
        )
    return f'<ol class="rail" data-run="{run_id}">' + "".join(items) + "</ol>"


def _stage_panel(stage, run_id, index) -> str:
    level = _stage_level(stage)
    aside = f'<p class="stage-file">{escape(stage.path.name)}</p>'
    if stage.exists:
        aside += '<button class="copy" type="button">Copy this stage</button>'
    head = (
        '<header class="stage-head">'
        f'<h3 class="stage-title">{escape(stage.step.title)}</h3>'
        f'<div class="stage-aside">{aside}</div>'
        "</header>"
    )
    verdict = stage.verdict
    meta = _counter_chips(stage.counts) + (
        _verdict_line(verdict, "") if verdict else ""
    )
    if stage.exists:
        body = f'<div class="prose">{render_markdown(stage.text)}</div>' 
    else:
        body = (
            '<div class="prose empty"><p>This stage has not run yet. It will write '
            f"<code>{escape(stage.step.output_name)}</code> when it does.</p></div>"
        )
    return (
        f'<article class="stage level-{level}" id="{run_id}-stage-{index}" '
        f'data-stage="{index}"{"" if index == 0 else " hidden"}>'
        + head
        + meta
        + body
        + "</article>"
    )


def _fact(label, value) -> str:
    return (
        f'<div class="fact"><dt>{escape(label)}</dt>'
        f"<dd>{escape(value) if value else '<span class=none>not given</span>'}</dd></div>"
    )


def _run_line(state, numbers) -> str:
    who = escape(state.seller) if state.seller else "The chain"
    what = f" selling {escape(state.offering)}" if state.offering else ""
    done, total = numbers["done"], numbers["total"]
    where = "all of them" if done == total else f"{done} of them"
    return (
        f"{who}{what}, researched into {escape(state.company)} across "
        f"{total} stages, {where} finished."
    )


def run_section(summary, run_id, stages, numbers, *, active=False) -> str:
    state = summary.state
    facts = (
        '<dl class="facts">'
        + _fact("Seller", state.seller)
        + _fact("What they sell", state.offering)
        + _fact("Industry", state.industry)
        + _fact("Model", state.model)
        + _fact("Run", str(summary.run_dir))
        + "</dl>"
    )
    return (
        f'<section class="run" id="{run_id}" data-run="{run_id}"'
        f'{"" if active else " hidden"}>'
        '<div class="run-head">'
        f'<p class="run-date">{escape(state.date)}</p>'
        f'<h2 class="run-name">{escape(state.company)}</h2>'
        f'<p class="run-line">{_run_line(state, numbers)}</p>'
        + facts
        + "</div>"
        + _ledger(numbers)
        + '<div class="reader">'
        + '<div class="rail-wrap">'
        + _rail(stages, run_id)
        + "</div>"
        + '<div class="stages">'
        + "".join(
            _stage_panel(stage, run_id, index) for index, stage in enumerate(stages)
        )
        + "</div></div></section>"
    )


def _tab_sub(state, numbers) -> str:
    stages = f'{numbers["done"]}/{numbers["total"]} stages'
    return f"{escape(state.seller)} · {stages}" if state.seller else stages


def _tabs(entries) -> str:
    items = []
    for index, (run_id, summary, numbers) in enumerate(entries):
        pct = numbers["sourced_pct"]
        level = "flat"
        if numbers["rows"]:
            level = (numbers["research_verdict"] or ("flat", ""))[0]
        meter = (
            f'<span class="tab-meter"><span class="tab-fill level-{level}" '
            f'style="width:{pct:g}%"></span></span>'
            if numbers["rows"]
            else '<span class="tab-meter"></span>'
        )
        items.append(
            f'<button class="tab" type="button" data-run="{run_id}" '
            f'aria-selected="{"true" if index == 0 else "false"}">'
            f'<span class="tab-name">{escape(summary.state.company)}</span>'
            f'<span class="tab-sub">{_tab_sub(summary.state, numbers)}</span>'
            + meter
            + "</button>"
        )
    return '<nav class="tabs" aria-label="Accounts researched">' + "".join(items) + "</nav>"


_NUMBER_WORD = {1: "One run", 2: "Both runs", 3: "All three runs", 4: "All four runs"}


def _count_word(count) -> str:
    return _NUMBER_WORD.get(count, f"All {count} runs")


def _mix(numbers) -> str:
    """How the sentences of one run were labelled, to scale and in words."""
    if not numbers["sentences"]:
        return "&mdash;"
    segments = [
        ("good", numbers["from_pack"], "from the pack"),
        ("warn", numbers["inferred"], "inferred"),
        ("flat", numbers["generic"], "generic"),
        ("bad", numbers["invented"], "invented"),
    ]
    words = " · ".join(
        f"{value} {label}" for _, value, label in segments if value
    )
    return _bar(segments) + f'<span class="row-sub">{words}</span>'


def _compare(entries) -> str:
    rows = []
    for run_id, summary, numbers in entries:
        research = numbers["research_verdict"]
        messages = numbers["message_verdict"]
        rows.append(
            "<tr>"
            f'<th scope="row"><button class="link" type="button" data-run="{run_id}">'
            f'{escape(summary.state.company)}</button>'
            f'<span class="row-sub">{escape(summary.state.seller)}</span></th>'
            f'<td>{numbers["done"]}/{numbers["total"]}</td>'
            f'<td>{numbers["verified"]} <span class="unit">verified</span> · '
            f'{numbers["asserted"]} <span class="unit">asserted</span></td>'
            f'<td>{(str(numbers["sourced_pct"]) + "%") if numbers["rows"] else "—"}'
            f'<span class="row-sub">{numbers["sourced"]}/{numbers["rows"]} rows</span></td>'
            f'<td class="mix">{_mix(numbers)}</td>'
            f'<td class="verdicts">'
            + (_verdict_line(research, "") if research else "—")
            + (_verdict_line(messages, "") if messages else "")
            + "</td></tr>"
        )
    return (
        '<section class="compare" id="compare">'
        f"<h2>{_count_word(len(entries))}, marked the same way</h2>"
        '<p class="lede">The same chain, the same thresholds. What changes between '
        "accounts is how much of the research named a source.</p>"
        '<div class="table-wrap"><table class="compare-table"><thead><tr>'
        "<th>Account</th><th>Stages</th><th>Claims</th><th>Rows sourced</th>"
        "<th>Sentences in the messages</th><th>Verdict</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></section>"
    )


STYLE = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --ground:#E9EDF1; --surface:#FFFFFF; --ink:#16283C; --ink-soft:#546C82;
  --rule:#C7D2DD; --rule-soft:#E2E8EE; --wash:#F1F4F7;
  --good:#1C6B4A; --warn:#8F5410; --bad:#A32929; --flat:#8A9AAA;
  --good-wash:#DFEDE5; --warn-wash:#F3E8D8; --bad-wash:#F4E1E1;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,"Times New Roman",serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--serif);
  font-size:17px;line-height:1.62;-webkit-font-smoothing:antialiased}
h1,h2,h3,h4{font-weight:600;letter-spacing:-.005em}
button{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.shell{max-width:1180px;margin:0 auto;padding:0 24px}
.visually-hidden{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}

.masthead{position:sticky;top:0;z-index:20;background:rgba(233,237,241,.94);
  border-bottom:1px solid var(--rule);backdrop-filter:blur(8px)}
.masthead .shell{display:flex;align-items:center;gap:18px;padding-top:10px;padding-bottom:10px}
.wordmark{margin:0;font-family:var(--sans);font-size:13px;color:var(--ink-soft)}
.wordmark b{color:var(--ink);font-weight:600}
.find{margin-left:auto;display:flex;align-items:center;gap:10px}
.find input{width:230px;padding:6px 10px;border:1px solid var(--rule);background:var(--surface);
  color:var(--ink);font-family:var(--sans);font-size:14px;border-radius:2px}
.find input::placeholder{color:var(--flat)}
.find-count{font-family:var(--sans);font-size:12px;color:var(--ink-soft);min-width:104px}

.tabs{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;
  padding-top:26px}
.tab{display:grid;gap:3px;text-align:left;background:none;border:0;border-top:2px solid var(--rule);
  padding:11px 0 13px;cursor:pointer}
.tab:hover{border-top-color:var(--ink-soft)}
.tab[aria-selected="true"]{border-top-color:var(--ink)}
.tab-name{font-size:19px;line-height:1.25;color:var(--ink-soft)}
.tab[aria-selected="true"] .tab-name{color:var(--ink)}
.tab-sub{font-family:var(--sans);font-size:12px;color:var(--ink-soft)}
.tab-meter{display:block;height:3px;margin-top:6px;background:var(--rule-soft)}
.tab-fill{display:block;height:100%;background:var(--flat)}
.tab-fill.level-good{background:var(--good)}
.tab-fill.level-warn{background:var(--warn)}
.tab-fill.level-bad{background:var(--bad)}

.run-head{padding-top:30px}
.run-date{margin:0;font-family:var(--sans);font-size:13px;color:var(--ink-soft)}
.run-name{margin:.06em 0 .18em;font-size:clamp(34px,5.2vw,56px);line-height:1.03}
.run-line{margin:0 0 20px;max-width:58ch;color:var(--ink-soft)}
.facts{display:flex;flex-wrap:wrap;margin:0;border-top:1px solid var(--rule)}
.fact{padding:10px 26px 12px 0;margin-right:26px;border-right:1px solid var(--rule-soft);
  max-width:34ch}
.fact:last-child{border-right:0;margin-right:0}
.fact dt{font-family:var(--sans);font-size:12px;color:var(--ink-soft)}
.fact dd{margin:1px 0 0;font-size:16px;line-height:1.45}
.none{color:var(--flat)}

.ledger{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:40px;
  margin-top:34px}
.ledger-block{border-top:1px solid var(--ink);padding-top:14px}
.ledger-figure{margin:0;font-size:62px;line-height:1;font-variant-numeric:lining-nums tabular-nums}
.ledger-figure span{font-size:24px;color:var(--ink-soft)}
.ledger-caption{margin:8px 0 16px;max-width:40ch;color:var(--ink-soft);font-size:16px}
.bar{display:flex;height:17px;background:var(--rule-soft)}
.seg{display:block;height:100%}
.seg-good{background:var(--good)}.seg-warn{background:var(--warn)}
.seg-bad{background:var(--bad)}.seg-flat{background:var(--flat)}
.keys{display:flex;flex-wrap:wrap;gap:16px;list-style:none;margin:11px 0 0;padding:0;
  font-family:var(--sans);font-size:13px;color:var(--ink-soft)}
.key::before{content:"";display:inline-block;width:9px;height:9px;margin-right:7px;background:var(--flat)}
.key-good::before{background:var(--good)}.key-warn::before{background:var(--warn)}
.key-bad::before{background:var(--bad)}
.key b{color:var(--ink);font-weight:600}
.verdict{margin:14px 0 0;font-family:var(--sans);font-size:13.5px;line-height:1.5;color:var(--ink-soft)}
.verdict-dot{display:inline-block;width:7px;height:7px;margin-right:8px;background:var(--flat);
  vertical-align:middle}
.verdict-good .verdict-dot{background:var(--good)}
.verdict-warn .verdict-dot{background:var(--warn)}
.verdict-bad .verdict-dot{background:var(--bad);}
.verdict-bad{color:var(--bad)}

.reader{display:grid;grid-template-columns:272px minmax(0,1fr);gap:34px;align-items:start;
  margin-top:40px;padding-bottom:64px}
.rail-wrap{position:sticky;top:62px}
.rail{list-style:none;margin:0;padding:0;border-top:1px solid var(--rule)}
.rail-item{width:100%;display:grid;grid-template-columns:20px minmax(0,1fr) auto;gap:10px;
  align-items:start;background:none;border:0;border-bottom:1px solid var(--rule-soft);
  padding:9px 8px 10px 9px;text-align:left;cursor:pointer;font-family:var(--sans)}
.rail-item:hover{background:rgba(255,255,255,.6)}
.rail-item[aria-selected="true"]{background:var(--surface);box-shadow:inset 3px 0 0 var(--ink)}
.rail-item[aria-selected="true"] .rail-title{color:var(--ink)}
.rail-step{font-size:12px;line-height:1.7;color:var(--flat);font-variant-numeric:tabular-nums}
.rail-title{display:block;font-size:14px;line-height:1.34;color:var(--ink-soft)}
.rail-badge{display:block;margin-top:2px;font-size:11.5px;line-height:1.4;color:var(--flat)}
.rail-hits{font-size:11.5px;color:var(--ink);background:#FFE9A8;padding:0 5px;line-height:1.7}
.level-good .rail-step{color:var(--good)}
.level-warn .rail-step{color:var(--warn)}
.level-bad .rail-step{color:var(--bad)}
.level-bad .rail-title{color:var(--bad)}
.level-pending .rail-title{color:var(--flat)}
.rail-item.no-hit{opacity:.4}

.stage{background:var(--surface);border:1px solid var(--rule);padding:30px 36px 44px}
.stage-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;
  gap:14px;padding-bottom:12px;border-bottom:1px solid var(--rule)}
.stage-title{margin:0;font-size:26px;line-height:1.22}
.stage-file{margin:0;font-family:var(--sans);font-size:12.5px;color:var(--ink-soft)}
.stage .counters{margin-top:16px}
.stage-aside{display:flex;align-items:baseline;gap:16px}
.copy,.link{background:none;border:0;padding:4px 0;font-family:var(--sans);font-size:13px;
  color:var(--ink-soft);cursor:pointer;text-decoration:underline;text-underline-offset:3px;
  text-decoration-color:var(--rule)}
.copy:hover,.link:hover{color:var(--ink)}

.counters{display:flex;flex-wrap:wrap;gap:8px;list-style:none;margin:0 0 20px;padding:0;
  font-family:var(--sans)}
.chip{display:flex;align-items:baseline;gap:6px;padding:3px 10px;border:1px solid var(--rule);
  font-size:12.5px;color:var(--ink-soft);background:var(--surface)}
.chip-value{font-size:14px;color:var(--ink);font-variant-numeric:tabular-nums}
.chip-name{font-size:11.5px;letter-spacing:.02em}
.chip-good{border-color:var(--good);background:var(--good-wash)}
.chip-good .chip-value{color:var(--good)}
.chip-warn{border-color:var(--warn);background:var(--warn-wash)}
.chip-warn .chip-value{color:var(--warn)}
.chip-bad{border-color:var(--bad);background:var(--bad-wash)}
.chip-bad .chip-value{color:var(--bad)}
.inline-counters{margin:24px 0 20px}

.prose{max-width:74ch}
.prose h1{margin:34px 0 10px;font-size:22px;line-height:1.25}
.prose h1:first-child,.prose h2:first-child{margin-top:0}
.prose h2{margin:28px 0 8px;font-size:19px}
.prose h3{margin:24px 0 6px;font-size:17px}
.prose p{margin:0 0 14px}
.prose a{color:var(--ink);text-decoration:underline;text-underline-offset:2px;
  text-decoration-color:var(--rule)}
.prose ul,.prose ol{margin:0 0 16px;padding-left:1.25em}
.prose li{margin-bottom:7px}
.prose blockquote{margin:0 0 16px;padding-left:16px;border-left:2px solid var(--rule);
  color:var(--ink-soft)}
.prose code{background:var(--wash);padding:1px 5px;font-size:.88em}
.prose pre{background:var(--wash);padding:15px;overflow-x:auto}
.prose pre code{background:none;padding:0}
.prose.empty{color:var(--ink-soft)}
.break{border:0;border-top:1px solid var(--rule);margin:32px 0}
.fields{display:grid;grid-template-columns:minmax(110px,188px) minmax(0,1fr);margin:0 0 20px;
  border-top:1px solid var(--rule-soft)}
.fields dt{padding:9px 16px 9px 0;border-bottom:1px solid var(--rule-soft);
  font-family:var(--sans);font-size:12.5px;line-height:1.5;color:var(--ink-soft)}
.fields dd{margin:0;padding:8px 0 9px;border-bottom:1px solid var(--rule-soft);font-size:16px}

.table-wrap{overflow-x:auto;margin:0 0 22px}
table{width:100%;border-collapse:collapse;font-size:15px}
th{padding:8px 16px 8px 0;border-bottom:1px solid var(--ink);text-align:left;
  font-family:var(--sans);font-size:12.5px;font-weight:600;color:var(--ink-soft);white-space:nowrap}
td{padding:10px 16px 10px 0;border-bottom:1px solid var(--rule-soft);vertical-align:top}
mark{padding:0 3px}
mark.verdict-good{background:var(--good-wash);color:var(--good)}
mark.verdict-warn{background:var(--warn-wash);color:var(--warn)}
mark.verdict-bad{background:var(--bad-wash);color:var(--bad)}
mark.hit{background:#FFE08A;color:var(--ink)}

.compare{border-top:1px solid var(--ink);padding-top:26px;padding-bottom:70px}
.compare h2{margin:0 0 6px;font-size:28px}
.lede{margin:0 0 22px;max-width:58ch;color:var(--ink-soft)}
.compare-table th{white-space:normal}
.compare-table td{font-variant-numeric:tabular-nums}
.mix{min-width:190px}
.mix .bar{height:9px;margin-bottom:5px}
.compare-table tbody th{padding:12px 16px 12px 0;border-bottom:1px solid var(--rule-soft);
  font-family:var(--serif);font-size:17px;font-weight:600;color:var(--ink);vertical-align:top}
.row-sub{display:block;font-family:var(--sans);font-size:12px;font-weight:400;color:var(--ink-soft)}
.unit{color:var(--ink-soft);font-size:13px}
.verdicts .verdict{margin:0 0 6px}

.colophon{border-top:1px solid var(--rule);padding:18px 0 46px;font-family:var(--sans);
  font-size:12.5px;color:var(--ink-soft);display:flex;flex-wrap:wrap;gap:18px}
.colophon kbd{font-family:var(--sans);font-size:11.5px;border:1px solid var(--rule);
  padding:1px 5px;background:var(--surface)}
.empty-page{padding:80px 0;font-size:19px;color:var(--ink-soft)}

@media (max-width:900px){
  .reader{grid-template-columns:minmax(0,1fr);gap:22px}
  .rail-wrap{position:static}
  .stage{padding:22px 20px 30px}
  .tabs{grid-template-columns:repeat(2,minmax(0,1fr))}
  .ledger{grid-template-columns:minmax(0,1fr);gap:28px}
  body{font-size:16px}
}
@media (max-width:620px){
  .shell{padding:0 16px}
  .tabs{grid-template-columns:minmax(0,1fr);gap:0}
  .tab{padding:9px 0 11px}
  .masthead .shell{flex-wrap:wrap;gap:8px}
  .find{width:100%;margin-left:0}
  .find input{flex:1;width:auto}
  .fact{flex:1 1 100%;max-width:none;margin-right:0;border-right:0;
    border-bottom:1px solid var(--rule-soft);padding-right:0}
  .fields{grid-template-columns:minmax(0,1fr)}
  .fields dt{border-bottom:0;padding-bottom:0}
  .fields dd{padding-top:2px}
  .ledger-figure{font-size:48px}
}
@media (prefers-reduced-motion:no-preference){
  .stage{animation:settle .16s ease-out}
  @keyframes settle{from{opacity:.35}to{opacity:1}}
}
@media print{
  .masthead,.tabs,.rail-wrap,.copy,.colophon{display:none}
  .run[hidden],.stage[hidden]{display:block!important}
  .reader{grid-template-columns:1fr}
  body{background:#fff}
  .stage{border:0;padding:0;margin-bottom:28px;page-break-inside:avoid}
}
"""


SCRIPT = """
(function () {
  var runs = [].slice.call(document.querySelectorAll('.run'));
  if (!runs.length) return;
  var tabs = [].slice.call(document.querySelectorAll('.tab'));
  var finder = document.getElementById('find');
  var findCount = document.getElementById('find-count');

  var model = runs.map(function (runEl) {
    var stages = [].slice.call(runEl.querySelectorAll('.stage'));
    return {
      el: runEl,
      id: runEl.dataset.run,
      stages: stages,
      rail: [].slice.call(runEl.querySelectorAll('.rail-item')),
      text: stages.map(function (stage) { return stage.textContent.toLowerCase(); }),
      stage: 0
    };
  });
  var current = 0;

  function showRun(index, moveFocus) {
    current = Math.max(0, Math.min(index, model.length - 1));
    model.forEach(function (run, i) {
      run.el.hidden = i !== current;
    });
    tabs.forEach(function (tab, i) {
      tab.setAttribute('aria-selected', i === current ? 'true' : 'false');
    });
    showStage(model[current].stage, moveFocus);
  }

  function showStage(index, moveFocus) {
    var run = model[current];
    run.stage = Math.max(0, Math.min(index, run.stages.length - 1));
    run.stages.forEach(function (stage, i) { stage.hidden = i !== run.stage; });
    run.rail.forEach(function (item, i) {
      item.setAttribute('aria-selected', i === run.stage ? 'true' : 'false');
    });
    highlight();
    if (history.replaceState) {
      history.replaceState(null, '', '#' + run.id + '/' + run.stage);
    }
    if (moveFocus) {
      var panel = run.stages[run.stage];
      var top = panel.getBoundingClientRect().top;
      if (top < 56 || top > window.innerHeight - 120) {
        panel.scrollIntoView({ block: 'start', behavior: 'auto' });
        window.scrollBy(0, -70);
      }
    }
  }

  tabs.forEach(function (tab, i) {
    tab.addEventListener('click', function () { showRun(i, true); });
  });
  model.forEach(function (run, runIndex) {
    run.rail.forEach(function (item, i) {
      item.addEventListener('click', function () {
        current = runIndex;
        showStage(i, true);
      });
    });
  });
  [].slice.call(document.querySelectorAll('.link[data-run]')).forEach(function (link) {
    link.addEventListener('click', function () {
      var index = model.findIndex(function (run) { return run.id === link.dataset.run; });
      if (index >= 0) {
        showRun(index, false);
        window.scrollTo({ top: 0, behavior: 'auto' });
      }
    });
  });

  // -- search --------------------------------------------------------------

  function clearMarks(root) {
    [].slice.call(root.querySelectorAll('mark.hit')).forEach(function (mark) {
      mark.replaceWith(document.createTextNode(mark.textContent));
    });
    root.normalize();
  }

  function markMatches(root, needle) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var nodes = [];
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue.toLowerCase().indexOf(needle) >= 0) nodes.push(node);
    }
    nodes.forEach(function (textNode) {
      var value = textNode.nodeValue;
      var lower = value.toLowerCase();
      var fragment = document.createDocumentFragment();
      var at = 0;
      var found;
      while ((found = lower.indexOf(needle, at)) >= 0) {
        fragment.appendChild(document.createTextNode(value.slice(at, found)));
        var mark = document.createElement('mark');
        mark.className = 'hit';
        mark.textContent = value.slice(found, found + needle.length);
        fragment.appendChild(mark);
        at = found + needle.length;
      }
      fragment.appendChild(document.createTextNode(value.slice(at)));
      textNode.replaceWith(fragment);
    });
  }

  function occurrences(haystack, needle) {
    var count = 0;
    var at = haystack.indexOf(needle);
    while (at >= 0) { count += 1; at = haystack.indexOf(needle, at + needle.length); }
    return count;
  }

  function highlight() {
    var needle = finder ? finder.value.trim().toLowerCase() : '';
    var matchedStages = 0;
    var matches = 0;
    model.forEach(function (run) {
      run.rail.forEach(function (item, i) {
        var hits = needle ? occurrences(run.text[i], needle) : 0;
        var badge = item.querySelector('.rail-hits');
        badge.hidden = !hits;
        badge.textContent = hits ? String(hits) : '';
        item.classList.toggle('no-hit', !!needle && !hits);
        if (hits) { matchedStages += 1; matches += hits; }
      });
      run.stages.forEach(function (stage) { clearMarks(stage); });
    });
    if (needle) {
      var panel = model[current].stages[model[current].stage];
      if (panel) markMatches(panel, needle);
    }
    if (findCount) {
      findCount.textContent = needle
        ? (matches ? matches + ' in ' + matchedStages + ' stages' : 'nothing found')
        : '';
    }
  }

  function nextMatch() {
    var needle = finder.value.trim().toLowerCase();
    if (!needle) return;
    for (var step = 1; step <= model.length * 40; step += 1) {
      var run = model[current];
      var index = run.stage + step;
      if (index < run.stages.length && run.text[index].indexOf(needle) >= 0) {
        showStage(index, true);
        return;
      }
      if (index >= run.stages.length) break;
    }
    for (var r = 0; r < model.length; r += 1) {
      var candidate = model[(current + r) % model.length];
      for (var s = 0; s < candidate.stages.length; s += 1) {
        if (candidate.text[s].indexOf(needle) >= 0) {
          current = (current + r) % model.length;
          showRun(current, false);
          showStage(s, true);
          return;
        }
      }
    }
  }

  if (finder) {
    var timer = null;
    finder.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(highlight, 110);
    });
    finder.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') { event.preventDefault(); nextMatch(); }
      if (event.key === 'Escape') { finder.value = ''; highlight(); finder.blur(); }
    });
  }

  // -- copy ----------------------------------------------------------------

  [].slice.call(document.querySelectorAll('.copy')).forEach(function (button) {
    button.addEventListener('click', function () {
      var stage = button.closest('.stage');
      var prose = stage.querySelector('.prose');
      var text = prose ? prose.innerText : stage.innerText;
      var done = function () {
        button.textContent = 'Copied';
        setTimeout(function () { button.textContent = 'Copy this stage'; }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallback(text, done); });
      } else {
        fallback(text, done);
      }
    });
  });

  function fallback(text, done) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); done(); } catch (error) { /* nothing to do */ }
    document.body.removeChild(area);
  }

  // -- keys ----------------------------------------------------------------

  document.addEventListener('keydown', function (event) {
    var typing = /input|textarea/i.test(event.target.tagName);
    if (event.key === '/' && !typing) {
      event.preventDefault();
      if (finder) finder.focus();
      return;
    }
    if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === 'ArrowRight' || event.key === 'n') {
      event.preventDefault();
      if (event.shiftKey) showRun(current + 1, true);
      else showStage(model[current].stage + 1, true);
    } else if (event.key === 'ArrowLeft' || event.key === 'p') {
      event.preventDefault();
      if (event.shiftKey) showRun(current - 1, true);
      else showStage(model[current].stage - 1, true);
    } else if (event.key === 'c') {
      var visible = model[current].stages[model[current].stage];
      var copy = visible && visible.querySelector('.copy');
      if (copy) copy.click();
    }
  });

  // -- open where the link points -------------------------------------------

  function fromHash() {
    var parts = (location.hash || '').replace('#', '').split('/');
    var index = model.findIndex(function (run) { return run.id === parts[0]; });
    if (index < 0) { showRun(0, false); return; }
    current = index;
    model[index].stage = parseInt(parts[1], 10) || 0;
    showRun(index, false);
  }

  fromHash();
  window.addEventListener('hashchange', fromHash);
})();
"""


def document(summaries, *, generated=None) -> str:
    """Every run, in one page that needs nothing but a browser."""
    generated = generated or time.strftime("%Y-%m-%d")
    entries = []
    for index, summary in enumerate(summaries):
        stages = summary.all_stages()
        entries.append((f"run-{index}", summary, stages, metrics(summary, stages)))

    head = (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Research chain report</title>\n"
        "<style>" + STYLE + "</style>\n</head>\n<body>\n"
    )

    if not entries:
        return (
            head
            + '<main class="shell"><p class="empty-page">No runs to show yet. '
            "Run the chain, then export it again.</p></main>\n</body>\n</html>\n"
        )

    tabs = _tabs([(run_id, summary, numbers) for run_id, summary, _, numbers in entries])
    sections = "".join(
        run_section(summary, run_id, stages, numbers, active=(position == 0))
        for position, (run_id, summary, stages, numbers) in enumerate(entries)
    )
    compare = _compare(
        [(run_id, summary, numbers) for run_id, summary, _, numbers in entries]
    )

    masthead = (
        '<header class="masthead"><div class="shell">'
        "<p class=\"wordmark\"><b>sales agents</b> &nbsp;research chain, "
        f"exported {escape(generated)}</p>"
        '<div class="find"><label class="visually-hidden" for="find">Search the runs</label>'
        '<input id="find" type="search" placeholder="Search every stage" '
        'autocomplete="off" spellcheck="false">'
        '<span class="find-count" id="find-count" aria-live="polite"></span></div>'
        "</div></header>"
    )

    colophon = (
        '<div class="shell"><footer class="colophon">'
        "<span>Move between stages with <kbd>←</kbd> <kbd>→</kbd></span>"
        "<span>Between accounts with <kbd>shift</kbd> + <kbd>←</kbd> <kbd>→</kbd></span>"
        "<span>Search with <kbd>/</kbd>, then <kbd>enter</kbd> for the next stage</span>"
        "<span>Copy the stage you are reading with <kbd>c</kbd></span>"
        "</footer></div>"
    )

    return (
        head
        + masthead
        + '<main><div class="shell">'
        + tabs
        + "</div>"
        + '<div class="shell">'
        + sections
        + "</div>"
        + '<div class="shell">'
        + compare
        + "</div></main>"
        + colophon
        + "<script>"
        + SCRIPT
        + "</script>\n</body>\n</html>\n"
    )
