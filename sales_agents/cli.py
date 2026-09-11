"""Command line entry point: collect the three inputs, then run the chain
under a live dashboard."""

import argparse
import functools
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import pairings, scoreboard, settings, ui
from .dashboard import Dashboard
from .pipeline import MissingDependencyError, Pipeline
from .runner import DEFAULT_TIMEOUT, ClaudeRunError, run_claude
from .state import RunState, slugify
from .steps import STEP_ORDER, STEPS

DEFAULT_RUNS_DIR = Path("research-chain") / "outputs"
LABEL_WIDTH = 16

FIELDS = (
    (
        "seller",
        "You sell for",
        "the company whose product you are selling, e.g. MoveInSync",
    ),
    (
        "offering",
        "What they sell",
        "one line on the product and who buys it",
    ),
    (
        "company",
        "Target account",
        "the company you want to sell into, e.g. Tata Steel",
    ),
)


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sales-agents",
        description=(
            "Chain sales-research prompts (ICP → industry → account → roles → "
            "people → pack → grade → emails → LinkedIn → grade messages) "
            "through the Claude Code CLI. Run with no arguments to be asked "
            "for the three inputs."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Start a new research chain (asks for anything missing).")
    run_p.add_argument("--seller", help="Who you sell for, e.g. 'MoveInSync'.")
    run_p.add_argument(
        "--sells",
        "--offering",
        dest="offering",
        help="What they sell, in one line.",
    )
    run_p.add_argument("--company", help="Target account name.")
    run_p.add_argument(
        "--industry",
        help="Target account's industry (default: the chain works it out).",
    )
    run_p.add_argument("--group", default="", help="Workshop group label (optional).")
    run_p.add_argument(
        "--style",
        choices=["a", "b", "both"],
        default=None,
        help="Email style to generate (default: a).",
    )
    run_p.add_argument("--model", default=None, help="Model alias passed to `claude --model`.")
    run_p.add_argument(
        "--out-dir",
        default=str(DEFAULT_RUNS_DIR),
        help=f"Where run folders live (default: {DEFAULT_RUNS_DIR}).",
    )
    run_p.add_argument(
        "--auto",
        action="store_true",
        help="Run the whole chain without pausing to review each stage.",
    )
    run_p.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Stop a stage if it would cost more than this many dollars.",
    )
    run_p.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Seconds to allow per stage (default: {DEFAULT_TIMEOUT}).",
    )
    run_p.add_argument("--date", default=None, help="Date stamped on the pack (default: today).")
    _add_display_flags(run_p)

    cont_p = sub.add_parser("continue", help="Resume an existing run.")
    cont_p.add_argument("run_dir", help="Path to the run's output directory.")
    cont_p.add_argument("--auto", action="store_true")
    cont_p.add_argument("--budget", type=float, default=None)
    cont_p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    _add_display_flags(cont_p)

    list_p = sub.add_parser("list", help="List runs and how far each one got.")
    list_p.add_argument("--out-dir", default=str(DEFAULT_RUNS_DIR))
    _add_display_flags(list_p)

    return parser


def _add_display_flags(parser) -> None:
    parser.add_argument(
        "--plain",
        action="store_true",
        help="No colour, no animation. Use this in CI or when piping to a file.",
    )


def steps_for_style(style: str):
    ids = list(STEP_ORDER)
    if style == "a":
        return [s for s in ids if s != "emails_b"]
    if style == "b":
        return [s for s in ids if s != "emails_a"]
    return ids


# --------------------------------------------------------------------------
# the wizard
# --------------------------------------------------------------------------


def collect_inputs(
    *,
    seller=None,
    offering=None,
    company=None,
    industry=None,
    defaults=None,
    input_fn=input,
    out=None,
):
    """Ask for whatever was not passed on the command line. Only the answers
    that stay the same between runs are pre-filled."""
    out = out or sys.stdout
    defaults = defaults or {}
    supplied = {"seller": seller, "offering": offering, "company": company}
    sticky = {"seller", "offering"}

    values = {}
    asked = 0
    total = sum(1 for key, _, _ in FIELDS if not supplied.get(key))
    for key, label, hint in FIELDS:
        given = supplied.get(key)
        if given:
            values[key] = given.strip()
            continue
        asked += 1
        values[key] = ui.ask(
            label,
            hint=hint,
            default=defaults.get(key, "") if key in sticky else "",
            note=f"{asked} of {total}",
            input_fn=input_fn,
            out=out,
        )

    values["industry"] = (industry or "").strip()
    return values


