"""Full-screen viewer: pick a run, then read every stage's output with the
stage list on the left and the text on the right."""

import os
import shlex
import subprocess
import sys

from . import keys, markdown, ui

_VERDICT_PAINT = {"good": ui.green, "warn": ui.yellow, "bad": ui.red}


class _View:
    """Shared frame plumbing: fixed height, fixed width, footer of keys."""

    def __init__(self, *, width_fn=None, height_fn=None):
        self.width_fn = width_fn or (lambda: min(ui.terminal_width(), 140))
        self.height_fn = height_fn or ui.terminal_height

    def _frame(self, header, body, footer, height, width):
        lines = [header, ""]
        lines.extend(body)
        while len(lines) < height - 2:
            lines.append("")
        lines = lines[: height - 2]
        lines.append("")
        lines.append(footer)
        return [ui.truncate(line, width) for line in lines[:height]]


class StageBrowser(_View):
    KEYS = "↑↓ scroll · ←→ stage · e edit · r runs · q quit"

    def __init__(self, summary, **kwargs):
        super().__init__(**kwargs)
        self.summary = summary
        self.stages = summary.stages()
        self.selected = 0
        self.scroll = 0

    # -- content -----------------------------------------------------------

    @property
    def stage(self):
        return self.stages[self.selected]

    def lines(self):
        """The selected stage's markdown, rendered to the content pane."""
        stage = self.stage
        if not stage.exists:
            return [
                "",
                ui.dim("  This stage has not run yet."),
                "",
                ui.dim(f"  It will write {stage.step.output_name} when it does."),
            ]
        return markdown.render(stage.text, self._content_width())

    def _content_width(self):
        return max(20, self.width_fn() - self._list_width() - 3)

    def _list_width(self):
        width = self.width_fn()
        return max(24, min(42, width // 3))

    def _body_height(self):
        return max(1, self.height_fn() - 4)

    def _max_scroll(self):
        return max(0, len(self.lines()) - self._body_height())

    # -- keys --------------------------------------------------------------

    def handle(self, key):
        if key in ("q", "ctrl-c", "ctrl-d"):
            return "quit"
        if key in ("r", "esc"):
            return "back"
        if key == "e":
            return "edit"
        if key in ("right", "tab", "n"):
            self._select(self.selected + 1)
        elif key in ("left", "p"):
            self._select(self.selected - 1)
        elif key in ("down", "j", "enter"):
            self._scroll_by(1)
        elif key in ("up", "k"):
            self._scroll_by(-1)
        elif key in ("pgdn", "space"):
            self._scroll_by(self._body_height())
        elif key in ("pgup", "b"):
            self._scroll_by(-self._body_height())
        elif key in ("end", "g"):
            self.scroll = self._max_scroll()
        elif key == "home":
            self.scroll = 0
        return None

    def _scroll_by(self, delta):
        self.scroll = max(0, min(self._max_scroll(), self.scroll + delta))

    def _select(self, index):
        index = max(0, min(len(self.stages) - 1, index))
        if index != self.selected:
            self.selected = index
            self.scroll = 0

    # -- rendering ---------------------------------------------------------

    def render(self):
        width = max(40, self.width_fn())
        height = max(8, self.height_fn())
        list_width = self._list_width()
        content_width = self._content_width()

        state = self.summary.state
        header = (
            "  "
            + ui.bold(state.company)
            + ui.dim(
                f"   {state.seller} → {state.offering}"
                if state.offering
                else f"   {state.seller}"
            )
            + ui.dim(f"   {state.date}")
        )

        left = self._stage_rows(list_width) + [""] + self._meta_rows(list_width)
        right = self.lines()[self.scroll : self.scroll + self._body_height()]

        body = []
        for index in range(self._body_height()):
            cell = left[index] if index < len(left) else ""
            text = right[index] if index < len(right) else ""
            body.append(
                ui.pad(ui.truncate(cell, list_width), list_width)
                + ui.dim(" │ ")
                + ui.truncate(text, content_width)
            )

        return self._frame(header, body, self._footer(width), height, width)

    def _stage_rows(self, width):
        rows = []
        for index, stage in enumerate(self.stages):
            chosen = index == self.selected
            glyph, paint = self._glyph(stage)
            title = stage.step.title
            if chosen:
                title = ui.bold(ui.cyan(title))
            elif not stage.exists:
                title = ui.dim(title)
            marker = ui.cyan("❯") if chosen else " "
            rows.append(
                f"{marker} {paint(glyph)} " + ui.truncate(title, max(8, width - 5))
            )
        return rows

    def _glyph(self, stage):
        """The tick says the stage ran; its colour, and "!", say what the
        grader made of what it produced."""
        if not stage.exists:
            return ui.GLYPH["pending"], ui.dim
        verdict = stage.verdict
        if verdict:
            level = verdict[0]
            return ("!" if level == "bad" else ui.GLYPH["done"]), _VERDICT_PAINT[level]
        return ui.GLYPH["done"], ui.green

    def _meta_rows(self, width):
        stage = self.stage
        if not stage.exists:
            return [ui.dim("  not run yet")]
        rows = [ui.dim("  " + stage.path.name)]
        if stage.counts:
            rows.extend(
                ui.dim("  " + line)
                for line in markdown.wrap(
                    " | ".join(f"{k}: {v}" for k, v in stage.counts.items()), width - 2
                )
            )
        verdict = stage.verdict
        if verdict:
            level, message = verdict
            rows.extend(
                "  " + _VERDICT_PAINT[level](line)
                for line in markdown.wrap(message, width - 2)
            )
        return rows

    def _footer(self, width):
        total = len(self.lines())
        shown = min(total, self.scroll + self._body_height())
        position = f"{self.scroll + 1}-{shown} of {total}" if total else "empty"
        stage_no = f"stage {self.selected + 1}/{len(self.stages)}"
        return "  " + ui.dim(f"{stage_no} · {position}   {self.KEYS}")


class RunPicker(_View):
    KEYS = "↑↓ select · enter open · q quit"

    def __init__(self, summaries, **kwargs):
        super().__init__(**kwargs)
        self.summaries = list(summaries)
        self.selected = 0
        self.chosen = None

    def handle(self, key):
        if key in ("q", "ctrl-c", "ctrl-d"):
            return "quit"
        if key in ("down", "j"):
            self.selected = min(len(self.summaries) - 1, self.selected + 1)
        elif key in ("up", "k"):
            self.selected = max(0, self.selected - 1)
        elif key in ("enter", "right", "space"):
            if self.summaries:
                self.chosen = self.summaries[self.selected]
                return "open"
        return None

    def render(self):
        width = max(40, self.width_fn())
        height = max(8, self.height_fn())
        header = "  " + ui.bold("Runs") + ui.dim("   pick one to read its stages")

        body = []
        for index, summary in enumerate(self.summaries):
            chosen = index == self.selected
            marker = ui.cyan("❯") if chosen else " "
            name = summary.state.company
            name = ui.bold(ui.cyan(name)) if chosen else ui.bold(name)
            status = (
                ui.green("complete")
                if summary.complete
                else ui.dim("next: " + summary.next_title)
            )
            body.append(
                f"{marker} "
                + ui.progress_bar(summary.done, summary.total, width=14)
                + f"  {summary.done:>2}/{summary.total}  "
                + ui.column(name, 26)
                + status
            )
            body.append("    " + ui.dim(str(summary.run_dir)))
        if not self.summaries:
            body.append("  " + ui.dim("No runs yet."))

        return self._frame(header, body, "  " + ui.dim(self.KEYS), height, width)


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


def browse(summaries, *, start=None, screen=None, reader=None, out=None):
    """Run the viewer until the reader quits. `start` opens one run directly
    and returns when it is closed."""
    out = out or sys.stdout
    summaries = list(summaries)
    screen = screen if screen is not None else ui.Screen(stream=out)
    reader = reader if reader is not None else keys.Reader()

    view = StageBrowser(start) if start else RunPicker(summaries)
    with screen, reader:
        while True:
            screen.draw(view.render())
            key = reader.read()
            action = view.handle(key)

            if action == "quit":
                return 0
            if action == "open":
                view = StageBrowser(view.chosen)
            elif action == "back":
                if start:
                    return 0
                view = RunPicker(summaries)
            elif action == "edit":
                _edit(screen, view.stage.path)


def _edit(screen, path):
    if not path.exists():
        return
    command = shlex.split(os.environ.get("EDITOR", "vi")) + [str(path)]
    with screen.suspended():
        subprocess.run(command)
