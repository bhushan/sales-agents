import argparse
import itertools
import subprocess
import sys
import threading
import time
from pathlib import Path

from .pipeline import Pipeline
from .runner import ClaudeRunError, run_claude
from .state import RunState, slugify
from .steps import STEP_ORDER, STEPS

DEFAULT_RUNS_DIR = Path("research-chain") / "outputs"


class Spinner:
    """Elapsed-time indicator for a slow `claude` call. Falls back to a
    single line (no carriage-return animation) when stdout isn't a tty,
    e.g. when output is piped or redirected to a log file."""

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str):
        self.label = label
        self._stop = threading.Event()
        self._thread = None
        self._start = None
        self._tty = sys.stdout.isatty()

    def start(self) -> None:
        self._start = time.monotonic()
        if not self._tty:
            print(f"  {self.label} ...")
            return
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                return
            elapsed = time.monotonic() - self._start
            sys.stdout.write(f"\r  {frame} {self.label} ({elapsed:0.0f}s)   ")
            sys.stdout.flush()
            time.sleep(0.1)

    def stop(self, done_label: str) -> None:
        elapsed = time.monotonic() - self._start if self._start else 0.0
        if self._tty and self._thread:
            self._stop.set()
            self._thread.join()
            sys.stdout.write("\r" + " " * (len(self.label) + 24) + "\r")
        print(f"  ✓ {done_label} ({elapsed:0.1f}s)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sales-agents",
        description="Chain sales-research prompts (ICP -> industry -> "
        "account -> roles -> people -> pack -> grade -> emails -> LinkedIn "
        "-> grade messages) through the Claude Code CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Start a new research chain for a company.")
    run_p.add_argument(
        "--seller",
        required=True,
        help="Who you sell for, e.g. 'MoveInSync' (used in outreach copy).",
    )
    run_p.add_argument("--company", required=True, help="Target account name.")
    run_p.add_argument("--industry", required=True, help="Target industry name.")
    run_p.add_argument("--group", default="", help="Workshop group label (optional).")
    run_p.add_argument(
        "--style",
        choices=["a", "b", "both"],
        default="a",
        help="Email style to generate (default: a).",
    )
    run_p.add_argument(
        "--model", default="sonnet", help="Model alias to pass to `claude --model`."
    )
    run_p.add_argument(
        "--out-dir",
        default=str(DEFAULT_RUNS_DIR),
        help=f"Directory to hold per-company run folders (default: {DEFAULT_RUNS_DIR}).",
    )
    run_p.add_argument(
        "--auto",
        action="store_true",
        help="Run the whole chain without pausing for review between steps.",
    )
    run_p.add_argument(
        "--date", default=None, help="Date to stamp on the pack (default: today)."
    )

    cont_p = sub.add_parser("continue", help="Resume an existing run.")
    cont_p.add_argument("run_dir", help="Path to the run's output directory.")
    cont_p.add_argument("--auto", action="store_true")

    list_p = sub.add_parser("list", help="List runs under a directory.")
    list_p.add_argument("--out-dir", default=str(DEFAULT_RUNS_DIR))

    return parser


def _steps_for_style(style: str):
    ids = list(STEP_ORDER)
    if style == "a":
        ids = [s for s in ids if s != "emails_b"]
    elif style == "b":
        ids = [s for s in ids if s != "emails_a"]
    return ids


def _today() -> str:
    import time

    return time.strftime("%Y-%m-%d")


def _preview(text: str, lines: int = 16) -> str:
    parts = text.splitlines()
    shown = "\n".join(parts[:lines])
    if len(parts) > lines:
        shown += f"\n... ({len(parts) - lines} more lines)"
    return shown


def _interactive_checkpoint(step, out_path: Path) -> str:
    print()
    print(_preview(out_path.read_text()))
    while True:
        choice = input(
            "\n[c]ontinue  [e]dit  [r]etry  [q]uit  > "
        ).strip().lower()
        if choice in ("", "c", "continue"):
            return "continue"
        if choice in ("r", "retry"):
            return "retry"
        if choice in ("q", "quit"):
            return "quit"
        if choice in ("e", "edit"):
            editor = _editor_command()
            subprocess.run(editor + [str(out_path)])
            print(f"\n--- {step.title} (edited) ---")
            print(_preview(out_path.read_text()))
            continue
        print("Type c, e, r, or q.")


