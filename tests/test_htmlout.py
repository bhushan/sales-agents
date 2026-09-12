import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sales_agents import htmlout, runs
from sales_agents.state import RunState


def write_run(root, name, company, files, *, seller="Alfred Scholar", offering="a workspace"):
    run_dir = Path(root) / name
    run_dir.mkdir(parents=True, exist_ok=True)
    completed = {}
    for step_id, (filename, text) in files.items():
        (run_dir / filename).write_text(text)
        completed[step_id] = filename
    RunState(
        run_dir=run_dir,
        company=company,
        industry="",
        model="sonnet",
        group="",
        date="2026-09-11",
        seller=seller,
        offering=offering,
        completed=completed,
    ).save()
    return run_dir


class InlineTests(unittest.TestCase):
    def test_bold_and_italic_become_tags(self):
        html = htmlout.render_markdown("**hard** and *soft*")
        self.assertIn("<strong>hard</strong>", html)
        self.assertIn("<em>soft</em>", html)

    def test_code_span_becomes_code(self):
        self.assertIn("<code>claude -p</code>", htmlout.render_markdown("`claude -p`"))

    def test_link_keeps_its_text_and_href(self):
        html = htmlout.render_markdown("[The Federal](https://thefederal.com/x)")
        self.assertIn('href="https://thefederal.com/x"', html)
        self.assertIn(">The Federal</a>", html)

    def test_javascript_urls_are_not_linked(self):
        html = htmlout.render_markdown("[click](javascript:alert(1))")
        self.assertNotIn("javascript:", html)

    def test_markup_in_the_source_is_escaped(self):
        html = htmlout.render_markdown("<script>alert('x')</script> & <b>no</b>")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>no</b>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)


class BlockTests(unittest.TestCase):
    def test_headings_keep_their_level(self):
        html = htmlout.render_markdown("# Email 1\n\n## The company")
        self.assertIn("Email 1</h1>", html)
        self.assertIn("The company</h2>", html)

    def test_paragraph_is_wrapped(self):
        self.assertIn("<p>Prof. Thampy,</p>", htmlout.render_markdown("Prof. Thampy,"))

    def test_bullets_become_one_list(self):
        html = htmlout.render_markdown("- one\n- two")
        self.assertEqual(html.count("<ul>"), 1)
        self.assertEqual(html.count("<li>"), 2)

    def test_numbered_items_become_an_ordered_list(self):
        html = htmlout.render_markdown("1. first\n2. second")
        self.assertIn("<ol", html)
        self.assertEqual(html.count("<li>"), 2)

    def test_label_lines_become_labelled_fields(self):
        html = htmlout.render_markdown("Source + date: UGC notice, July 16, 2025")
        self.assertIn("Source + date", html)
        self.assertIn("field", html)
        self.assertNotIn("<p>Source + date:", html)

    def test_three_fields_on_one_line_are_read_as_three(self):
        html = htmlout.render_markdown(
            "Group:             Account: mphasis            Date: 2026-09-11"
        )
        self.assertIn("<dt>Account</dt><dd>mphasis</dd>", html)
        self.assertIn("<dt>Date</dt><dd>2026-09-11</dd>", html)

    def test_a_value_with_its_own_colon_stays_whole(self):
        html = htmlout.render_markdown("Source + date: UGC notice, July 16, 2025")
        self.assertIn("<dd>UGC notice, July 16, 2025</dd>", html)

    def test_a_sentence_that_opens_with_a_label_stays_a_sentence(self):
        html = htmlout.render_markdown(
            "Prof. Thampy,\n\n"
            "One thing worth flagging: UGC discontinued the CARE list in "
            "February 2025.\n\nBest,"
        )
        self.assertNotIn("<dt>One thing worth flagging</dt>", html)
        self.assertIn("<p>One thing worth flagging:", html)

    def test_a_block_of_labelled_lines_is_still_a_block_of_fields(self):
        html = htmlout.render_markdown(
            "Name: IIM Bangalore\nSource + date: iimb.ac.in, 2026\nStatus: VERIFIED"
        )
        self.assertIn("<dt>Name</dt>", html)
        self.assertIn("<dt>Status</dt>", html)

    def test_quote_and_rule(self):
        html = htmlout.render_markdown("> quoted\n\n---")
        self.assertIn("<blockquote>", html)
        self.assertIn("<hr", html)

    def test_fenced_code_is_preserved_verbatim(self):
        html = htmlout.render_markdown("```\n**not bold**\n```")
        self.assertIn("<pre>", html)
        self.assertIn("**not bold**", html)


class TableTests(unittest.TestCase):
    SOURCE = (
        "| Sentence | Label |\n"
        "|---|---|\n"
        '| "One thing" | FROM PACK |\n'
        '| "Another" | GENERIC |\n'
    )

    def test_header_cells_are_headers(self):
        html = htmlout.render_markdown(self.SOURCE)
        self.assertIn("<th>Sentence</th>", html)
        self.assertIn("<th>Label</th>", html)

    def test_separator_row_is_dropped(self):
        html = htmlout.render_markdown(self.SOURCE)
        self.assertNotIn("---", html)
        self.assertEqual(html.count("<tr>"), 3)

    def test_ragged_rows_are_padded(self):
        html = htmlout.render_markdown("| a | b |\n|---|---|\n| only |\n")
        self.assertEqual(html.count("<td"), 2)


