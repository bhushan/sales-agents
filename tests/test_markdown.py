import unittest

from sales_agents import markdown, ui


def plain(lines):
    return [ui.strip_ansi(line) for line in lines]


def render_plain(text, width=60):
    return plain(markdown.render(text, width))


class Coloured(unittest.TestCase):
    """Colour is off when output is not a terminal, so turn it on to assert
    on painting."""

    def setUp(self):
        ui.set_color(True)

    def tearDown(self):
        ui.set_color(False)


class HeadingTests(unittest.TestCase):
    def test_hash_markers_are_not_shown(self):
        lines = render_plain("## What changed in their industry")
        self.assertIn("What changed in their industry", "\n".join(lines))
        self.assertNotIn("#", "\n".join(lines))

    def test_heading_gets_breathing_room_above_it(self):
        lines = render_plain("text\n## Section\nmore")
        self.assertEqual(lines, ["text", "", "Section", "more"])

    def test_no_blank_line_before_a_leading_heading(self):
        lines = render_plain("# Title\nbody")
        self.assertEqual(lines[0].strip(), "Title")


class PaintTests(Coloured):
    def test_heading_is_painted(self):
        self.assertIn(ui.ESC, markdown.render("# Personalization Pack", 60)[0])

    def test_bold_text_is_painted(self):
        rendered = markdown.render("**Email 1**", 60)[0]
        self.assertIn(ui.ESC, rendered)
        self.assertEqual(ui.strip_ansi(rendered), "Email 1")

    def test_verdict_words_are_coloured(self):
        rendered = markdown.render('1. "A claim." - MADE UP', 60)[0]
        self.assertIn(ui.ESC, rendered)
        self.assertIn("MADE UP", ui.strip_ansi(rendered))

    def test_inferred_is_coloured_too(self):
        self.assertIn(ui.ESC, markdown.render("2. \"A guess.\" - INFERRED", 60)[0])

    def test_ordinary_prose_is_left_alone(self):
        self.assertEqual(markdown.render("just a sentence", 60), ["just a sentence"])


class InlineTests(unittest.TestCase):
    def test_bold_markers_are_removed(self):
        lines = render_plain("**Email 1** is ready")
        self.assertEqual(lines, ["Email 1 is ready"])

    def test_italic_markers_are_removed(self):
        self.assertEqual(render_plain("an *important* point"), ["an important point"])

    def test_underscore_emphasis_inside_a_word_is_left_alone(self):
        self.assertIn("snake_case_name", render_plain("a snake_case_name here")[0])

    def test_inline_code_markers_are_removed(self):
        self.assertEqual(render_plain("run `make test` now"), ["run make test now"])

    def test_link_keeps_both_text_and_url(self):
        line = render_plain("see [the notice](https://ugc.gov.in/x) for detail")[0]
        self.assertIn("the notice", line)
        self.assertIn("https://ugc.gov.in/x", line)

class FieldTests(unittest.TestCase):
    def test_label_and_value_both_survive(self):
        self.assertEqual(
            render_plain("Source + date: Deccan Herald, Nov 15 2025"),
            ["Source + date: Deccan Herald, Nov 15 2025"],
        )

    def test_a_long_value_wraps_under_its_label(self):
        lines = render_plain("What they do: " + "word " * 12, 30)
        self.assertTrue(lines[0].startswith("What they do: "))
        self.assertGreater(len(lines), 1)
        for line in lines[1:]:
            self.assertTrue(line.startswith("  "))

    def test_a_bare_url_is_not_mistaken_for_a_field(self):
        line = render_plain("https://tatasteel.com/news/x")[0]
        self.assertEqual(line, "https://tatasteel.com/news/x")


class WrapTests(unittest.TestCase):
    def test_every_line_fits_the_width(self):
        text = "word " * 80
        for line in markdown.render(text, 30):
            self.assertLessEqual(ui.visible_width(line), 30)

    def test_wrapping_measures_text_without_its_markers(self):
        # 40 visible characters, but 44 with the ** markers around it.
        lines = render_plain("**" + "a" * 20 + " " + "b" * 19 + "**", 42)
        self.assertEqual(len(lines), 1)

    def test_blank_lines_are_kept(self):
        self.assertEqual(render_plain("one\n\ntwo"), ["one", "", "two"])

    def test_a_word_longer_than_the_width_is_split(self):
        lines = render_plain("x" * 50, 20)
        self.assertEqual("".join(lines), "x" * 50)


