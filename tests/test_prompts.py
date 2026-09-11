"""What the prompt files have to keep saying.

These are the rules the graded runs showed were load-bearing: a prompt
that quietly loses one of them fails silently, by producing worse
research rather than an error.
"""

import re
import unittest

from sales_agents import scoreboard
from sales_agents.steps import PROMPTS_DIR, STEPS


def prompt(name):
    return (PROMPTS_DIR / name).read_text()


def flat(text):
    """One line, single-spaced: prompt wording matters, line breaks do not."""
    return " ".join(text.split()).lower()


def counter_line(text, first_word):
    for line in text.splitlines():
        if first_word + ":" in line:
            return line[line.index(first_word) :].strip()
    raise AssertionError(f"no {first_word} counter line in the prompt")


class CounterContractTests(unittest.TestCase):
    """The counter line a grader is told to print, read back by the parser
    that has to understand it."""

    def parsed(self, text, first_word):
        line = re.sub(r"\bn\b", "7", counter_line(text, first_word))
        return scoreboard.parse_counts(line)

    def test_research_grader_counters_parse(self):
        counts = self.parsed(prompt("06_grade_research.md"), "ROWS")
        self.assertEqual(
            set(counts),
            {"ROWS", "FAILED A", "FAILED B", "FAILED C", "FAILED D"},
        )

    def test_message_grader_counters_parse(self):
        counts = self.parsed(prompt("09_grade_messages.md"), "SENTENCES")
        self.assertEqual(
            set(counts),
            {"SENTENCES", "FROM PACK", "INFERRED", "GENERIC", "MADE UP", "BANNED"},
        )

    def test_research_step_counters_parse(self):
        for name in ("01_industry.md", "02_account.md", "03_roles.md", "04_people.md"):
            counts = self.parsed(prompt(name), "VERIFIED")
            self.assertIn("VERIFIED", counts, name)
            self.assertIn("TOTAL", counts, name)


class PackTemplateTests(unittest.TestCase):
    """Every section the research grader will grade needs somewhere to put a
    source. Sections without one failed check A by construction, and their
    rows were dumped into "Do not use" before an email was ever written."""

    def setUp(self):
        self.pack = prompt("05_pack.md")

    def sections(self):
        found = {}
        current = None
        for line in self.pack.splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
                found[current] = []
            elif current:
                found[current].append(line)
        return found

    def test_every_section_can_carry_a_source_or_is_marked_inferred(self):
        for name, body in self.sections().items():
            if name == "Do not use":
                continue
            text = "\n".join(body)
            self.assertTrue(
                "Source + date:" in text or "Link + date:" in text,
                f"section {name!r} has no source field",
            )

    def test_judgement_fields_are_marked_so_the_grader_skips_them(self):
        for field in (
            "Why they fit our ICP",
            "Role in the decision",
            "What they are measured on",
            "What they would fear about buying this",
        ):
            line = next(
                line for line in self.pack.splitlines() if line.startswith(field)
            )
            self.assertIn("inferred", line.lower(), field)

    def test_the_do_not_use_placeholder_survives_for_the_grader_to_fill(self):
        self.assertIn("## Do not use", self.pack)


class ResearchGraderTests(unittest.TestCase):
    def setUp(self):
        self.text = prompt("06_grade_research.md")

    def test_inferred_fields_are_not_graded_as_claims(self):
        self.assertIn("inferred, not graded", self.text)

    def test_a_field_with_nothing_in_it_is_not_a_failed_row(self):
        self.assertIn("not found", self.text)

    def test_only_an_unsourced_row_is_banned_from_the_emails(self):
        """A row can be undated and still be true. Only check A decides what
        goes on the "Do not use" list."""
        self.assertIn("only check a puts a row on that list", flat(self.text))
        self.assertIn("must not be listed there", flat(self.text))

    def test_a_standing_fact_is_allowed_to_have_no_date(self):
        self.assertIn("— for not applicable", flat(self.text))
        self.assertIn("a — is not a failure", flat(self.text))


class MessageGraderTests(unittest.TestCase):
    def setUp(self):
        self.text = prompt("09_grade_messages.md")

    def test_every_label_is_defined(self):
        for label in ("FROM PACK", "INFERRED", "GENERIC", "MADE UP", "BANNED"):
            self.assertIn(label, self.text)

    def test_a_question_is_graded_on_what_it_assumes(self):
        self.assertIn("question", self.text.lower())

    def test_claims_about_other_customers_are_made_up(self):
        self.assertIn("peers", self.text.lower())

    def test_a_sentence_resting_on_an_inferred_field_is_not_from_pack(self):
        self.assertIn("inferred, not graded", self.text)

    def test_guessing_the_accounts_internal_state_is_invention(self):
        self.assertIn("tracks or is planning internally", flat(self.text))


class WriterPromptTests(unittest.TestCase):
    """Both writers get the same ban list, because the grader found the same
    inventions in emails and in LinkedIn messages."""

    def writers(self):
        return {name: prompt(name) for name in ("07_emails.md", "08_linkedin.md")}

    def test_do_not_use_is_off_limits_even_reworded(self):
        for name, text in self.writers().items():
            self.assertIn("Do not use", text, name)
            self.assertIn("reworded", text.lower(), name)

    def test_peers_and_other_customers_are_banned(self):
        for name, text in self.writers().items():
            self.assertIn("peers", text.lower(), name)

    def test_comparisons_the_pack_does_not_make_are_banned(self):
        for name, text in self.writers().items():
            self.assertIn("compar", text.lower(), name)

    def test_a_question_may_only_assume_what_the_pack_says(self):
        for name, text in self.writers().items():
            self.assertIn("question", text.lower(), name)

    def test_the_accounts_internal_state_is_not_guessable(self):
        """Both surviving inventions in the last graded run asserted what the
        account tracks internally, which nobody outside can see."""
        for name, text in self.writers().items():
            self.assertIn("tracks or is planning internally", flat(text), name)


class NoHardcodedAccountTests(unittest.TestCase):
    """Everything case-specific arrives through the three inputs. A product
    or company name left in a prompt does not raise, it just researches the
    wrong thing."""

    NAMES = ("MoveInSync", "Mphasis", "Tata Steel", "IIM", "commute", "e-auction")

    def test_no_prompt_names_a_company_or_product(self):
        for step in STEPS.values():
            text = prompt(step.template)
            for name in self.NAMES:
                self.assertNotIn(name.lower(), text.lower(), f"{step.template}: {name}")


if __name__ == "__main__":
    unittest.main()
