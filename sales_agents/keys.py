"""Reading single keypresses from a terminal, without echo or a newline.

Bytes are read straight from the file descriptor: a buffered text stream
swallows the rest of an escape sequence, which makes every arrow key look
like a bare Escape."""

import os
import select
import sys

_SEQUENCES = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
    "\x1bOA": "up",
    "\x1bOB": "down",
    "\x1bOC": "right",
    "\x1bOD": "left",
    "\x1b[5~": "pgup",
    "\x1b[6~": "pgdn",
    "\x1b[H": "home",
    "\x1b[F": "end",
    "\x1b[1~": "home",
    "\x1b[4~": "end",
    "\x1b": "esc",
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    " ": "space",
    "\x03": "ctrl-c",
    "\x04": "ctrl-d",
    "\x7f": "backspace",
}

ESCAPE_WAIT = 0.05  # seconds to wait for the rest of an escape sequence


def decode(sequence: str) -> str:
    """Map a raw byte sequence to a key name. Unknown sequences map to ""."""
    if sequence in _SEQUENCES:
        return _SEQUENCES[sequence]
    if len(sequence) == 1 and sequence.isprintable():
        return sequence.lower()
    return ""


def read_key(read_byte, has_more) -> str:
    """One keypress, given a byte reader and a "more bytes waiting?" check.

    read_byte() returns a single byte, or b"" at end of input.
    has_more(timeout) says whether another byte is already on its way."""
    first = read_byte()
    if not first:
        return "ctrl-d"
    if first != b"\x1b":
        return decode(first.decode("utf-8", "ignore"))

    sequence = first
    while len(sequence) < 8 and has_more(ESCAPE_WAIT):
        nxt = read_byte()
        if not nxt:
            break
        sequence += nxt
        name = decode(sequence.decode("utf-8", "ignore"))
        if name:
            return name
    text = sequence.decode("utf-8", "ignore")
    if text == "\x1b":
        return "esc"
    return decode(text)  # "" for a sequence we do not know


class Reader:
    """Context manager that puts the terminal in cbreak mode for its scope."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdin
        self._saved = None
        self._termios = None

    @property
    def usable(self):
        return bool(getattr(self.stream, "isatty", lambda: False)())

    def __enter__(self):
        if not self.usable:
            return self
        try:
            import termios
            import tty
        except ImportError:  # not a POSIX terminal
            return self
        self._termios = termios
        fd = self.stream.fileno()
        self._saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        return self

    def __exit__(self, *exc):
        if self._saved is not None:
            self._termios.tcsetattr(
                self.stream.fileno(), self._termios.TCSADRAIN, self._saved
            )
            self._saved = None
        return False

    def read(self) -> str:
        fd = self.stream.fileno()

        def read_byte():
            try:
                return os.read(fd, 1)
            except OSError:
                return b""

        def has_more(timeout):
            try:
                return bool(select.select([fd], [], [], timeout)[0])
            except OSError:
                return False

        return read_key(read_byte, has_more)