class ListTests(unittest.TestCase):
    def test_dash_bullet_becomes_a_bullet(self):
        self.assertEqual(render_plain("- one thing"), ["• one thing"])

    def test_bullet_continuation_is_indented_under_the_text(self):
        lines = render_plain("- " + "word " * 10, 20)
        self.assertTrue(lines[0].startswith("• "))
        for line in lines[1:]:
            self.assertTrue(line.startswith("  "))

    def test_numbered_list_keeps_its_number(self):
        self.assertEqual(render_plain("1. first"), ["1. first"])

    def test_empty_bullet_placeholder_survives(self):
        self.assertEqual(render_plain("-"), ["•"])


class TableTests(unittest.TestCase):
    NARROW = (
        "| Claim | Status |\n"
        "|---|---|\n"
        "| Board approved expansion | VERIFIED |\n"
        "| Vendor portal is live | ASSERTED |\n"
    )

    def test_pipes_and_separator_row_are_gone(self):
        lines = render_plain(self.NARROW, 60)
        joined = "\n".join(lines)
        self.assertNotIn("|", joined)
        self.assertNotIn("---", joined)

    def test_columns_are_aligned(self):
        lines = [line for line in render_plain(self.NARROW, 60) if "VERIFIED" in line]
        other = [line for line in render_plain(self.NARROW, 60) if "ASSERTED" in line]
        self.assertEqual(lines[0].index("VERIFIED"), other[0].index("ASSERTED"))

    def test_header_and_cells_both_survive(self):
        joined = "\n".join(render_plain(self.NARROW, 60))
        self.assertIn("Claim", joined)
        self.assertIn("Board approved expansion", joined)

    def test_a_table_too_wide_to_align_becomes_labelled_records(self):
        wide = (
            "| Claim | Source + date | Status |\n"
            "|---|---|---|\n"
            "| Bengaluru Traffic Police asked tech parks to start pay-and-park "
            "| Deccan Herald, November 15 2025 | VERIFIED |\n"
        )
        lines = render_plain(wide, 40)
        joined = "\n".join(lines)
        self.assertIn("Source + date", joined)
        self.assertIn("Deccan Herald", joined)
        # nothing is cut: the long claim survives in full across wrapped lines
        self.assertIn("pay-and-park", joined.replace("\n", " "))
        for line in lines:
            self.assertLessEqual(len(line), 40)

    def test_records_are_separated_by_a_blank_line(self):
        wide = (
            "| Claim | Source + date | Status |\n"
            "|---|---|---|\n"
            "| First claim that runs on a while | Somewhere, 2025 | VERIFIED |\n"
            "| Second claim that also runs on | Elsewhere, 2025 | ASSERTED |\n"
        )
        lines = render_plain(wide, 40)
        first = next(i for i, line in enumerate(lines) if "First claim" in line)
        second = next(i for i, line in enumerate(lines) if "Second claim" in line)
        self.assertIn("", lines[first:second])

    def test_table_cells_keep_their_inline_formatting(self):
        table = "| Claim |\n|---|\n| **bold** claim |\n"
        self.assertIn("bold claim", "\n".join(render_plain(table, 40)))

    def test_ragged_rows_do_not_crash(self):
        table = "| A | B |\n|---|---|\n| only one |\n| x | y | z |\n"
        self.assertTrue(render_plain(table, 40))


class BlockTests(unittest.TestCase):
    def test_horizontal_rule_becomes_a_line(self):
        line = render_plain("---", 10)[0]
        self.assertEqual(line, "─" * 10)

    def test_blockquote_is_marked_and_stripped(self):
        line = render_plain("> quoted thing")[0]
        self.assertIn("quoted thing", line)
        self.assertNotIn(">", line)

    def test_fenced_code_is_left_verbatim(self):
        lines = render_plain("```\n  **not bold**\n```", 60)
        self.assertIn("  **not bold**", lines)

    def test_empty_text_renders_nothing(self):
        self.assertEqual(markdown.render("", 40), [])


if __name__ == "__main__":
    unittest.main()
