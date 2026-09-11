"""Reads the machine-readable counters every stage is told to end with, and
turns them into the verdicts the workshop grades on.

    VERIFIED: n | ASSERTED: n | TOTAL: n
    ROWS: n | FAILED A: n | FAILED B: n | FAILED C: n | FAILED D: n
    SENTENCES: n | FROM PACK: n | GENERIC: n | MADE UP: n | BANNED: n
"""

import re

from . import ui
from .steps import STEPS

COUNTER_NAMES = (
    "VERIFIED",
    "ASSERTED",
    "TOTAL",
    "ROWS",
    "FAILED A",
    "FAILED B",
    "FAILED C",
    "FAILED D",
    "SENTENCES",
    "FROM PACK",
    "GENERIC",
    "MADE UP",
    "BANNED",
)

_COUNTER_RE = re.compile(
    r"\b(" + "|".join(name.replace(" ", r"\s+") for name in COUNTER_NAMES) + r")\s*:\s*(\d+)",
    re.IGNORECASE,
)


def parse_counts(text: str) -> dict:
    """Later counters win, so the summary line at the end of a stage beats any
    example line earlier in it."""
    counts = {}
    for name, value in _COUNTER_RE.findall(text or ""):
        counts[" ".join(name.upper().split())] = int(value)
    return counts


def sourced_ratio(counts: dict):
    """Share of graded rows that named a real source (check A)."""
    rows = counts.get("ROWS", 0)
    if not rows:
        return None
    return (rows - counts.get("FAILED A", 0)) / rows


def research_verdict(counts: dict):
    ratio = sourced_ratio(counts)
    if ratio is None:
        return None
    if ratio < 0.5:
        return "bad", "Not usable in front of a buyer."
    if ratio < 0.75:
        return "warn", "Normal first attempt. Fix the prompt, not the chat."
    return "good", "Strong. Check it is useful, not just cautious."


def message_verdict(counts: dict):
    sentences = counts.get("SENTENCES", 0)
    if not sentences:
        return None
    made_up = counts.get("MADE UP", 0)
    banned = counts.get("BANNED", 0)
    if made_up or banned:
        return "bad", f"Does not go out: {made_up} made up, {banned} banned."
    if counts.get("GENERIC", 0) / sentences > 0.30:
        return "warn", "The research did not earn the email. Fix the sentences."
    if counts.get("FROM PACK", 0) / sentences > 0.70:
        return "good", "Strong. Read it aloud and check a person could have written it."
    return "warn", "Thin. Most sentences should trace to a pack field."


def badge(text: str) -> str:
    """A few words about a stage's counters, for the step row."""
    counts = parse_counts(text)
    if not counts:
        return ""
    if "SENTENCES" in counts:
        return (
            f"{counts.get('FROM PACK', 0)} from pack · "
            f"{counts.get('MADE UP', 0)} made up · {counts.get('BANNED', 0)} banned"
        )
    if "ROWS" in counts:
        return f"{counts.get('FAILED A', 0)}/{counts['ROWS']} rows unsourced"
    if "TOTAL" in counts or "VERIFIED" in counts:
        return (
            f"{counts.get('VERIFIED', 0)} verified · {counts.get('ASSERTED', 0)} asserted"
        )
    return ""


_VERDICT_PAINT = {"good": ui.green, "warn": ui.yellow, "bad": ui.red}


def report(outputs: dict):
    """Printable lines: the counters each stage reported, and what the
    workshop's thresholds make of them."""
    lines = []
    for step_id, text in outputs.items():
        counts = parse_counts(text)
        if not counts:
            continue
        verdict = None
        if "SENTENCES" in counts:
            verdict = message_verdict(counts)
        elif "ROWS" in counts:
            verdict = research_verdict(counts)

        title = STEPS[step_id].title if step_id in STEPS else step_id
        summary = " | ".join(
            f"{name}: {counts[name]}" for name in COUNTER_NAMES if name in counts
        )
        lines.append("  " + ui.pad(ui.bold(title), 44) + ui.dim(summary))
        if verdict:
            level, message = verdict
            lines.append("  " + " " * 44 + _VERDICT_PAINT[level](message))
    return lines
