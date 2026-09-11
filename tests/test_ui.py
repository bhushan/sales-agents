import io
import unittest

from sales_agents import ui


class TextMeasurementTests(unittest.TestCase):
    def test_strip_ansi_removes_escape_codes(self):
        self.assertEqual(ui.strip_ansi("\x1b[36mhello\x1b[0m"), "hello")

    def test_visible_width_ignores_escape_codes(self):
        self.assertEqual(ui.visible_width("\x1b[1mabc\x1b[0m"), 3)

    def test_visible_width_counts_wide_characters_as_two(self):
        self.assertEqual(ui.visible_width("東京"), 4)

    def test_truncate_leaves_short_text_alone(self):
        self.assertEqual(ui.truncate("abc", 10), "abc")

    def test_truncate_clips_to_width_with_ellipsis(self):
        out = ui.truncate("abcdefghij", 5)
        self.assertLessEqual(ui.visible_width(out), 5)
        self.assertTrue(ui.strip_ansi(out).endswith("…"))

    def test_truncate_keeps_escape_codes_and_resets(self):
        colored = "\x1b[36m" + "abcdefghij" + "\x1b[0m"
        out = ui.truncate(colored, 5)
        self.assertLessEqual(ui.visible_width(out), 5)
        self.assertIn("\x1b[36m", out)
        self.assertTrue(out.endswith(ui.RESET))

    def test_pad_fills_to_width_using_visible_length(self):
        out = ui.pad("\x1b[1mab\x1b[0m", 5)
        self.assertEqual(ui.visible_width(out), 5)


class FormattingTests(unittest.TestCase):
    def test_format_duration_seconds(self):
        self.assertEqual(ui.format_duration(5), "5.0s")

    def test_format_duration_minutes(self):
        self.assertEqual(ui.format_duration(65), "1m 05s")

    def test_format_duration_hours(self):
        self.assertEqual(ui.format_duration(3725), "1h 02m")

    def test_format_tokens(self):
        self.assertEqual(ui.format_tokens(950), "950")
        self.assertEqual(ui.format_tokens(1500), "1.5k")
        self.assertEqual(ui.format_tokens(2_500_000), "2.5M")

    def test_format_cost(self):
        self.assertEqual(ui.format_cost(0), "$0.00")
        self.assertEqual(ui.format_cost(0.004), "<$0.01")
        self.assertEqual(ui.format_cost(0.4234), "$0.42")

    def test_progress_bar_is_exactly_the_requested_width(self):
        bar = ui.strip_ansi(ui.progress_bar(3, 10, width=20))
        self.assertEqual(len(bar), 20)

    def test_progress_bar_fills_proportionally(self):
        bar = ui.strip_ansi(ui.progress_bar(5, 10, width=10))
        self.assertEqual(bar.count(ui.BAR_FULL), 5)

    def test_progress_bar_complete_and_empty_edges(self):
        full = ui.strip_ansi(ui.progress_bar(4, 4, width=8))
        empty = ui.strip_ansi(ui.progress_bar(0, 4, width=8))
        self.assertEqual(full.count(ui.BAR_FULL), 8)
        self.assertEqual(empty.count(ui.BAR_FULL), 0)

    def test_progress_bar_handles_zero_total(self):
        bar = ui.strip_ansi(ui.progress_bar(0, 0, width=6))
        self.assertEqual(len(bar), 6)

    def test_spinner_frame_cycles(self):
        first = ui.spinner_frame(0)
        self.assertEqual(ui.spinner_frame(len(ui.SPINNER_FRAMES)), first)


class AskTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)
        self.out = io.StringIO()

    def _input_fn(self, answers):
        answers = list(answers)

        def fake(prompt=""):
            if not answers:
                raise AssertionError("ask() prompted more times than expected")
            return answers.pop(0)

        return fake

    def test_returns_trimmed_answer(self):
        value = ui.ask(
            "You sell for", input_fn=self._input_fn(["  MoveInSync  "]), out=self.out
        )
        self.assertEqual(value, "MoveInSync")

    def test_shows_label_and_hint(self):
        ui.ask(
            "Target account",
            hint="the company you are selling into",
            input_fn=self._input_fn(["Tata Steel"]),
            out=self.out,
        )
        printed = self.out.getvalue()
        self.assertIn("Target account", printed)
        self.assertIn("the company you are selling into", printed)

    def test_empty_answer_falls_back_to_default(self):
        value = ui.ask(
            "Model",
            default="sonnet",
            input_fn=self._input_fn([""]),
            out=self.out,
        )
        self.assertEqual(value, "sonnet")

    def test_default_is_displayed(self):
        ui.ask("Model", default="sonnet", input_fn=self._input_fn([""]), out=self.out)
        self.assertIn("sonnet", self.out.getvalue())

    def test_required_field_reprompts_until_answered(self):
        value = ui.ask(
            "Target account",
            input_fn=self._input_fn(["", "   ", "Tata Steel"]),
            out=self.out,
        )
        self.assertEqual(value, "Tata Steel")
        self.assertIn("required", self.out.getvalue().lower())

    def test_optional_field_accepts_empty(self):
        value = ui.ask(
            "Group", required=False, input_fn=self._input_fn([""]), out=self.out
        )
        self.assertEqual(value, "")

    def test_validator_rejection_reprompts_with_message(self):
        def validate(value):
            if len(value) < 3:
                return "too short"
            return None

        value = ui.ask(
            "Target account",
            validate=validate,
            input_fn=self._input_fn(["ab", "Tata Steel"]),
            out=self.out,
        )
        self.assertEqual(value, "Tata Steel")
        self.assertIn("too short", self.out.getvalue())

    def test_eof_raises_input_aborted(self):
        def fake(prompt=""):
            raise EOFError()

        with self.assertRaises(ui.InputAborted):
            ui.ask("You sell for", input_fn=fake, out=self.out)

    def test_keyboard_interrupt_raises_input_aborted(self):
        def fake(prompt=""):
            raise KeyboardInterrupt()

        with self.assertRaises(ui.InputAborted):
            ui.ask("You sell for", input_fn=fake, out=self.out)


class AskChoiceTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)
        self.out = io.StringIO()

    def test_accepts_a_listed_choice(self):
        value = ui.ask_choice(
            "Style",
            ["a", "b", "both"],
            default="a",
            input_fn=lambda prompt="": "both",
            out=self.out,
        )
        self.assertEqual(value, "both")

    def test_empty_uses_default(self):
        value = ui.ask_choice(
            "Style",
            ["a", "b", "both"],
            default="a",
            input_fn=lambda prompt="": "",
            out=self.out,
        )
        self.assertEqual(value, "a")

    def test_rejects_unlisted_choice_and_reprompts(self):
        answers = ["zzz", "b"]
        value = ui.ask_choice(
            "Style",
            ["a", "b"],
            default="a",
            input_fn=lambda prompt="": answers.pop(0),
            out=self.out,
        )
        self.assertEqual(value, "b")
        self.assertFalse(answers)


class LiveRegionTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def _region(self, frames, width=40):
        self.stream = io.StringIO()
        box = {"frame": frames[0]}
        self.box = box
        return (
            ui.LiveRegion(
                lambda: box["frame"],
                stream=self.stream,
                enabled=True,
                width_fn=lambda: width,
            ),
            box,
        )

    def test_first_refresh_paints_lines_without_moving_cursor(self):
        region, _ = self._region([["one", "two"]])
        region.refresh()
        painted = self.stream.getvalue()
        self.assertIn("one", painted)
        self.assertIn("two", painted)
        self.assertNotIn("\x1b[2A", painted)

    def test_second_refresh_rewinds_by_previous_line_count(self):
        region, box = self._region([["one", "two", "three"]])
        region.refresh()
        self.stream.truncate(0)
        self.stream.seek(0)
        box["frame"] = ["one", "two", "three"]
        region.refresh()
        self.assertIn("\x1b[3A", self.stream.getvalue())

    def test_shrinking_frame_erases_leftover_lines(self):
        region, box = self._region([["a", "b", "c"]])
        region.refresh()
        box["frame"] = ["a"]
        self.stream.truncate(0)
        self.stream.seek(0)
        region.refresh()
        painted = self.stream.getvalue()
        self.assertIn("\x1b[3A", painted)
        self.assertGreaterEqual(painted.count("\x1b[2K"), 3)

    def test_lines_are_truncated_to_terminal_width(self):
        region, _ = self._region([["x" * 200]], width=20)
        region.refresh()
        for line in self.stream.getvalue().split("\n"):
            self.assertLessEqual(ui.visible_width(line), 20)

    def test_pause_clears_the_painted_frame(self):
        region, _ = self._region([["one", "two"]])
        region.refresh()
        self.stream.truncate(0)
        self.stream.seek(0)
        region.pause()
        painted = self.stream.getvalue()
        self.assertIn("\x1b[2A", painted)
        self.assertIn("\x1b[0J", painted)

    def test_refresh_after_pause_repaints_from_scratch(self):
        region, _ = self._region([["one", "two"]])
        region.refresh()
        region.pause()
        self.stream.truncate(0)
        self.stream.seek(0)
        region.refresh()
        self.assertNotIn("\x1b[2A", self.stream.getvalue())

    def test_disabled_region_writes_nothing(self):
        stream = io.StringIO()
        region = ui.LiveRegion(lambda: ["one"], stream=stream, enabled=False)
        region.start()
        region.refresh()
        region.stop()
        self.assertEqual(stream.getvalue(), "")

    def test_stop_restores_the_cursor(self):
        region, _ = self._region([["one"]])
        region.start()
        region.refresh()
        region.stop()
        self.assertIn(ui.SHOW_CURSOR, self.stream.getvalue())


class LayoutTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)

    def test_panel_wraps_content_in_a_box_of_equal_width(self):
        lines = ui.panel(["hello", "a longer line"], width=30)
        self.assertTrue(all(ui.visible_width(line) == 30 for line in lines))
        self.assertTrue(lines[0].startswith(ui.BOX["tl"]))
        self.assertTrue(lines[-1].startswith(ui.BOX["bl"]))

    def test_panel_truncates_content_that_does_not_fit(self):
        lines = ui.panel(["x" * 100], width=20)
        self.assertTrue(all(ui.visible_width(line) == 20 for line in lines))

    def test_field_row_aligns_label_column(self):
        rows = [ui.field_row("You sell for", "MoveInSync", label_width=16),
                ui.field_row("Target account", "Tata Steel", label_width=16)]
        offsets = [ui.strip_ansi(row).index(v) for row, v in
                   zip(rows, ["MoveInSync", "Tata Steel"])]
        self.assertEqual(offsets[0], offsets[1])


if __name__ == "__main__":
    unittest.main()
