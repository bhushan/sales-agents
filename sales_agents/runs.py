"""Finding runs on disk and pairing each stage with the file it produced."""

from dataclasses import dataclass
from pathlib import Path

from . import scoreboard
from .state import RunState
from .steps import STEP_ORDER, STEPS


@dataclass
class Stage:
    step: object
    path: Path
    exists: bool
    text: str
    counts: dict

    @property
    def badge(self):
        return scoreboard.badge(self.text)

    @property
    def verdict(self):
        if "SENTENCES" in self.counts:
            return scoreboard.message_verdict(self.counts)
        if "ROWS" in self.counts:
            return scoreboard.research_verdict(self.counts)
        return None


@dataclass
class RunSummary:
    run_dir: Path
    state: RunState
    step_ids: list

    @property
    def done(self):
        return sum(1 for step_id in self.step_ids if step_id in self.state.completed)

    @property
    def total(self):
        return len(self.step_ids)

    @property
    def complete(self):
        return self.done == self.total

    @property
    def next_title(self):
        for step_id in self.step_ids:
            if step_id not in self.state.completed:
                return STEPS[step_id].title
        return ""

    def stages(self):
        found = []
        for step_id in self.step_ids:
            step = STEPS[step_id]
            name = self.state.completed.get(step_id, step.output_name)
            path = self.run_dir / name
            try:
                text = path.read_text()
                exists = True
            except OSError:
                text, exists = "", False
            found.append(
                Stage(
                    step=step,
                    path=path,
                    exists=exists,
                    text=text,
                    counts=scoreboard.parse_counts(text) if exists else {},
                )
            )
        return found


def load(run_dir) -> RunSummary:
    run_dir = Path(run_dir)
    state = RunState.load(run_dir)
    return RunSummary(run_dir=run_dir, state=state, step_ids=list(STEP_ORDER))


def discover(out_dir):
    """Every run under `out_dir`, most recently touched first."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    found = []
    for child in out_dir.iterdir():
        state_path = child / "state.json"
        if not state_path.exists():
            continue
        try:
            found.append((state_path.stat().st_mtime, load(child)))
        except (OSError, ValueError, TypeError):
            continue
    found.sort(key=lambda pair: pair[0], reverse=True)
    return [summary for _, summary in found]
