import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sales_agents import runs, ui
from sales_agents.browser import RunPicker, StageBrowser
from sales_agents.state import RunState

INDUSTRY_OUTPUT = (
    "## Industry: Steel manufacturing\n\n"
    "| What changed | Source + date | Status |\n"
    "| capex cycle restarted | Reuters, 2026-03-01 | VERIFIED |\n"
    "| vendor churn | trade press, 2024-01-01 | ASSERTED |\n"
    # enough rows that the content pane has to scroll
    + "".join(f"| change {i} | Reuters, 2026-03-{i:02d} | VERIFIED |\n" for i in range(1, 21))
    + "\nVERIFIED: 3 | ASSERTED: 1 | TOTAL: 4\n"
)


def make_run(tmp, completed=("icp", "industry"), company="Tata Steel"):
    run_dir = Path(tmp) / "tata-steel"
    run_dir.mkdir(parents=True, exist_ok=True)
    files = {"icp": "00-icp.md", "industry": "01-industry.md"}
    done = {}
    for step_id in completed:
        name = files[step_id]
        (run_dir / name).write_text(
            INDUSTRY_OUTPUT if step_id == "industry" else "## Who fits\n| a | b |\n"
        )
        done[step_id] = name
    state = RunState(
        run_dir=run_dir,
        company=company,
        industry="",
        model="sonnet",
        group="",
        date="2026-09-11",
        seller="MoveInSync",
        offering="commute software",
        completed=done,
    )
    state.save()
    return run_dir


def make_browser(tmp, height=24, width=100, **kwargs):
    run_dir = make_run(tmp, **kwargs)
    summary = runs.load(run_dir)
    return StageBrowser(summary, width_fn=lambda: width, height_fn=lambda: height)


def rendered(view):
    return "\n".join(ui.strip_ansi(line) for line in view.render())


