import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sales_agents.pipeline import Pipeline
from sales_agents.state import RunState


class FakeRunner:
    """Returns queued canned responses in call order; records prompts seen."""

    def __init__(self, responses):
        self.queue = list(responses)
        self.calls = []

    def __call__(self, prompt, model=None):
        self.calls.append(prompt)
        return self.queue.pop(0)


def make_state(run_dir, **overrides):
    defaults = dict(
        run_dir=run_dir,
        company="Acme Steel",
        industry="Manufacturing",
        style="a",
        model="sonnet",
        group="",
        date="2026-09-11",
        completed={},
    )
    defaults.update(overrides)
    return RunState(**defaults)


class PipelineOrderingTests(unittest.TestCase):
    def test_runs_steps_in_order_and_writes_files(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir)
            runner = FakeRunner(["ICP OUTPUT", "INDUSTRY OUTPUT"])
            pipeline = Pipeline(state, runner)

            pipeline.run(["icp", "industry"])

            icp_path = run_dir / state.completed["icp"]
            industry_path = run_dir / state.completed["industry"]
            self.assertEqual(icp_path.read_text(), "ICP OUTPUT")
            self.assertEqual(industry_path.read_text(), "INDUSTRY OUTPUT")
            # industry prompt should have been rendered with the icp output folded in
            self.assertIn("ICP OUTPUT", runner.calls[1])
            self.assertIn("Manufacturing", runner.calls[1])

            self.assertTrue((run_dir / "state.json").exists())

    def test_resume_skips_already_completed_steps(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            existing = run_dir / "00-icp.md"
            existing.write_text("OLD ICP OUTPUT")
            state = make_state(run_dir, completed={"icp": "00-icp.md"})
            runner = FakeRunner(["INDUSTRY OUTPUT"])
            pipeline = Pipeline(state, runner)

            pipeline.run(["icp", "industry"])

            self.assertEqual(len(runner.calls), 1)
            self.assertIn("OLD ICP OUTPUT", runner.calls[0])


class PipelineCheckpointTests(unittest.TestCase):
    def test_quit_checkpoint_stops_remaining_steps(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir)
            runner = FakeRunner(["ICP OUTPUT", "INDUSTRY OUTPUT"])
            pipeline = Pipeline(state, runner)

            pipeline.run(["icp", "industry"], checkpoint=lambda step, path: "quit")

            self.assertIn("icp", state.completed)
            self.assertNotIn("industry", state.completed)
            self.assertEqual(len(runner.calls), 1)

    def test_retry_checkpoint_reruns_same_step(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir)
            runner = FakeRunner(["FIRST TRY", "SECOND TRY"])
            attempts = {"n": 0}

            def checkpoint(step, path):
                attempts["n"] += 1
                return "retry" if attempts["n"] == 1 else "continue"

            pipeline = Pipeline(state, runner)
            pipeline.run(["icp"], checkpoint=checkpoint)

            self.assertEqual(len(runner.calls), 2)
            final_path = run_dir / state.completed["icp"]
            self.assertEqual(final_path.read_text(), "SECOND TRY")


class GradeResearchPostProcessTests(unittest.TestCase):
    def test_do_not_use_rows_are_appended_to_pack(self):
        pack_output = (
            "# Personalization Pack\n"
            "## The company\n"
            "Name: Acme Steel\n"
            "## Do not use\n"
            "-\n"
            "-\n"
        )
        grade_output = (
            "| row | A | B | C | D |\n"
            "ROWS: 3 | FAILED A: 1 | FAILED B: 0 | FAILED C: 0 | FAILED D: 0\n"
            "DO NOT USE\n"
            "- The company grew 40% (no source)\n"
            "- Procurement team doubled (industry knowledge only)\n"
        )
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir)
            runner = FakeRunner([pack_output, grade_output])
            pipeline = Pipeline(state, runner)
            # stand in for steps 0-4, which this test doesn't exercise
            pipeline.values.update(
                icp="icp text",
                industry_output="industry text",
                account_output="account text",
                roles_output="roles text",
                people_output="people text",
            )

            pipeline.run(["pack", "grade_research"])

            pack_path = run_dir / state.completed["pack"]
            final_pack = pack_path.read_text()
            self.assertIn("The company grew 40% (no source)", final_pack)
            self.assertIn("Procurement team doubled (industry knowledge only)", final_pack)


class PipelineProgressCallbackTests(unittest.TestCase):
    def test_on_step_start_called_for_each_executed_step(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir)
            runner = FakeRunner(["ICP OUTPUT", "INDUSTRY OUTPUT"])
            pipeline = Pipeline(state, runner)
            seen = []

            pipeline.run(
                ["icp", "industry"],
                on_step_start=lambda step, index, total: seen.append(
                    (step.id, index, total)
                ),
            )

            self.assertEqual(seen, [("icp", 0, 2), ("industry", 1, 2)])

    def test_on_step_skip_called_for_resumed_steps(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "00-icp.md").write_text("OLD ICP OUTPUT")
            state = make_state(run_dir, completed={"icp": "00-icp.md"})
            runner = FakeRunner(["INDUSTRY OUTPUT"])
            pipeline = Pipeline(state, runner)
            started = []
            skipped = []

            pipeline.run(
                ["icp", "industry"],
                on_step_start=lambda step, index, total: started.append(
                    (step.id, index, total)
                ),
                on_step_skip=lambda step, index, total: skipped.append(
                    (step.id, index, total)
                ),
            )

            self.assertEqual(skipped, [("icp", 0, 2)])
            self.assertEqual(started, [("industry", 1, 2)])

    def test_retry_calls_on_step_start_again(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir)
            runner = FakeRunner(["FIRST TRY", "SECOND TRY"])
            attempts = {"n": 0}
            starts = []

            def checkpoint(step, path):
                attempts["n"] += 1
                return "retry" if attempts["n"] == 1 else "continue"

            pipeline = Pipeline(state, runner)
            pipeline.run(
                ["icp"],
                checkpoint=checkpoint,
                on_step_start=lambda step, index, total: starts.append(index),
            )

            self.assertEqual(starts, [0, 0])


if __name__ == "__main__":
    unittest.main()
