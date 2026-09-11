import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sales_agents.state import RunState, slugify


class SlugifyTests(unittest.TestCase):
    def test_lowercases_and_hyphenates(self):
        self.assertEqual(slugify("Tata Steel Ltd."), "tata-steel-ltd")

    def test_collapses_repeated_separators(self):
        self.assertEqual(slugify("  A   B--C  "), "a-b-c")

    def test_empty_input_falls_back(self):
        self.assertEqual(slugify("   "), "run")


class RunStateTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "acme"
            run_dir.mkdir()
            state = RunState(
                run_dir=run_dir,
                company="Acme",
                industry="Manufacturing",
                model="sonnet",
                group="",
                date="2026-09-11",
                completed={},
            )
            state.completed["icp"] = "00-icp.md"
            state.save()

            loaded = RunState.load(run_dir)
            self.assertEqual(loaded.company, "Acme")
            self.assertEqual(loaded.industry, "Manufacturing")
            self.assertEqual(loaded.date, "2026-09-11")
            self.assertEqual(loaded.completed, {"icp": "00-icp.md"})

    def test_state_file_is_valid_json(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "acme"
            run_dir.mkdir()
            state = RunState(
                run_dir=run_dir,
                company="Acme",
                industry="Manufacturing",
                model="sonnet",
                group="",
                date="2026-09-11",
                completed={},
            )
            state.save()
            raw = json.loads((run_dir / "state.json").read_text())
            self.assertEqual(raw["company"], "Acme")


if __name__ == "__main__":
    unittest.main()
