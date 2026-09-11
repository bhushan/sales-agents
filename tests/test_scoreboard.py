import unittest

from sales_agents import scoreboard

RESEARCH_STEP = """
## Industry: Steel manufacturing
| What changed | Source + date | Why | Status |
| capex cycle | Reuters, 2026-03-01 | frees budget | VERIFIED |

VERIFIED: 3 | ASSERTED: 1 | TOTAL: 4
Two things I could not find out:
"""

GRADE_RESEARCH = """
| row | A | B | C | D |
| the first row | YES | YES | YES | YES |

ROWS: 12 | FAILED A: 2 | FAILED B: 1 | FAILED C: 3 | FAILED D: 0
DO NOT USE
- headcount is around 1,400 (2022 press release)
"""

GRADE_MESSAGES = """
1. In today's volatile input-cost environment — GENERIC

SENTENCES: 20 | FROM PACK: 13 | INFERRED: 2 | GENERIC: 3 | MADE UP: 1 | BANNED: 1
"""


class ParseCountsTests(unittest.TestCase):
    def test_reads_the_research_step_counters(self):
        counts = scoreboard.parse_counts(RESEARCH_STEP)
        self.assertEqual(counts["VERIFIED"], 3)
        self.assertEqual(counts["ASSERTED"], 1)
        self.assertEqual(counts["TOTAL"], 4)

    def test_reads_the_research_grader_counters(self):
        counts = scoreboard.parse_counts(GRADE_RESEARCH)
        self.assertEqual(counts["ROWS"], 12)
        self.assertEqual(counts["FAILED A"], 2)
        self.assertEqual(counts["FAILED D"], 0)

    def test_reads_the_message_grader_counters(self):
        counts = scoreboard.parse_counts(GRADE_MESSAGES)
        self.assertEqual(counts["SENTENCES"], 20)
        self.assertEqual(counts["FROM PACK"], 13)
        self.assertEqual(counts["INFERRED"], 2)
        self.assertEqual(counts["MADE UP"], 1)
        self.assertEqual(counts["BANNED"], 1)

    def test_ignores_prose_that_merely_mentions_a_word(self):
        self.assertEqual(scoreboard.parse_counts("nothing verified here"), {})

    def test_last_counter_line_wins(self):
        text = "VERIFIED: 1 | TOTAL: 2\n\nlater\n\nVERIFIED: 5 | TOTAL: 9"
        self.assertEqual(scoreboard.parse_counts(text)["VERIFIED"], 5)

    def test_missing_counters_return_empty(self):
        self.assertEqual(scoreboard.parse_counts("no counters at all"), {})


class BadgeTests(unittest.TestCase):
    def test_research_step_badge_shows_verified_and_asserted(self):
        badge = scoreboard.badge(RESEARCH_STEP)
        self.assertIn("3", badge)
        self.assertIn("verified", badge.lower())
        self.assertIn("asserted", badge.lower())

    def test_grader_badge_shows_unsourced_rows(self):
        badge = scoreboard.badge(GRADE_RESEARCH)
        self.assertIn("2", badge)
        self.assertIn("12", badge)

    def test_message_grader_badge_shows_the_dangerous_labels(self):
        badge = scoreboard.badge(GRADE_MESSAGES)
        self.assertIn("made up", badge.lower())
        self.assertIn("banned", badge.lower())
        self.assertIn("inferred", badge.lower())

    def test_output_without_counters_has_no_badge(self):
        self.assertEqual(scoreboard.badge("just prose"), "")


class ResearchVerdictTests(unittest.TestCase):
    def test_below_half_sourced_is_not_usable(self):
        level, message = scoreboard.research_verdict({"ROWS": 10, "FAILED A": 6})
        self.assertEqual(level, "bad")
        self.assertIn("not usable", message.lower())

    def test_middling_is_a_normal_first_attempt(self):
        level, message = scoreboard.research_verdict({"ROWS": 10, "FAILED A": 4})
        self.assertEqual(level, "warn")
        self.assertIn("fix the prompt", message.lower())

    def test_three_quarters_sourced_is_strong(self):
        level, message = scoreboard.research_verdict({"ROWS": 12, "FAILED A": 2})
        self.assertEqual(level, "good")
        self.assertIn("strong", message.lower())

    def test_no_rows_has_no_verdict(self):
        self.assertIsNone(scoreboard.research_verdict({}))

    def test_ratio_is_reported(self):
        self.assertEqual(scoreboard.sourced_ratio({"ROWS": 12, "FAILED A": 3}), 0.75)