def _auto_checkpoint(step, out_path: Path) -> str:
    return "continue"


def _editor_command():
    import os
    import shlex

    editor = os.environ.get("EDITOR", "vi")
    return shlex.split(editor)


def _make_runner(model_default: str):
    def runner(prompt: str, model: str = model_default) -> str:
        return run_claude(prompt, model=model)

    return runner


def cmd_run(args) -> int:
    date = args.date or _today()
    out_dir = Path(args.out_dir)
    run_dir = out_dir / slugify(args.company)

    if (run_dir / "state.json").exists():
        print(
            f"A run already exists at {run_dir}. Use "
            f"`sales-agents continue {run_dir}` to resume it."
        )
        return 1

    state = RunState(
        run_dir=run_dir,
        company=args.company,
        industry=args.industry,
        style=args.style,
        model=args.model,
        group=args.group,
        date=date,
        seller=args.seller,
        completed={},
    )
    state.save()

    return _execute(state, auto=args.auto)


def cmd_continue(args) -> int:
    run_dir = Path(args.run_dir)
    try:
        state = RunState.load(run_dir)
    except FileNotFoundError:
        print(f"No state.json found under {run_dir}.")
        return 1
    return _execute(state, auto=args.auto)


def cmd_list(args) -> int:
    out_dir = Path(args.out_dir)
    if not out_dir.exists():
        print(f"No runs yet under {out_dir}.")
        return 0
    found = False
    for child in sorted(out_dir.iterdir()):
        state_path = child / "state.json"
        if not state_path.exists():
            continue
        found = True
        state = RunState.load(child)
        step_ids = _steps_for_style(state.style)
        done = len(state.completed)
        total = len(step_ids)
        line = f"{child}  [{state.company}]  {done}/{total} steps"
        remaining = [s for s in step_ids if s not in state.completed]
        if remaining:
            line += f" — next: {STEPS[remaining[0]].title}"
        else:
            line += " — complete"
        print(line)
    if not found:
        print(f"No runs yet under {out_dir}.")
    return 0


def _execute(state: RunState, auto: bool) -> int:
    step_ids = _steps_for_style(state.style)
    runner = _make_runner(state.model)
    pipeline = Pipeline(state, runner)
    checkpoint = _auto_checkpoint if auto else _interactive_checkpoint

    spinner_box = {}

    def on_step_start(step, index, total):
        print(f"\nStep {index + 1}/{total}: {step.title}")
        spinner = Spinner("calling claude")
        spinner.start()
        spinner_box["spinner"] = spinner

    def on_step_skip(step, index, total):
        print(f"Step {index + 1}/{total}: {step.title} — already done, skipping")

    def checkpoint_wrapper(step, out_path):
        spinner = spinner_box.pop("spinner", None)
        if spinner:
            spinner.stop(f"wrote {out_path.name}")
        return checkpoint(step, out_path)

    already_done = len(state.completed)
    print(f"Run directory: {state.run_dir}")
    print(f"Plan: {len(step_ids)} steps ({already_done} already done)\n")

    try:
        pipeline.run(
            step_ids,
            checkpoint=checkpoint_wrapper,
            on_step_start=on_step_start,
            on_step_skip=on_step_skip,
        )
    except ClaudeRunError as exc:
        spinner = spinner_box.pop("spinner", None)
        if spinner:
            spinner.stop("failed")
        print(f"\nclaude call failed: {exc}", file=sys.stderr)
        print(f"Fix the issue and resume with: sales-agents continue {state.run_dir}")
        return 1

    remaining = [s for s in step_ids if s not in state.completed]
    if remaining:
        print(f"\nStopped early ({len(state.completed)}/{len(step_ids)} steps done). "
              f"Resume with: sales-agents continue {state.run_dir}")
    else:
        print(f"\nDone. All {len(step_ids)} steps complete. Outputs in {state.run_dir}")
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
