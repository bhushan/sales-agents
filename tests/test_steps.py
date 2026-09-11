import unittest

from sales_agents.steps import TemplateRenderError, render, STEPS, STEP_ORDER


class RenderTests(unittest.TestCase):
    def test_substitutes_known_placeholders(self):
        template = "Hello {{name}}, you sell {{product}}."
        out = render(template, {"name": "Bhushan", "product": "Procol"})
        self.assertEqual(out, "Hello Bhushan, you sell Procol.")

    def test_missing_placeholder_raises(self):
        with self.assertRaises(TemplateRenderError):
            render("Hello {{name}}", {})

    def test_ignores_unused_values(self):
        out = render("Hello {{name}}", {"name": "X", "unused": "Y"})
        self.assertEqual(out, "Hello X")

    def test_leaves_single_braces_alone(self):
        out = render("table row {a: 1}", {})
        self.assertEqual(out, "table row {a: 1}")


class StepDefinitionTests(unittest.TestCase):
    def test_step_order_matches_registered_steps(self):
        self.assertEqual(set(STEP_ORDER), set(STEPS.keys()))

    def test_expected_steps_present(self):
        for step_id in [
            "icp",
            "industry",
            "account",
            "roles",
            "people",
            "pack",
            "grade_research",
            "emails",
            "linkedin",
            "grade_messages",
        ]:
            self.assertIn(step_id, STEPS)

    def test_each_step_has_a_template_file(self):
        from sales_agents.steps import PROMPTS_DIR

        for step in STEPS.values():
            path = PROMPTS_DIR / step.template
            self.assertTrue(path.exists(), f"missing template for {step.id}: {path}")

    def test_no_prompt_file_is_left_behind(self):
        """A prompt no step points at is a prompt nobody edits, and nobody
        notices has gone stale."""
        from sales_agents.steps import PROMPTS_DIR

        used = {step.template for step in STEPS.values()}
        found = {path.name for path in PROMPTS_DIR.glob("*.md")}
        self.assertEqual(found - used, set())


if __name__ == "__main__":
    unittest.main()
