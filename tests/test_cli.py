import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sales_agents import pairings, settings, ui
from sales_agents.cli import build_parser, collect_inputs
from sales_agents.steps import STEP_ORDER
from sales_agents.state import RunState


class Answers:
    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = 0

    def __call__(self, prompt=""):
        self.asked += 1
        if not self.answers:
            raise AssertionError("the wizard asked more questions than expected")
        return self.answers.pop(0)


class CollectInputsTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)
        self.out = io.StringIO()

    def test_asks_the_three_core_questions(self):
        answers = Answers(["MoveInSync", "employee commute automation", "Tata Steel"])
        values = collect_inputs(input_fn=answers, out=self.out)
        self.assertEqual(values["seller"], "MoveInSync")
        self.assertEqual(values["offering"], "employee commute automation")
        self.assertEqual(values["company"], "Tata Steel")

    def test_labels_match_the_three_fields(self):
        collect_inputs(
            input_fn=Answers(["A", "B", "C"]),
            out=self.out,
        )
        printed = ui.strip_ansi(self.out.getvalue())
        self.assertIn("You sell for", printed)
        self.assertIn("What they sell", printed)
        self.assertIn("Target account", printed)

    def test_values_passed_in_are_not_asked_again(self):
        answers = Answers(["Tata Steel"])
        values = collect_inputs(
            seller="MoveInSync",
            offering="commute automation",
            input_fn=answers,
            out=self.out,
        )
        self.assertEqual(answers.asked, 1)
        self.assertEqual(values["company"], "Tata Steel")

    def test_nothing_is_asked_when_everything_is_supplied(self):
        answers = Answers([])
        values = collect_inputs(
            seller="MoveInSync",
            offering="commute automation",
            company="Tata Steel",
            input_fn=answers,
            out=self.out,
        )
        self.assertEqual(answers.asked, 0)
        self.assertEqual(values["company"], "Tata Steel")

    def test_remembered_values_become_defaults(self):
        answers = Answers(["", "", "Tata Steel"])
        values = collect_inputs(
            defaults={"seller": "MoveInSync", "offering": "commute automation"},
            input_fn=answers,
            out=self.out,
        )
        self.assertEqual(values["seller"], "MoveInSync")
        self.assertEqual(values["offering"], "commute automation")

    def test_target_account_is_never_defaulted_from_history(self):
        answers = Answers(["MoveInSync", "commute automation", "", "Tata Steel"])
        values = collect_inputs(
            defaults={"company": "Old Account"},
            input_fn=answers,
            out=self.out,
        )
        self.assertEqual(values["company"], "Tata Steel")

    def test_industry_defaults_to_auto_detect(self):
        values = collect_inputs(
            input_fn=Answers(["A", "B", "C"]),
            out=self.out,
        )
        self.assertEqual(values["industry"], "")


class StepSelectionTests(unittest.TestCase):
    def test_there_is_one_email_stage(self):
        self.assertIn("emails", STEP_ORDER)
        self.assertNotIn("emails_a", STEP_ORDER)
        self.assertNotIn("emails_b", STEP_ORDER)

    def test_emails_come_after_the_pack_and_before_grading(self):
        self.assertLess(STEP_ORDER.index("pack"), STEP_ORDER.index("emails"))
        self.assertLess(STEP_ORDER.index("emails"), STEP_ORDER.index("grade_messages"))

    def test_the_grader_sees_the_research_pack_before_any_email_is_written(self):
        self.assertLess(
            STEP_ORDER.index("grade_research"), STEP_ORDER.index("emails")
        )

    def test_no_style_flag_is_offered(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["run", "--style", "b"])


class ParserTests(unittest.TestCase):
    def test_bare_invocation_has_no_subcommand(self):
        args = build_parser().parse_args([])
        self.assertIsNone(args.command)

    def test_run_does_not_require_any_flag(self):
        args = build_parser().parse_args(["run"])
        self.assertIsNone(args.seller)
        self.assertIsNone(args.company)

    def test_run_accepts_the_three_inputs(self):
        args = build_parser().parse_args(
            ["run", "--seller", "MoveInSync", "--sells", "commute", "--company", "Tata"]
        )
        self.assertEqual(args.seller, "MoveInSync")
        self.assertEqual(args.offering, "commute")
        self.assertEqual(args.company, "Tata")

    def test_industry_is_optional(self):
        args = build_parser().parse_args(["run", "--company", "Tata"])
        self.assertIsNone(args.industry)

    def test_plain_flag_is_available(self):
        args = build_parser().parse_args(["run", "--plain"])
        self.assertTrue(args.plain)

    def test_view_takes_an_optional_run_directory(self):
        parser = build_parser()
        self.assertIsNone(parser.parse_args(["view"]).run_dir)
        self.assertEqual(parser.parse_args(["view", "runs/x"]).run_dir, "runs/x")

    def test_continue_takes_a_run_directory(self):
        args = build_parser().parse_args(["continue", "runs/tata-steel"])
        self.assertEqual(args.run_dir, "runs/tata-steel")