class DiscoveryTests(unittest.TestCase):
    def test_finds_runs_that_have_state(self):
        with TemporaryDirectory() as tmp:
            make_run(tmp)
            (Path(tmp) / "not-a-run").mkdir()
            found = runs.discover(Path(tmp))
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].state.company, "Tata Steel")

    def test_reports_progress(self):
        with TemporaryDirectory() as tmp:
            summary = runs.load(make_run(tmp))
            self.assertEqual(summary.done, 2)
            self.assertEqual(summary.total, len(summary.step_ids))
            self.assertFalse(summary.complete)

    def test_missing_directory_is_empty(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(runs.discover(Path(tmp) / "nope"), [])

    def test_stages_pair_each_step_with_its_output(self):
        with TemporaryDirectory() as tmp:
            summary = runs.load(make_run(tmp))
            stages = summary.stages()
            self.assertEqual(stages[0].step.id, "icp")
            self.assertTrue(stages[0].exists)
            self.assertFalse(stages[5].exists)
            self.assertIn("Industry", stages[1].text)

    def test_counters_are_attached_to_the_stage(self):
        with TemporaryDirectory() as tmp:
            stages = runs.load(make_run(tmp)).stages()
            self.assertEqual(stages[1].counts["VERIFIED"], 3)


class BrowserRenderTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def test_frame_is_exactly_the_terminal_height(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp, height=24)
            self.assertEqual(len(view.render()), 24)

    def test_no_line_is_wider_than_the_terminal(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp, width=70)
            for line in view.render():
                self.assertLessEqual(ui.visible_width(line), 70)

    def test_header_names_the_account(self):
        with TemporaryDirectory() as tmp:
            self.assertIn("Tata Steel", rendered(make_browser(tmp)))

    def test_every_stage_is_listed(self):
        with TemporaryDirectory() as tmp:
            text = rendered(make_browser(tmp))
            self.assertIn("The ICP", text)
            self.assertIn("Grade the messages", text)

    def test_selected_stage_content_is_shown(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp)
            view.handle("right")
            self.assertIn("Steel manufacturing", rendered(view))

    def test_stage_that_never_ran_says_so(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp)
            for _ in range(5):
                view.handle("right")
            self.assertIn("not run yet", rendered(view).lower())

    def test_footer_lists_the_keys(self):
        with TemporaryDirectory() as tmp:
            text = rendered(make_browser(tmp)).lower()
            self.assertIn("quit", text)
            self.assertIn("scroll", text)

    def test_counters_are_visible_for_the_selected_stage(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp)
            view.handle("right")
            self.assertIn("VERIFIED: 3", rendered(view))


class BrowserNavigationTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def test_left_and_right_move_between_stages(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp)
            view.handle("right")
            self.assertEqual(view.selected, 1)
            view.handle("left")
            self.assertEqual(view.selected, 0)

    def test_selection_stops_at_the_ends(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp)
            view.handle("left")
            self.assertEqual(view.selected, 0)
            for _ in range(50):
                view.handle("right")
            self.assertEqual(view.selected, len(view.stages) - 1)

    def test_arrows_and_jk_scroll_the_text(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp, height=12)
            view.handle("right")
            view.handle("down")
            self.assertEqual(view.scroll, 1)
            view.handle("j")
            self.assertEqual(view.scroll, 2)
            view.handle("up")
            view.handle("k")
            self.assertEqual(view.scroll, 0)
            self.assertEqual(view.selected, 1)

    def test_content_scrolls_with_the_right_hand_keys(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp, height=12)
            view.handle("right")
            view.handle("pgdn")
            self.assertGreater(view.scroll, 0)
            view.handle("pgup")
            self.assertEqual(view.scroll, 0)

    def test_scroll_never_runs_past_the_end(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp, height=12)
            for _ in range(200):
                view.handle("pgdn")
            self.assertLessEqual(view.scroll, max(0, len(view.lines()) - 1))

    def test_changing_stage_resets_the_scroll(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp, height=12)
            view.handle("right")
            view.handle("pgdn")
            view.handle("left")
            self.assertEqual(view.scroll, 0)

    def test_end_and_home_jump(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp, height=12)
            view.handle("right")
            view.handle("end")
            self.assertGreater(view.scroll, 0)
            view.handle("home")
            self.assertEqual(view.scroll, 0)

    def test_q_quits_and_r_goes_back_to_the_run_list(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp)
            self.assertEqual(view.handle("q"), "quit")
            self.assertEqual(view.handle("r"), "back")

    def test_ctrl_c_quits(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(make_browser(tmp).handle("ctrl-c"), "quit")

    def test_unknown_key_does_nothing(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp)
            self.assertIsNone(view.handle("z"))
            self.assertEqual(view.selected, 0)
            self.assertEqual(view.scroll, 0)


class RunPickerTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def _picker(self, tmp, height=20, width=90):
        make_run(tmp)
        found = runs.discover(Path(tmp))
        return RunPicker(found, width_fn=lambda: width, height_fn=lambda: height)

    def test_lists_each_run_with_progress(self):
        with TemporaryDirectory() as tmp:
            text = rendered(self._picker(tmp))
            self.assertIn("Tata Steel", text)
            self.assertIn("2/", text)

    def test_frame_fits_the_terminal(self):
        with TemporaryDirectory() as tmp:
            picker = self._picker(tmp, height=20, width=60)
            self.assertEqual(len(picker.render()), 20)
            for line in picker.render():
                self.assertLessEqual(ui.visible_width(line), 60)

    def test_enter_opens_the_highlighted_run(self):
        with TemporaryDirectory() as tmp:
            picker = self._picker(tmp)
            self.assertEqual(picker.handle("enter"), "open")
            self.assertEqual(picker.chosen.state.company, "Tata Steel")

    def test_q_quits(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(self._picker(tmp).handle("q"), "quit")


class StagePaneTests(unittest.TestCase):
    """The pane shows the document, not the markdown source."""

    def setUp(self):
        ui.set_color(False)

    def test_markdown_markers_are_not_shown(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp)
            view.handle("right")
            pane = [line.split("│", 1)[-1] for line in rendered(view).splitlines()]
            text = "\n".join(pane)
            self.assertIn("Industry: Steel manufacturing", text)
            self.assertNotIn("|", text)
            self.assertNotIn("##", text)

    def test_table_columns_line_up_in_the_pane(self):
        with TemporaryDirectory() as tmp:
            view = make_browser(tmp, width=120)
            view.handle("right")
            rows = [line for line in rendered(view).splitlines() if "Reuters" in line]
            self.assertGreater(len(rows), 1)
            self.assertEqual(
                {row.index("Reuters") for row in rows}, {rows[0].index("Reuters")}
            )


if __name__ == "__main__":
    unittest.main()
