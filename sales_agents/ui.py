"""Terminal presentation primitives: colour, measurement, input fields and a
repainting live region. Stdlib only, so the CLI stays installable by copying
the repo. Everything degrades to plain text when stdout is not a terminal."""

import atexit
import os
import re
import shutil
import sys
import threading
import time
import unicodedata

ESC = "\x1b"
RESET = f"{ESC}[0m"
HIDE_CURSOR = f"{ESC}[?25l"
SHOW_CURSOR = f"{ESC}[?25h"
ERASE_LINE = f"{ESC}[2K"
ERASE_BELOW = f"{ESC}[0J"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
BAR_FULL = "▰"
BAR_EMPTY = "▱"

BOX = {"tl": "╭", "tr": "╮", "bl": "╰", "br": "╯", "h": "─", "v": "│"}

# Status glyphs, shared by the dashboard and the summary.
GLYPH = {
    "done": "✔",
    "failed": "✖",
    "skipped": "↷",
    "pending": "○",
    "running": "●",
}

_COLOR = None


# --------------------------------------------------------------------------
# colour
# --------------------------------------------------------------------------


def detect_color(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def set_color(enabled: bool) -> None:
    global _COLOR
    _COLOR = bool(enabled)


def color_enabled() -> bool:
    global _COLOR
    if _COLOR is None:
        _COLOR = detect_color()
    return _COLOR


def _sgr(text: str, *codes: str) -> str:
    if not text or not color_enabled():
        return text
    return f"{ESC}[{';'.join(codes)}m{text}{RESET}"


def bold(text):
    return _sgr(text, "1")


def dim(text):
    return _sgr(text, "2")


def italic(text):
    return _sgr(text, "3")


def cyan(text):
    return _sgr(text, "36")


def green(text):
    return _sgr(text, "32")


def yellow(text):
    return _sgr(text, "33")


def red(text):
    return _sgr(text, "31")


def magenta(text):
    return _sgr(text, "35")


def blue(text):
    return _sgr(text, "34")


# --------------------------------------------------------------------------
# measurement
# --------------------------------------------------------------------------


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return 2
    return 1


def visible_width(text: str) -> int:
    return sum(_char_width(char) for char in strip_ansi(text))


def truncate(text: str, width: int) -> str:
    """Clip to `width` display columns, keeping escape sequences intact."""
    if width <= 0:
        return ""
    if visible_width(text) <= width:
        return text

    out = []
    used = 0
    saw_escape = False
    index = 0
    limit = width - 1  # leave a column for the ellipsis
    while index < len(text):
        match = _ANSI_RE.match(text, index)
        if match:
            saw_escape = True
            out.append(match.group())
            index = match.end()
            continue
        char_width = _char_width(text[index])
        if used + char_width > limit:
            break
        out.append(text[index])
        used += char_width
        index += 1
    out.append("…")
    if saw_escape:
        out.append(RESET)
    return "".join(out)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_width(text))


def terminal_width(default: int = 80) -> int:
    return shutil.get_terminal_size((default, 24)).columns


def terminal_height(default: int = 24) -> int:
    return shutil.get_terminal_size((80, default)).lines


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def format_tokens(count) -> str:
    count = int(count or 0)
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


def format_cost(usd) -> str:
    usd = float(usd or 0.0)
    if usd <= 0:
        return "$0.00"
    if usd < 0.01:
        return "<$0.01"
    return f"${usd:.2f}"


def progress_bar(done: int, total: int, width: int = 24) -> str:
    if width <= 0:
        return ""
    ratio = 0.0 if total <= 0 else max(0.0, min(1.0, done / total))
    filled = int(round(width * ratio))
    return cyan(BAR_FULL * filled) + dim(BAR_EMPTY * (width - filled))


def spinner_frame(tick: int) -> str:
    return SPINNER_FRAMES[int(tick) % len(SPINNER_FRAMES)]


# --------------------------------------------------------------------------
# layout
# --------------------------------------------------------------------------


def panel(lines, width=None, border=dim):
    width = width or min(terminal_width(), 80)
    inner = max(1, width - 4)
    top = BOX["tl"] + BOX["h"] * (width - 2) + BOX["tr"]
    bottom = BOX["bl"] + BOX["h"] * (width - 2) + BOX["br"]
    body = [
        border(BOX["v"]) + " " + pad(truncate(line, inner), inner) + " " + border(BOX["v"])
        for line in lines
    ]
    return [border(top)] + body + [border(bottom)]


def field_row(label: str, value: str, label_width: int = 16) -> str:
    return "  " + pad(dim(label), label_width) + value


def rule(width=None, char=BOX["h"]) -> str:
    return dim(char * (width or terminal_width()))


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------


class InputAborted(RuntimeError):
    """The reader hit EOF or Ctrl-C while a question was on screen."""