class VerdictWordTests(unittest.TestCase):
    def test_sourced_words_are_marked_good(self):
        html = htmlout.render_markdown("Status: VERIFIED")
        self.assertIn("verdict-good", html)

    def test_invented_words_are_marked_bad(self):
        html = htmlout.render_markdown("| x | MADE UP |")
        self.assertIn("verdict-bad", html)

    def test_soft_words_are_marked_warn(self):
        self.assertIn("verdict-warn", htmlout.render_markdown("Status: ASSERTED"))

    def test_a_verdict_word_is_still_readable(self):
        self.assertIn("VERIFIED", htmlout.render_markdown("Status: VERIFIED"))


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_run(
            self.root,
            "iim",
            "IIM Bangalore",
            {
                "icp": ("00-icp.md", "# ICP\n\nVERIFIED: 4 | ASSERTED: 1 | TOTAL: 5\n"),
                "grade_research": (
                    "06-grade-research.md",
                    "ROWS: 10 | FAILED A: 1 | FAILED B: 0 | FAILED C: 2\n",
                ),
                "grade_messages": (
                    "09-grade-messages.md",
                    "SENTENCES: 20 | FROM PACK: 10 | INFERRED: 5 | GENERIC: 5 "
                    "| MADE UP: 0 | BANNED: 0\n",
                ),
            },
        )
        write_run(self.root, "acme", "Acme <Steel>", {"icp": ("00-icp.md", "# ICP\n")})
        self.summaries = runs.discover(self.root)
        self.html = htmlout.document(self.summaries)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_run_is_in_the_page(self):
        self.assertIn("IIM Bangalore", self.html)
        self.assertIn("Acme &lt;Steel&gt;", self.html)

    def test_a_company_name_cannot_inject_markup(self):
        self.assertNotIn("Acme <Steel>", self.html)

    def test_every_stage_title_is_listed(self):
        self.assertIn("The ICP", self.html)
        self.assertIn("Grade the messages", self.html)

    def test_stages_that_never_ran_are_marked(self):
        self.assertIn("not run", self.html.lower())

    def test_counters_are_shown(self):
        self.assertIn("VERIFIED", self.html)
        self.assertIn("FROM PACK", self.html)

    def test_the_research_verdict_is_applied(self):
        self.assertIn("Strong.", self.html)

    def test_the_page_is_self_contained(self):
        self.assertNotIn("<script src=", self.html)
        self.assertNotIn('<link rel="stylesheet"', self.html)
        self.assertNotIn("https://fonts.", self.html)
        self.assertNotIn("cdn.", self.html)

    def test_it_is_a_whole_document(self):
        self.assertTrue(self.html.lstrip().startswith("<!doctype html>"))
        self.assertIn("</html>", self.html.rstrip()[-10:])
        self.assertIn('<meta name="viewport"', self.html)

    def test_stage_text_is_rendered_not_dumped(self):
        self.assertNotIn("# ICP", self.html)

    def test_an_empty_list_of_runs_still_renders(self):
        page = htmlout.document([])
        self.assertIn("No runs", page)


class ExtraFileTests(unittest.TestCase):
    def test_style_variant_outputs_are_not_lost(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_run(
                root,
                "mphasis",
                "Mphasis",
                {"icp": ("00-icp.md", "# ICP\n")},
            )
            (run_dir / "07a-emails-style-a.md").write_text("# Email 1\n\nstyle a body\n")
            summary = runs.load(run_dir)
            titles = [stage.step.title for stage in summary.all_stages()]
            self.assertTrue(any("style a" in title.lower() for title in titles))
            html = htmlout.document([summary])
            self.assertIn("style a body", html)

    def test_a_stage_that_ran_in_two_styles_is_not_reported_missing(self):
        with TemporaryDirectory() as tmp:
            run_dir = write_run(Path(tmp), "m", "M", {"icp": ("00-icp.md", "# ICP\n")})
            (run_dir / "07a-emails-style-a.md").write_text("a\n")
            (run_dir / "07b-emails-style-b.md").write_text("b\n")
            stages = runs.load(run_dir).all_stages()
            missing = [s.path.name for s in stages if not s.exists]
            self.assertNotIn("07-emails.md", missing)

    def test_outputs_stay_in_the_order_the_chain_wrote_them(self):
        with TemporaryDirectory() as tmp:
            run_dir = write_run(Path(tmp), "m", "M", {"icp": ("00-icp.md", "# ICP\n")})
            (run_dir / "07a-emails-style-a.md").write_text("a\n")
            names = [s.path.name for s in runs.load(run_dir).all_stages()]
            self.assertLess(names.index("07a-emails-style-a.md"), names.index("08-linkedin.md"))
            self.assertGreater(names.index("07a-emails-style-a.md"), names.index("06-grade-research.md"))

    def test_state_json_is_not_treated_as_a_stage(self):
        with TemporaryDirectory() as tmp:
            run_dir = write_run(Path(tmp), "x", "X", {"icp": ("00-icp.md", "# ICP\n")})
            names = [stage.path.name for stage in runs.load(run_dir).all_stages()]
            self.assertNotIn("state.json", names)

    def test_known_stage_files_are_not_listed_twice(self):
        with TemporaryDirectory() as tmp:
            run_dir = write_run(Path(tmp), "x", "X", {"icp": ("00-icp.md", "# ICP\n")})
            names = [stage.path.name for stage in runs.load(run_dir).all_stages()]
            self.assertEqual(names.count("00-icp.md"), 1)


class ComparisonTests(unittest.TestCase):
    def test_runs_are_compared_side_by_side(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, "a", "Alpha", {"icp": ("00-icp.md", "VERIFIED: 3 | TOTAL: 3\n")})
            write_run(root, "b", "Beta", {"icp": ("00-icp.md", "VERIFIED: 1 | TOTAL: 4\n")})
            html = htmlout.document(runs.discover(root))
            table = re.search(r'id="compare".*?</section>', html, re.S)
            self.assertIsNotNone(table)
            self.assertIn("Alpha", table.group(0))
            self.assertIn("Beta", table.group(0))


if __name__ == "__main__":
    unittest.main()
