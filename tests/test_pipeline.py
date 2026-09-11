import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sales_agents.pipeline import Pipeline, compose_our_product
from sales_agents.runner import Activity
from sales_agents.state import RunState


class FakeRunner:
    """Returns queued canned responses in call order; records prompts seen."""

    def __init__(self, responses):
        self.queue = list(responses)
        self.calls = []
        self.kwargs = []

    def __call__(self, prompt, **kwargs):
        self.calls.append(prompt)
        self.kwargs.append(kwargs)
        return self.queue.pop(0)


def make_state(run_dir, **overrides):
    defaults = dict(
        run_dir=run_dir,
        company="Acme Steel",
        industry="Manufacturing",
        model="sonnet",
        group="",
        date="2026-09-11",
        seller="MoveInSync",
        offering="employee commute automation",
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


class PipelineInputTests(unittest.TestCase):
    def test_what_they_sell_is_woven_into_the_first_prompt(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir, offering="employee commute automation")
            runner = FakeRunner(["ICP OUTPUT"])
            Pipeline(state, runner).run(["icp"])
            self.assertIn("employee commute automation", runner.calls[0])
            self.assertIn("MoveInSync", runner.calls[0])

    def test_blank_industry_asks_the_model_to_identify_it(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir, industry="")
            runner = FakeRunner(["ICP OUTPUT", "INDUSTRY OUTPUT"])
            Pipeline(state, runner).run(["icp", "industry"])
            prompt = runner.calls[1]
            self.assertIn("Acme Steel", prompt)
            self.assertIn("identify", prompt.lower())

    def test_given_industry_is_used_verbatim(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir, industry="Steel manufacturing")
            runner = FakeRunner(["ICP OUTPUT", "INDUSTRY OUTPUT"])
            Pipeline(state, runner).run(["icp", "industry"])
            self.assertIn("Steel manufacturing", runner.calls[1])

    def test_falls_back_to_the_context_file_when_no_offering_is_set(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            context_dir = run_dir / "context"
            context_dir.mkdir()
            (context_dir / "our_product.md").write_text("A FILE-BASED PITCH\n")
            state = make_state(run_dir, offering="", seller="")
            runner = FakeRunner(["ICP OUTPUT"])
            Pipeline(state, runner, context_dir=context_dir).run(["icp"])
            self.assertIn("A FILE-BASED PITCH", runner.calls[0])


class ComposeOurProductTests(unittest.TestCase):
    def test_names_the_seller_and_the_offering(self):
        text = compose_our_product("MoveInSync", "employee commute automation")
        self.assertIn("MoveInSync", text)
        self.assertIn("employee commute automation", text)

    def test_offering_alone_is_enough(self):
        self.assertIn("commute", compose_our_product("", "commute automation"))

    def test_returns_empty_without_an_offering(self):
        self.assertEqual(compose_our_product("MoveInSync", ""), "")


class PipelineActivityTests(unittest.TestCase):
    def test_activity_callback_is_handed_to_the_runner(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir)
            runner = FakeRunner(["ICP OUTPUT"])
            seen = []
            pipeline = Pipeline(state, runner, on_activity=seen.append)

            pipeline.run(["icp"])

            callback = runner.kwargs[0]["on_activity"]
            callback(Activity(kind="tool", label="WebSearch"))
            self.assertEqual(seen[0].label, "WebSearch")

    def test_model_is_handed_to_the_runner(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = make_state(run_dir, model="opus")
            runner = FakeRunner(["ICP OUTPUT"])
            Pipeline(state, runner).run(["icp"])
            self.assertEqual(runner.kwargs[0]["model"], "opus")


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