class RecentSettingsTests(unittest.TestCase):
    def test_roundtrip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "recent.json"
            settings.save_recent({"seller": "MoveInSync"}, path=path)
            self.assertEqual(settings.load_recent(path=path)["seller"], "MoveInSync")

    def test_missing_file_returns_empty(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(settings.load_recent(path=Path(tmp) / "nope.json"), {})

    def test_corrupt_file_returns_empty(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "recent.json"
            path.write_text("{not json")
            self.assertEqual(settings.load_recent(path=path), {})

    def test_only_known_keys_are_stored(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "recent.json"
            settings.save_recent(
                {"seller": "A", "company": "Secret Co", "junk": 1}, path=path
            )
            stored = json.loads(path.read_text())
            self.assertIn("seller", stored)
            self.assertNotIn("company", stored)
            self.assertNotIn("junk", stored)


class RunStateTests(unittest.TestCase):
    def test_offering_survives_a_save_and_load(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "acme"
            state = RunState(
                run_dir=run_dir,
                company="Acme",
                industry="",
                model="sonnet",
                group="",
                date="2026-09-11",
                seller="MoveInSync",
                offering="commute automation",
            )
            state.save()
            loaded = RunState.load(run_dir)
            self.assertEqual(loaded.offering, "commute automation")
            self.assertEqual(loaded.seller, "MoveInSync")

    def test_old_state_files_without_offering_still_load(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "acme"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "run_dir": str(run_dir),
                        "company": "Acme",
                        "industry": "Steel",
                        "style": "a",
                        "model": "sonnet",
                        "group": "",
                        "date": "2026-09-11",
                        "completed": {},
                    }
                )
            )
            loaded = RunState.load(run_dir)
            self.assertEqual(loaded.offering, "")

    def test_unknown_keys_in_state_are_ignored(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "acme"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "run_dir": str(run_dir),
                        "company": "Acme",
                        "industry": "Steel",
                        "style": "a",
                        "model": "sonnet",
                        "group": "",
                        "date": "2026-09-11",
                        "completed": {},
                        "from_a_future_version": True,
                    }
                )
            )
            self.assertEqual(RunState.load(run_dir).company, "Acme")


class PairingTests(unittest.TestCase):
    def setUp(self):
        ui.set_color(False)
        self.out = io.StringIO()

    def test_the_workshop_pairings_are_available(self):
        self.assertEqual(len(pairings.PAIRINGS), 6)
        for pairing in pairings.PAIRINGS:
            self.assertEqual(len(pairing), 3)

    def test_a_pairing_maps_onto_the_three_inputs(self):
        values = pairings.as_values(0)
        self.assertEqual(set(values), {"seller", "offering", "company"})
        self.assertEqual(values["seller"], pairings.PAIRINGS[0][0])
        self.assertEqual(values["company"], pairings.PAIRINGS[0][2])

    def test_choosing_a_number_returns_that_pairing(self):
        values = pairings.choose(input_fn=lambda prompt="": "3", out=self.out)
        self.assertEqual(values["seller"], pairings.PAIRINGS[2][0])

    def test_empty_answer_means_type_your_own(self):
        self.assertIsNone(pairings.choose(input_fn=lambda prompt="": "", out=self.out))

    def test_every_pairing_is_listed(self):
        pairings.choose(input_fn=lambda prompt="": "", out=self.out)
        printed = ui.strip_ansi(self.out.getvalue())
        for seller, _, company in pairings.PAIRINGS:
            self.assertIn(seller, printed)
            self.assertIn(company, printed)

    def test_out_of_range_answer_is_reasked(self):
        answers = ["99", "2"]
        values = pairings.choose(
            input_fn=lambda prompt="": answers.pop(0), out=self.out
        )
        self.assertEqual(values["seller"], pairings.PAIRINGS[1][0])
        self.assertFalse(answers)

    def test_abort_is_passed_through(self):
        def fake(prompt=""):
            raise EOFError()

        with self.assertRaises(ui.InputAborted):
            pairings.choose(input_fn=fake, out=self.out)


if __name__ == "__main__":
    unittest.main()
