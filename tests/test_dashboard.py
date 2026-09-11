import io
import unittest
from pathlib import Path

from sales_agents import ui
from sales_agents.dashboard import ACTIVITY_FEED_MAX, Dashboard
from sales_agents.runner import Activity
from sales_agents.steps import STEPS


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_dashboard(step_ids=("icp", "industry", "account"), height=60, out=None):
    clock = FakeClock()
    dash = Dashboard(
        [STEPS[s] for s in step_ids],
        clock=clock,
        out=out or io.StringIO(),
        live=False,
        width_fn=lambda: 100,
        height_fn=lambda: height,
    )
    return dash, clock


def rendered(dash):
    return "\n".join(ui.strip_ansi(line) for line in dash.render())


class DashboardRenderTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def test_lists_every_step_title(self):
        dash, _ = make_dashboard()
        text = rendered(dash)
        for step_id in ("icp", "industry", "account"):
            self.assertIn(STEPS[step_id].title, text)

    def test_progress_counts_completed_steps(self):
        dash, clock = make_dashboard()
        dash.step_started(0)
        clock.advance(5)
        dash.step_finished(0, Path("00-icp.md"))
        self.assertIn("1/3", rendered(dash))

    def test_running_step_shows_elapsed_time(self):
        dash, clock = make_dashboard()
        dash.step_started(1)
        clock.advance(12)
        self.assertIn("12", rendered(dash))

    def test_finished_step_shows_its_duration(self):
        dash, clock = make_dashboard()
        dash.step_started(0)
        clock.advance(42)
        dash.step_finished(0, Path("00-icp.md"))
        self.assertIn("42", rendered(dash))

    def test_step_carried_over_from_an_earlier_run_is_marked(self):
        dash, _ = make_dashboard()
        dash.step_skipped(0)
        line = [l for l in dash.render() if STEPS["icp"].title in ui.strip_ansi(l)][0]
        self.assertIn("done earlier", ui.strip_ansi(line).lower())

    def test_failed_step_is_marked(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        dash.step_failed(0, "claude exited 1")
        line = [l for l in dash.render() if STEPS["icp"].title in ui.strip_ansi(l)][0]
        self.assertIn("failed", ui.strip_ansi(line).lower())

    def test_spinner_animates_between_frames(self):
        dash, clock = make_dashboard()
        dash.step_started(0)
        first = rendered(dash)
        clock.advance(1.0)
        self.assertNotEqual(first, rendered(dash))

    def test_total_cost_is_shown_once_known(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        dash.activity(Activity(kind="done", label="done", cost_usd=0.25, duration_s=3))
        dash.step_finished(0, Path("00-icp.md"))
        self.assertIn("$0.25", rendered(dash))

    def test_costs_accumulate_across_steps(self):
        dash, _ = make_dashboard()
        for index, name in ((0, "00-icp.md"), (1, "01-industry.md")):
            dash.step_started(index)
            dash.activity(Activity(kind="done", label="done", cost_usd=0.25, duration_s=1))
            dash.step_finished(index, Path(name))
        self.assertIn("$0.50", rendered(dash))


class ActivityFeedTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def test_tool_activity_is_shown_with_its_detail(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        dash.activity(Activity(kind="tool", label="WebSearch", detail="Tata Steel CPO"))
        text = rendered(dash)
        self.assertIn("WebSearch", text)
        self.assertIn("Tata Steel CPO", text)

    def test_feed_keeps_only_the_most_recent_entries(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        for i in range(ACTIVITY_FEED_MAX + 4):
            dash.activity(Activity(kind="tool", label="WebSearch", detail=f"query-{i}"))
        text = rendered(dash)
        self.assertIn(f"query-{ACTIVITY_FEED_MAX + 3}", text)
        self.assertNotIn("query-0 ", text + " ")

    def test_repeated_thinking_updates_collapse_into_one_line(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        for tokens in (10, 200, 3000):
            dash.activity(Activity(kind="thinking", label="thinking", tokens=tokens))
        text = rendered(dash)
        self.assertEqual(text.count("thinking"), 1)
        self.assertIn("3.0k", text)

    def test_feed_resets_when_the_next_step_starts(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        dash.activity(Activity(kind="tool", label="WebSearch", detail="old-query"))
        dash.step_finished(0, Path("00-icp.md"))
        dash.step_started(1)
        self.assertNotIn("old-query", rendered(dash))

    def test_tool_counts_are_summarised_for_the_run(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        dash.activity(Activity(kind="tool", label="WebSearch", detail="a"))
        dash.activity(Activity(kind="tool", label="WebSearch", detail="b"))
        dash.activity(Activity(kind="tool", label="WebFetch", detail="c"))
        self.assertEqual(dash.tool_counts["WebSearch"], 2)
        self.assertEqual(dash.tool_counts["WebFetch"], 1)


class DashboardFitTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def test_frame_fits_inside_a_short_terminal(self):
        dash, _ = make_dashboard(
            step_ids=tuple(STEPS.keys()), height=14
        )
        dash.step_started(6)
        self.assertLessEqual(len(dash.render()), 14)

    def test_running_step_stays_visible_in_a_short_terminal(self):
        step_ids = tuple(STEPS.keys())
        dash, _ = make_dashboard(step_ids=step_ids, height=14)
        dash.step_started(9)
        self.assertIn(STEPS[step_ids[9]].title, rendered(dash))

    def test_hidden_steps_are_accounted_for(self):
        dash, _ = make_dashboard(step_ids=tuple(STEPS.keys()), height=14)
        dash.step_started(9)
        self.assertIn("earlier", rendered(dash).lower())

    def test_lines_never_exceed_terminal_width(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        dash.activity(Activity(kind="tool", label="WebSearch", detail="x" * 400))
        for line in dash.render():
            self.assertLessEqual(ui.visible_width(line), 100)


class DashboardLoggingTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def test_finished_step_writes_a_permanent_log_line(self):
        out = io.StringIO()
        dash, clock = make_dashboard(out=out)
        dash.step_started(0)
        clock.advance(9)
        dash.step_finished(0, Path("/runs/acme/00-icp.md"))
        printed = out.getvalue()
        self.assertIn(STEPS["icp"].title, printed)
        self.assertIn("00-icp.md", printed)

    def test_failed_step_writes_the_reason(self):
        out = io.StringIO()
        dash, _ = make_dashboard(out=out)
        dash.step_started(0)
        dash.step_failed(0, "claude exited 1")
        self.assertIn("claude exited 1", out.getvalue())

    def test_summary_reports_totals(self):
        out = io.StringIO()
        dash, clock = make_dashboard(out=out)
        for index, name in ((0, "00-icp.md"), (1, "01-industry.md")):
            dash.step_started(index)
            clock.advance(10)
            dash.activity(Activity(kind="done", label="done", cost_usd=0.2, duration_s=10))
            dash.step_finished(index, Path(name))
        out.truncate(0)
        out.seek(0)
        dash.summary(Path("/runs/acme"))
        printed = ui.strip_ansi(out.getvalue())
        self.assertIn("2/3", printed)
        self.assertIn("$0.40", printed)
        self.assertIn("/runs/acme", printed)


class StepBadgeTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def test_badge_from_the_stage_counters_is_shown_on_the_row(self):
        dash, _ = make_dashboard()
        dash.step_started(0)
        dash.step_finished(0, Path("00-icp.md"), badge="3 verified · 1 asserted")
        self.assertIn("3 verified · 1 asserted", rendered(dash))

    def test_badge_is_kept_in_the_permanent_log_line(self):
        out = io.StringIO()
        dash, _ = make_dashboard(out=out)
        dash.step_started(0)
        dash.step_finished(0, Path("00-icp.md"), badge="2/12 rows unsourced")
        self.assertIn("2/12 rows unsourced", out.getvalue())


if __name__ == "__main__":
    unittest.main()