def _plan_lines(values, run_dir, step_ids, model, style):
    return [
        ui.field_row("You sell for", ui.bold(values["seller"]), LABEL_WIDTH),
        ui.field_row("What they sell", values["offering"], LABEL_WIDTH),
        ui.field_row("Target account", ui.bold(values["company"]), LABEL_WIDTH),
        ui.field_row(
            "Industry",
            values["industry"] or ui.dim("worked out from the account"),
            LABEL_WIDTH,
        ),
        ui.field_row(
            "Plan",
            f"{len(step_ids)} stages · {model} · email style {style}",
            LABEL_WIDTH,
        ),
        ui.field_row("Output", str(run_dir), LABEL_WIDTH),
    ]


def _banner(out):
    width = min(ui.terminal_width(), 72)
    lines = ui.panel(
        [ui.bold("sales agents"), ui.dim("research chain · runs on your Claude Code login")],
        width=width,
    )
    out.write("\n" + "\n".join("  " + line for line in lines) + "\n")


# --------------------------------------------------------------------------
# review checkpoint
# --------------------------------------------------------------------------


def _preview(text: str, lines: int = 14) -> str:
    parts = text.splitlines()
    shown = "\n".join("    " + line for line in parts[:lines])
    if len(parts) > lines:
        shown += "\n" + ui.dim(f"    … {len(parts) - lines} more lines")
    return shown


def _editor_command():
    return shlex.split(os.environ.get("EDITOR", "vi"))


