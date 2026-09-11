"""The live run view: an overall progress bar, one row per stage, and a feed
of what the model is doing inside the stage that is running right now."""

import sys
import time
from collections import Counter

from . import ui

ACTIVITY_FEED_MAX = 5

PENDING = "pending"
RUNNING = "running"
DONE = "done"
SKIPPED = "skipped"
FAILED = "failed"

_ACTIVITY_ICON = {
    "session": "◇",
    "thinking": "◆",
    "tool_result": "↳",
    "text": "✎",
    "done": "✔",
    "error": "✖",
}
_TOOL_ICON = {"WebSearch": "🔎", "WebFetch": "🌐"}


class _Row:
    __slots__ = (
        "step",
        "status",
        "started",
        "duration",
        "cost_usd",
        "tokens",
        "note",
        "badge",
    )

    def __init__(self, step):
        self.step = step
        self.status = PENDING
        self.started = None
        self.duration = 0.0
        self.cost_usd = 0.0
        self.tokens = 0
        self.note = ""
        self.badge = ""


class Dashboard:
    """Owns the frame. Every mutator is safe to call from the pipeline
    callbacks; rendering is pure enough to unit test."""

    def __init__(
        self,
        steps,
        *,
        clock=time.monotonic,
        out=None,
        live=None,
        width_fn=None,
        height_fn=None,
    ):
        self.rows = [_Row(step) for step in steps]
        self.clock = clock
        self.out = out or sys.stdout
        self.width_fn = width_fn or (lambda: min(ui.terminal_width(), 110))
        self.height_fn = height_fn or ui.terminal_height
        self.current = None
        self.started_at = None
        self.feed = []
        self.tool_counts = Counter()
        self.total_cost = 0.0
        self._pending_metrics = None
        self.region = ui.LiveRegion(
            self.render, stream=self.out, enabled=live, width_fn=self.width_fn
        )

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        self.started_at = self.clock()
        self.region.start()

    def stop(self):
        self.region.stop()

    def log(self, line=""):
        """Write a line that stays in the scrollback, above the live frame."""
        self.region.pause()
        self.out.write(line + "\n")
        self.out.flush()

    def resume(self):
        self.region.resume()

    # -- step transitions --------------------------------------------------

    def step_started(self, index):
        if self.started_at is None:
            self.started_at = self.clock()
        row = self.rows[index]
        row.status = RUNNING
        row.started = self.clock()
        row.duration = 0.0
        self.current = index
        self.feed = []
        self._pending_metrics = None
        if self._plain:
            self.log(
                "  "
                + ui.dim(f"▸ stage {index + 1}/{len(self.rows)}")
                + "  "
                + ui.bold(row.step.title)
            )
        self.region.resume()

    def step_finished(self, index, out_path=None, badge=""):
        row = self.rows[index]
        row.status = DONE
        row.duration = self._elapsed(row)
        row.badge = badge
        if self._pending_metrics:
            row.cost_usd = self._pending_metrics.cost_usd
            row.tokens = self._pending_metrics.tokens
            self.total_cost += row.cost_usd
        self.current = None
        self._pending_metrics = None
        self.log(
            "  "
            + ui.green(ui.GLYPH["done"])
            + " "
            + ui.bold(row.step.title)
            + ui.dim(
                "  ·  "
                + ui.format_duration(row.duration)
                + (f"  ·  {ui.format_cost(row.cost_usd)}" if row.cost_usd else "")
                + (f"  ·  {out_path.name}" if out_path is not None else "")
                + (f"  ·  {badge}" if badge else "")
            )
        )

    def step_skipped(self, index):
        row = self.rows[index]
        row.status = SKIPPED
        row.note = "done earlier"
        self._refresh()

    def step_failed(self, index, message=""):
        row = self.rows[index]
        row.status = FAILED
        row.duration = self._elapsed(row)
        row.note = "failed"
        self.current = None
        self.log("  " + ui.red(ui.GLYPH["failed"]) + " " + ui.bold(row.step.title))
        if message:
            self.log("    " + ui.red(message))

    # -- activity ----------------------------------------------------------

    def activity(self, act):
        if act.kind == "done":
            self._pending_metrics = act
            return
        if act.kind == "tool":
            self.tool_counts[act.label] += 1
            if self._plain:
                self.log(
                    "      "
                    + _TOOL_ICON.get(act.label, "⚙")
                    + " "
                    + act.label
                    + ("  " + act.detail if act.detail else "")
                )
        if act.kind == "tool_result":
            self._attach_result(act)
            return
        if act.kind in ("thinking", "text") and self.feed and self.feed[-1].kind == act.kind:
            self.feed[-1] = _FeedEntry(act)
        else:
            self.feed.append(_FeedEntry(act))
        del self.feed[:-ACTIVITY_FEED_MAX]
        self._refresh()

    def _attach_result(self, act):
        for entry in reversed(self.feed):
            if entry.kind == "tool" and entry.label == act.label and not entry.result:
                entry.result = act.tokens
                break
        self._refresh()

    # -- rendering ---------------------------------------------------------

    def render(self):
        width = max(30, self.width_fn())
        lines = ["", self._progress_line(width), ""]

        reserved = len(lines) + (ACTIVITY_FEED_MAX + 1 if self.current is not None else 0)
        budget = max(1, self.height_fn() - reserved)
        window, hidden_before, hidden_after = self._window(budget)

        if hidden_before:
            lines.append(ui.dim(f"    … {hidden_before} earlier stages"))
        for index in window:
            lines.append(self._step_line(index, width))
        if hidden_after:
            lines.append(ui.dim(f"    … {hidden_after} more stages"))

        if self.current is not None and self.feed:
            lines.append("")
            lines.extend(self._feed_line(entry) for entry in self.feed)

        return [ui.truncate(line, width) for line in lines]

    def _progress_line(self, width):
        done = sum(1 for row in self.rows if row.status in (DONE, SKIPPED))
        bar = ui.progress_bar(done, len(self.rows), width=min(28, max(10, width // 4)))
        parts = [f"{done}/{len(self.rows)} stages", ui.format_duration(self.elapsed)]
        if self.total_cost or self._pending_metrics:
            parts.append(ui.format_cost(self.total_cost))
        searches = self.tool_counts.get("WebSearch", 0)
        fetches = self.tool_counts.get("WebFetch", 0)
        if searches or fetches:
            parts.append(f"{searches} searches · {fetches} pages")
        return "  " + bar + "  " + ui.dim(" · ".join(parts))

    def _step_line(self, index, width):
        row = self.rows[index]
        glyph, paint = self._glyph(row)
        right = self._right_column(row)
        number = ui.dim(f"{index:>2}")
        title_width = max(10, width - 8 - ui.visible_width(right))
        title = ui.truncate(row.step.title, title_width)
        if row.status == RUNNING:
            title = ui.bold(title)
        elif row.status == PENDING:
            title = ui.dim(title)
        body = f"  {paint(glyph)} {number}  " + ui.pad(title, title_width)
        return body + ui.dim(right)

    def _glyph(self, row):
        if row.status == RUNNING:
            tick = int((self.clock() - (row.started or 0)) * 8)
            return ui.spinner_frame(tick), ui.cyan
        if row.status == DONE:
            return ui.GLYPH["done"], ui.green
        if row.status == FAILED:
            return ui.GLYPH["failed"], ui.red
        if row.status == SKIPPED:
            return ui.GLYPH["skipped"], ui.dim
        return ui.GLYPH["pending"], ui.dim

    def _right_column(self, row):
        if row.status == RUNNING:
            return ui.format_duration(self._elapsed(row))
        if row.status == DONE:
            parts = [ui.format_duration(row.duration)]
            if row.badge:
                parts.append(row.badge)
            elif row.tokens:
                parts.append(ui.format_tokens(row.tokens) + " tok")
            return "  ".join(parts)
        if row.status in (SKIPPED, FAILED):
            return row.note
        return ""

    def _feed_line(self, entry):
        icon = entry.icon()
        text = entry.text()
        return "      " + ui.dim("│ ") + icon + " " + text

    def _window(self, budget):
        total = len(self.rows)
        if budget >= total:
            return list(range(total)), 0, 0
        focus = self.current if self.current is not None else self._last_touched()
        rows = max(1, budget)
        start = max(0, min(focus - rows // 2, total - rows))
        if start > 0:
            rows = max(1, rows - 1)
            start = max(0, min(focus - rows // 2, total - rows))
        end = start + rows
        if end < total:
            rows = max(1, rows - 1)
            end = start + rows
        return list(range(start, end)), start, total - end

    def _last_touched(self):
        for index in range(len(self.rows) - 1, -1, -1):
            if self.rows[index].status != PENDING:
                return index
        return 0

    # -- summary -----------------------------------------------------------

    def summary(self, run_dir):
        done = sum(1 for row in self.rows if row.status in (DONE, SKIPPED))
        lines = [
            ui.bold("Run complete") if done == len(self.rows) else ui.bold("Run stopped"),
            "",
            ui.field_row("Steps", f"{done}/{len(self.rows)}"),
            ui.field_row("Time", ui.format_duration(self.elapsed)),
            ui.field_row("Cost", ui.format_cost(self.total_cost)),
            ui.field_row(
                "Research",
                f"{self.tool_counts.get('WebSearch', 0)} searches, "
                f"{self.tool_counts.get('WebFetch', 0)} pages fetched",
            ),
            ui.field_row("Output", str(run_dir)),
        ]
        self.region.pause()
        self.out.write("\n" + "\n".join(lines) + "\n")
        self.out.flush()

    # -- helpers -----------------------------------------------------------

    @property
    def _plain(self):
        """No live frame (piped output, --plain): narrate in flat lines."""
        return not self.region.enabled

    @property
    def elapsed(self):
        if self.started_at is None:
            return 0.0
        return self.clock() - self.started_at

    def _elapsed(self, row):
        if row.started is None:
            return row.duration
        return self.clock() - row.started

    def _refresh(self):
        self.region.refresh()


class _FeedEntry:
    __slots__ = ("kind", "label", "detail", "tokens", "result")

    def __init__(self, act):
        self.kind = act.kind
        self.label = act.label
        self.detail = act.detail
        self.tokens = act.tokens
        self.result = 0

    def icon(self):
        if self.kind == "tool":
            return _TOOL_ICON.get(self.label, "⚙")
        return _ACTIVITY_ICON.get(self.kind, "·")

    def text(self):
        if self.kind == "tool":
            body = ui.bold(self.label)
            if self.detail:
                body += "  " + ui.dim(self.detail)
            if self.result:
                body += ui.dim(f"  ← {ui.format_tokens(self.result)} chars")
            return body
        if self.kind == "thinking":
            return ui.dim(f"{self.label} · {ui.format_tokens(self.tokens)} tokens")
        if self.kind == "text":
            return ui.dim(f"{self.label} · {ui.format_tokens(self.tokens)} chars")
        detail = f" · {self.detail}" if self.detail else ""
        return ui.dim(f"{self.label}{detail}")
