import re
from pathlib import Path

from .state import RunState
from .steps import CONTEXT_DIR, STEPS, load_template, render


class MissingDependencyError(RuntimeError):
    pass


_DO_NOT_USE_PLACEHOLDER_RE = re.compile(r"## Do not use\n(?:-\s*\n?)*")


class Pipeline:
    """Runs a chain of Steps through `runner`, persisting output files and
    resumable state under state.run_dir."""

    def __init__(self, state: RunState, runner, context_dir: Path = CONTEXT_DIR):
        self.state = state
        self.runner = runner
        self.context_dir = Path(context_dir)
        self.values = {
            "company": state.company,
            "industry": state.industry,
            "group": state.group,
            "date": state.date,
            "seller": state.seller,
        }
        self.values["our_product"] = (
            (self.context_dir / "our_product.md").read_text().strip()
        )
        self._load_completed_outputs()

    def _load_completed_outputs(self) -> None:
        for step_id, rel_path in self.state.completed.items():
            step = STEPS[step_id]
            path = self.state.run_dir / rel_path
            if path.exists():
                self.values[step.produces] = path.read_text()

    def run(self, step_ids, checkpoint=None, on_step_start=None, on_step_skip=None) -> None:
        """checkpoint(step, out_path) -> 'continue' | 'retry' | 'quit'.
        on_step_start(step, index, total) fires right before a step that
        will actually run. on_step_skip(step, index, total) fires instead,
        for a step already satisfied by prior state (resume)."""
        total = len(step_ids)
        index = 0
        while index < len(step_ids):
            step_id = step_ids[index]
            step = STEPS[step_id]

            if step_id in self.state.completed:
                if on_step_skip:
                    on_step_skip(step, index, total)
                index += 1
                continue

            if on_step_start:
                on_step_start(step, index, total)

            output = self._run_step(step)
            out_path = self.state.run_dir / step.output_name
            self.state.run_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output)
            self.values[step.produces] = output

            self._post_process(step)

            self.state.completed[step_id] = step.output_name
            self.state.save()

            action = checkpoint(step, out_path) if checkpoint else "continue"

            if action == "quit":
                return
            if action == "retry":
                del self.state.completed[step_id]
                continue
            index += 1

    def _run_step(self, step) -> str:
        if step.id == "grade_messages":
            self.values["messages_output"] = self._assemble_messages()

        missing = [key for key in step.requires if key not in self.values]
        if missing:
            raise MissingDependencyError(
                f"step '{step.id}' is missing required values: {missing}"
            )

        template = load_template(step)
        prompt = render(template, self.values)
        return self.runner(prompt, model=self.state.model)

    def _assemble_messages(self) -> str:
        parts = []
        for key, label in (
            ("emails_a_output", "EMAILS - STYLE A"),
            ("emails_b_output", "EMAILS - STYLE B"),
            ("linkedin_output", "LINKEDIN OUTREACH"),
        ):
            if key in self.values:
                parts.append(f"--- {label} ---\n{self.values[key]}")
        return "\n\n".join(parts)

    def _post_process(self, step) -> None:
        if step.id != "grade_research":
            return

        flagged = self._extract_do_not_use(self.values["grade_output"])
        if not flagged:
            return

        pack_step = STEPS["pack"]
        pack_output = self.values.get(pack_step.produces)
        if pack_output is None:
            return

        updated = self._append_do_not_use(pack_output, flagged)
        self.values[pack_step.produces] = updated

        pack_rel_path = self.state.completed.get(pack_step.id, pack_step.output_name)
        (self.state.run_dir / pack_rel_path).write_text(updated)

    @staticmethod
    def _extract_do_not_use(grade_output: str) -> list:
        flagged = []
        capture = False
        for line in grade_output.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("DO NOT USE"):
                capture = True
                continue
            if not capture:
                continue
            if not stripped:
                continue
            if stripped.startswith("-"):
                flagged.append(stripped)
            else:
                break
        return flagged

    @staticmethod
    def _append_do_not_use(pack_output: str, flagged: list) -> str:
        body = "\n".join(flagged) + "\n"
        replacement = "## Do not use\n" + body
        if _DO_NOT_USE_PLACEHOLDER_RE.search(pack_output):
            return _DO_NOT_USE_PLACEHOLDER_RE.sub(replacement, pack_output, count=1)
        return pack_output.rstrip() + "\n\n## Do not use\n" + body