def review_checkpoint(step, out_path: Path, *, input_fn=input, out=None) -> str:
    """Show what the stage produced before it feeds the next one."""
    out = out or sys.stdout
    while True:
        out.write("\n" + ui.dim(f"  ── {out_path.name} " + "─" * 20) + "\n")
        out.write(_preview(out_path.read_text()) + "\n\n")
        out.write(
            "    "
            + ui.dim("[enter] continue   [e] edit   [r] retry   [a] run the rest   [q] quit")
            + "\n"
        )
        try:
            choice = input_fn("  " + ui.cyan(ui.PROMPT)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            return "quit"

        if choice in ("", "c", "continue"):
            return "continue"
        if choice in ("r", "retry"):
            return "retry"
        if choice in ("q", "quit"):
            return "quit"
        if choice in ("a", "auto"):
            return "auto"
        if choice in ("e", "edit"):
            subprocess.run(_editor_command() + [str(out_path)])
            continue
        out.write("    " + ui.yellow("type enter, e, r, a or q") + "\n")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def cmd_run(args) -> int:
    out = sys.stdout
    _banner(out)

    recent = settings.load_recent()
    supplied = {
        "seller": args.seller,
        "offering": args.offering,
        "company": args.company,
    }
    try:
        if not any(supplied.values()):
            chosen = pairings.choose(out=out)
            if chosen:
                supplied.update(chosen)
        values = collect_inputs(
            seller=supplied["seller"],
            offering=supplied["offering"],
            company=supplied["company"],
            industry=args.industry,
            defaults=recent,
            out=out,
        )
    except ui.InputAborted:
        out.write(ui.dim("  nothing started.\n"))
        return 130

    model = args.model or recent.get("model") or "sonnet"
    style = args.style or recent.get("style") or "a"
    out_dir = Path(args.out_dir)
    run_dir = out_dir / slugify(values["company"])
    step_ids = steps_for_style(style)

    out.write("\n" + "\n".join(_plan_lines(values, run_dir, step_ids, model, style)) + "\n")

    if (run_dir / "state.json").exists():
        out.write(
            "\n  "
            + ui.yellow("A run already exists there.")
            + ui.dim(f"  Resume it with: sales-agents continue {run_dir}\n")
        )
        return 1

    state = RunState(
        run_dir=run_dir,
        company=values["company"],
        industry=values["industry"],
        style=style,
        model=model,
        group=args.group,
        date=args.date or time.strftime("%Y-%m-%d"),
        seller=values["seller"],
        offering=values["offering"],
        completed={},
    )
    state.save()
    settings.save_recent(
        {
            "seller": values["seller"],
            "offering": values["offering"],
            "model": model,
            "style": style,
        }
    )

    return _execute(state, args)


def cmd_continue(args) -> int:
    run_dir = Path(args.run_dir)
    try:
        state = RunState.load(run_dir)
    except (OSError, ValueError):
        print(f"No readable state.json under {run_dir}.", file=sys.stderr)
        return 1

    _banner(sys.stdout)
    step_ids = steps_for_style(state.style)
    values = {
        "seller": state.seller,
        "offering": state.offering,
        "company": state.company,
        "industry": state.industry,
    }
    print(
        "\n"
        + "\n".join(_plan_lines(values, run_dir, step_ids, state.model, state.style))
    )
    print(
        ui.field_row(
            "Done so far", f"{len(state.completed)}/{len(step_ids)} stages", LABEL_WIDTH
        )
    )
    return _execute(state, args)


def cmd_list(args) -> int:
    out_dir = Path(args.out_dir)
    runs = sorted(
        child for child in out_dir.glob("*") if (child / "state.json").exists()
    ) if out_dir.exists() else []

    if not runs:
        print(f"\n  {ui.dim('No runs yet under ' + str(out_dir))}\n")
        return 0

    print()
    for child in runs:
        try:
            state = RunState.load(child)
        except (OSError, ValueError):
            continue
        step_ids = steps_for_style(state.style)
        done = sum(1 for step_id in step_ids if step_id in state.completed)
        remaining = [s for s in step_ids if s not in state.completed]
        status = (
            ui.dim("next: " + STEPS[remaining[0]].title)
            if remaining
            else ui.green("complete")
        )
        print(
            "  "
            + ui.progress_bar(done, len(step_ids), width=14)
            + f"  {done:>2}/{len(step_ids)}  "
            + ui.pad(ui.bold(state.company), 24)
            + status
        )
        print("  " + ui.dim(" " * 16 + str(child)))
    print()
    return 0


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------


def _execute(state: RunState, args) -> int:
    step_ids = steps_for_style(state.style)
    steps = [STEPS[step_id] for step_id in step_ids]
    live = not getattr(args, "plain", False) and sys.stdout.isatty()
    dash = Dashboard(steps, live=live)

    runner = functools.partial(
        run_claude,
        timeout=getattr(args, "timeout", None) or DEFAULT_TIMEOUT,
        max_budget_usd=getattr(args, "budget", None),
    )
    pipeline = Pipeline(state, runner, on_activity=dash.activity)

    mode = {"auto": bool(getattr(args, "auto", False))}
    position = {"index": 0}

    def on_step_start(step, index, total):
        position["index"] = index
        dash.step_started(index)

    def on_step_skip(step, index, total):
        dash.step_skipped(index)

    def checkpoint(step, out_path):
        dash.step_finished(
            position["index"], out_path, badge=scoreboard.badge(out_path.read_text())
        )
        if mode["auto"]:
            return "continue"
        action = review_checkpoint(step, out_path)
        if action == "auto":
            mode["auto"] = True
            return "continue"
        return action

    dash.start()
    exit_code = 0
    try:
        pipeline.run(
            step_ids,
            checkpoint=checkpoint,
            on_step_start=on_step_start,
            on_step_skip=on_step_skip,
        )
    except KeyboardInterrupt:
        dash.step_failed(position["index"], "interrupted")
        exit_code = 130
    except (ClaudeRunError, MissingDependencyError) as exc:
        dash.step_failed(position["index"], str(exc))
        exit_code = 1
    finally:
        dash.stop()

    dash.summary(state.run_dir)
    _print_scoreboard(state, step_ids)
    remaining = [s for s in step_ids if s not in state.completed]
    if remaining:
        print(
            "\n  "
            + ui.dim("Resume with: ")
            + ui.bold(f"sales-agents continue {state.run_dir}")
            + "\n"
        )
        return exit_code or 1
    print("\n  " + ui.green("All stages done.") + ui.dim(f"  Files in {state.run_dir}\n"))
    return exit_code


def _print_scoreboard(state: RunState, step_ids) -> None:
    """The counts the workshop actually marks: what each stage reported, and
    what the thresholds say about it."""
    outputs = {}
    for step_id in step_ids:
        rel_path = state.completed.get(step_id)
        if not rel_path:
            continue
        try:
            outputs[step_id] = (state.run_dir / rel_path).read_text()
        except OSError:
            continue

    lines = scoreboard.report(outputs)
    if lines:
        print("\n" + ui.bold("  Counts") + "\n")
        print("\n".join(lines))


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["run"])

    if getattr(args, "plain", False) or not sys.stdout.isatty():
        ui.set_color(False)

    if args.command == "run":
        return cmd_run(args)
    if args.command == "continue":
        return cmd_continue(args)
    if args.command == "list":
        return cmd_list(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