class MessageVerdictTests(unittest.TestCase):
    def test_any_made_up_sentence_blocks_the_message(self):
        level, message = scoreboard.message_verdict(
            {"SENTENCES": 20, "FROM PACK": 18, "GENERIC": 1, "MADE UP": 1, "BANNED": 0}
        )
        self.assertEqual(level, "bad")
        self.assertIn("does not go out", message.lower())

    def test_any_banned_sentence_blocks_the_message(self):
        level, _ = scoreboard.message_verdict(
            {"SENTENCES": 20, "FROM PACK": 19, "GENERIC": 0, "MADE UP": 0, "BANNED": 1}
        )
        self.assertEqual(level, "bad")

    def test_too_much_generic_is_a_warning(self):
        level, message = scoreboard.message_verdict(
            {"SENTENCES": 10, "FROM PACK": 6, "GENERIC": 4, "MADE UP": 0, "BANNED": 0}
        )
        self.assertEqual(level, "warn")
        self.assertIn("research did not earn", message.lower())

    def test_mostly_from_pack_is_strong(self):
        level, message = scoreboard.message_verdict(
            {"SENTENCES": 10, "FROM PACK": 8, "GENERIC": 2, "MADE UP": 0, "BANNED": 0}
        )
        self.assertEqual(level, "good")
        self.assertIn("strong", message.lower())

    def test_a_consequence_drawn_from_the_pack_counts_as_grounded(self):
        """The email prompt asks for the "so what" of a fact. Grading that
        as invention was the false alarm that made the gate useless."""
        level, _ = scoreboard.message_verdict(
            {
                "SENTENCES": 10,
                "FROM PACK": 5,
                "INFERRED": 3,
                "GENERIC": 2,
                "MADE UP": 0,
                "BANNED": 0,
            }
        )
        self.assertEqual(level, "good")

    def test_an_email_leaning_on_inference_more_than_sources_is_not_strong(self):
        level, message = scoreboard.message_verdict(
            {
                "SENTENCES": 10,
                "FROM PACK": 2,
                "INFERRED": 7,
                "GENERIC": 1,
                "MADE UP": 0,
                "BANNED": 0,
            }
        )
        self.assertEqual(level, "warn")
        self.assertIn("inference", message.lower())

    def test_invention_still_blocks_the_message_whatever_else_is_true(self):
        level, _ = scoreboard.message_verdict(
            {
                "SENTENCES": 10,
                "FROM PACK": 8,
                "INFERRED": 1,
                "GENERIC": 0,
                "MADE UP": 1,
                "BANNED": 0,
            }
        )
        self.assertEqual(level, "bad")

    def test_no_sentences_has_no_verdict(self):
        self.assertIsNone(scoreboard.message_verdict({}))


class ReportTests(unittest.TestCase):
    def test_report_lists_a_line_per_graded_output(self):
        outputs = {
            "industry": RESEARCH_STEP,
            "grade_research": GRADE_RESEARCH,
            "grade_messages": GRADE_MESSAGES,
        }
        text = "\n".join(scoreboard.report(outputs))
        self.assertIn("12", text)
        self.assertIn("20", text)

    def test_report_carries_the_verdicts(self):
        outputs = {"grade_research": GRADE_RESEARCH, "grade_messages": GRADE_MESSAGES}
        text = "\n".join(scoreboard.report(outputs)).lower()
        self.assertIn("strong", text)
        self.assertIn("does not go out", text)

    def test_report_is_empty_without_counters(self):
        self.assertEqual(scoreboard.report({"icp": "no counters"}), [])


if __name__ == "__main__":
    unittest.main()
