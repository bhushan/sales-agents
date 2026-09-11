import subprocess
import unittest
from unittest.mock import patch, MagicMock

from sales_agents.runner import run_claude, ClaudeRunError


class RunClaudeTests(unittest.TestCase):
    @patch("sales_agents.runner.subprocess.run")
    def test_builds_expected_command_and_returns_stdout(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="  the answer  \n", stderr="")

        out = run_claude("hello prompt", model="sonnet")

        self.assertEqual(out, "the answer")
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertEqual(cmd[0], "claude")
        self.assertIn("-p", cmd)
        self.assertIn("--output-format", cmd)
        self.assertIn("text", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("sonnet", cmd)
        self.assertIn("--allowedTools", cmd)
        self.assertEqual(kwargs["input"], "hello prompt")

    @patch("sales_agents.runner.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        with self.assertRaises(ClaudeRunError):
            run_claude("hello")

    @patch("sales_agents.runner.subprocess.run", side_effect=FileNotFoundError())
    def test_missing_cli_raises_friendly_error(self, mock_run):
        with self.assertRaises(ClaudeRunError):
            run_claude("hello")

    @patch(
        "sales_agents.runner.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1),
    )
    def test_timeout_raises(self, mock_run):
        with self.assertRaises(ClaudeRunError):
            run_claude("hello", timeout=1)


if __name__ == "__main__":
    unittest.main()