PROMPT = "❯ "


def ask(
    label,
    *,
    hint="",
    default="",
    required=True,
    validate=None,
    note="",
    input_fn=input,
    out=None,
):
    """Ask one question. Returns the trimmed answer, or the default when the
    answer is blank. Re-asks until the answer passes `validate`."""
    out = out or sys.stdout
    head = "  " + cyan("▌") + " " + bold(label)
    if note:
        head += "  " + dim(note)
    out.write("\n" + head + "\n")
    if hint:
        out.write("    " + dim(hint) + "\n")
    if default:
        out.write("    " + dim(f"enter to keep: {default}") + "\n")
    out.flush()

    while True:
        try:
            answer = input_fn("  " + cyan(PROMPT)).strip()
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            raise InputAborted(label)

        if not answer and default:
            answer = default
        if not answer and required:
            out.write("    " + yellow("this one is required") + "\n")
            out.flush()
            continue
        if answer and validate:
            problem = validate(answer)
            if problem:
                out.write("    " + yellow(problem) + "\n")
                out.flush()
                continue
        return answer


def ask_choice(label, choices, *, default=None, hint="", input_fn=input, out=None):
    out = out or sys.stdout
    rendered = " / ".join(
        bold(choice) if choice == default else choice for choice in choices
    )
    full_hint = f"{hint} ({rendered})" if hint else rendered

    def validate(value):
        if value not in choices:
            return f"pick one of: {', '.join(choices)}"
        return None

    return ask(
        label,
        hint=full_hint,
        default=default or "",
        validate=validate,
        input_fn=input_fn,
        out=out,
    )


def confirm(label, *, default=True, input_fn=input, out=None):
    suffix = "Y/n" if default else "y/N"
    answer = ask(
        label,
        hint=suffix,
        required=False,
        input_fn=input_fn,
        out=out,
    ).lower()
    if not answer:
        return default
    return answer.startswith("y")


# --------------------------------------------------------------------------
# live region
# --------------------------------------------------------------------------


class LiveRegion:
    """A block of lines at the bottom of the screen that repaints in place.

    `render()` is called on every frame and must return the current lines.
    When disabled (no tty, --plain) every method is a no-op so callers do not
    have to branch."""

    def __init__(
        self,
        render,
        *,
        stream=None,
        fps=10,
        enabled=None,
        width_fn=terminal_width,
    ):
        self.render = render
        self.stream = stream or sys.stdout
        self.fps = fps
        self.enabled = detect_color(self.stream) if enabled is None else bool(enabled)
        self.width_fn = width_fn
        self._painted = 0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._cursor_hidden = False
        self._atexit_registered = False

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        if not self.enabled or self._thread:
            return
        self._hide_cursor()
        self._stop.clear()
        if self.fps:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        if not self.enabled:
            return
        self._halt_thread()
        self._erase()
        self._show_cursor()

    def pause(self):
        """Take the frame off screen so ordinary prints land cleanly."""
        if not self.enabled:
            return
        self._halt_thread()
        self._erase()
        self._show_cursor()

    def resume(self):
        if not self.enabled:
            return
        self._hide_cursor()
        self.start()
        self.refresh()

    # -- painting ----------------------------------------------------------

    def refresh(self):
        if not self.enabled:
            return
        width = max(8, self.width_fn())
        lines = [truncate(line, width) for line in self.render()]
        with self._lock:
            chunks = []
            if self._painted:
                chunks.append(f"{ESC}[{self._painted}A")
            for line in lines:
                chunks.append(ERASE_LINE + line + "\n")
            leftover = self._painted - len(lines)
            if leftover > 0:
                chunks.extend([ERASE_LINE + "\n"] * leftover)
                chunks.append(f"{ESC}[{leftover}A")
            self._painted = len(lines)
            self._write("".join(chunks))

    def _loop(self):
        interval = 1.0 / max(1, self.fps)
        while not self._stop.wait(interval):
            try:
                self.refresh()
            except Exception:  # a repaint must never take the run down
                return

    def _halt_thread(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _erase(self):
        with self._lock:
            if self._painted:
                self._write(f"{ESC}[{self._painted}A" + ERASE_BELOW)
                self._painted = 0

    def _hide_cursor(self):
        if not self._cursor_hidden:
            self._write(HIDE_CURSOR)
            self._cursor_hidden = True
            if not self._atexit_registered:
                atexit.register(self._show_cursor)  # never strand a hidden cursor
                self._atexit_registered = True

    def _show_cursor(self):
        if self._cursor_hidden:
            self._write(SHOW_CURSOR)
            self._cursor_hidden = False

    def _write(self, text):
        try:
            self.stream.write(text)
            self.stream.flush()
        except (ValueError, OSError):  # stream closed underneath us
            self.enabled = False


def sleep(seconds: float) -> None:
    time.sleep(seconds)
