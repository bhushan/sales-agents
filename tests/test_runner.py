import io
import json
import unittest

from sales_agents.runner import (
    Activity,
    ClaudeRunError,
    StreamParser,
    build_command,
    run_claude,
)


def assistant(*blocks, usage=None):
    return {
        "type": "assistant",
        "message": {
            "model": "claude-sonnet-5",
            "content": list(blocks),
            "usage": usage or {"input_tokens": 10, "output_tokens": 20},
        },
    }


def result_event(**overrides):
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "FINAL ANSWER",
        "duration_ms": 4200,
        "total_cost_usd": 0.1234,
        "num_turns": 3,
        "usage": {
            "input_tokens": 9,
            "output_tokens": 780,
            "cache_read_input_tokens": 100,
            "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 1},
        },
    }
    payload.update(overrides)
    return payload


class BuildCommandTests(unittest.TestCase):
    def test_uses_headless_streaming_json_mode(self):
        cmd = build_command(model="sonnet", allowed_tools=("WebSearch", "WebFetch"))
        self.assertEqual(cmd[0], "claude")
        self.assertIn("-p", cmd)
        self.assertIn("--output-format", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--verbose", cmd)

    def test_passes_the_model(self):
        cmd = build_command(model="opus", allowed_tools=())
        self.assertIn("--model", cmd)
        self.assertIn("opus", cmd)

    def test_restricts_tools_to_the_allowed_set(self):
        cmd = build_command(model="sonnet", allowed_tools=("WebSearch", "WebFetch"))
        self.assertIn("--tools", cmd)
        self.assertIn("--allowedTools", cmd)
        self.assertIn("WebSearch", cmd)
        self.assertIn("WebFetch", cmd)

    def test_isolates_the_run_from_local_mcp_and_session_history(self):
        cmd = build_command(model="sonnet", allowed_tools=())
        self.assertIn("--strict-mcp-config", cmd)
        self.assertIn("--no-session-persistence", cmd)

    def test_budget_cap_is_passed_when_set(self):
        cmd = build_command(model="sonnet", allowed_tools=(), max_budget_usd=2.5)
        self.assertIn("--max-budget-usd", cmd)
        self.assertIn("2.5", cmd)

    def test_budget_cap_is_omitted_when_unset(self):
        self.assertNotIn("--max-budget-usd", build_command(model="sonnet", allowed_tools=()))


class StreamParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = StreamParser()

    def test_init_event_reports_the_model(self):
        acts = self.parser.feed({"type": "system", "subtype": "init", "model": "claude-sonnet-5"})
        self.assertEqual(acts[0].kind, "session")
        self.assertIn("claude-sonnet-5", acts[0].detail)

    def test_thinking_tokens_event_carries_a_live_count(self):
        acts = self.parser.feed(
            {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 136}
        )
        self.assertEqual(acts[0].kind, "thinking")
        self.assertEqual(acts[0].tokens, 136)

    def test_web_search_tool_use_shows_the_query(self):
        acts = self.parser.feed(
            assistant(
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "WebSearch",
                    "input": {"query": "Tata Steel head of procurement"},
                }
            )
        )
        self.assertEqual(acts[0].kind, "tool")
        self.assertEqual(acts[0].label, "WebSearch")
        self.assertIn("Tata Steel head of procurement", acts[0].detail)

    def test_web_fetch_tool_use_shows_the_url(self):
        acts = self.parser.feed(
            assistant(
                {
                    "type": "tool_use",
                    "id": "toolu_2",
                    "name": "WebFetch",
                    "input": {"url": "https://www.reuters.com/markets/steel-2026"},
                }
            )
        )
        self.assertEqual(acts[0].label, "WebFetch")
        self.assertIn("reuters.com", acts[0].detail)

    def test_unknown_tool_still_reports_its_name(self):
        acts = self.parser.feed(
            assistant({"type": "tool_use", "id": "t3", "name": "Mystery", "input": {}})
        )
        self.assertEqual(acts[0].label, "Mystery")

    def test_tool_result_is_attributed_to_the_tool_that_ran(self):
        self.parser.feed(
            assistant(
                {
                    "type": "tool_use",
                    "id": "toolu_9",
                    "name": "WebSearch",
                    "input": {"query": "q"},
                }
            )
        )
        acts = self.parser.feed(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_9",
                            "content": [{"type": "text", "text": "x" * 1200}],
                        }
                    ]
                },
            }
        )
        self.assertEqual(acts[0].kind, "tool_result")
        self.assertEqual(acts[0].label, "WebSearch")

    def test_assistant_text_block_reports_writing(self):
        acts = self.parser.feed(assistant({"type": "text", "text": "## Industry"}))
        self.assertEqual(acts[0].kind, "text")

    def test_thinking_block_is_not_reported_as_text(self):
        acts = self.parser.feed(assistant({"type": "thinking", "thinking": "hmm"}))
        self.assertFalse([a for a in acts if a.kind == "text"])

    def test_text_deltas_accumulate_and_emit_throttled_updates(self):
        emitted = []
        for _ in range(10):
            emitted += self.parser.feed(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "y" * 100},
                    },
                }
            )
        self.assertTrue(emitted)
        self.assertTrue(all(a.kind == "text" for a in emitted))
        self.assertLess(len(emitted), 10)
        self.assertEqual(emitted[-1].tokens, self.parser.text_chars)

    def test_result_event_captures_text_cost_and_usage(self):
        acts = self.parser.feed(result_event())
        self.assertEqual(self.parser.result_text, "FINAL ANSWER")
        self.assertAlmostEqual(self.parser.cost_usd, 0.1234)
        self.assertAlmostEqual(self.parser.duration_s, 4.2)
        self.assertEqual(self.parser.output_tokens, 780)
        self.assertEqual(self.parser.web_searches, 2)
        self.assertEqual(self.parser.web_fetches, 1)
        self.assertEqual(acts[-1].kind, "done")

    def test_error_result_is_recorded(self):
        self.parser.feed(
            result_event(is_error=True, subtype="error_during_execution", result="nope")
        )
        self.assertTrue(self.parser.is_error)
        self.assertIn("nope", self.parser.error_message)

    def test_unknown_event_types_are_ignored(self):
        self.assertEqual(self.parser.feed({"type": "rate_limit_event"}), [])
        self.assertEqual(self.parser.feed({"type": "brand_new_thing"}), [])


class Sink(io.StringIO):
    """A stdin stand-in that survives the close() a real pipe needs."""

    def close(self):
        pass


class FakeProcess:
    def __init__(self, lines, returncode=0, stderr=""):
        self.stdin = Sink()
        self.stdout = iter(lines)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.killed = False

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def spawn_returning(proc):
    def spawn(cmd):
        spawn.cmd = cmd
        return proc

    return spawn


def jsonl(*events):
    return [json.dumps(e) + "\n" for e in events]


class RunClaudeTests(unittest.TestCase):
    def test_returns_the_final_result_text(self):
        proc = FakeProcess(jsonl(result_event()))
        out = run_claude("hello", model="sonnet", spawn=spawn_returning(proc))
        self.assertEqual(out, "FINAL ANSWER")

    def test_sends_the_prompt_on_stdin(self):
        proc = FakeProcess(jsonl(result_event()))
        run_claude("the prompt", model="sonnet", spawn=spawn_returning(proc))
        self.assertEqual(proc.stdin.getvalue(), "the prompt")

    def test_streams_activities_to_the_callback(self):
        seen = []
        events = jsonl(
            {"type": "system", "subtype": "init", "model": "claude-sonnet-5"},
            assistant(
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "WebSearch",
                    "input": {"query": "steel"},
                }
            ),
            result_event(),
        )
        proc = FakeProcess(events)
        run_claude(
            "hello",
            model="sonnet",
            spawn=spawn_returning(proc),
            on_activity=seen.append,
        )
        kinds = [a.kind for a in seen]
        self.assertEqual(kinds[0], "session")
        self.assertIn("tool", kinds)
        self.assertEqual(kinds[-1], "done")

    def test_malformed_lines_do_not_break_the_stream(self):
        lines = ["not json\n", "\n"] + jsonl(result_event())
        proc = FakeProcess(lines)
        self.assertEqual(
            run_claude("hello", model="sonnet", spawn=spawn_returning(proc)),
            "FINAL ANSWER",
        )

    def test_nonzero_exit_raises_with_stderr(self):
        proc = FakeProcess([], returncode=1, stderr="boom")
        with self.assertRaises(ClaudeRunError) as ctx:
            run_claude("hello", model="sonnet", spawn=spawn_returning(proc))
        self.assertIn("boom", str(ctx.exception))

    def test_error_result_raises(self):
        proc = FakeProcess(jsonl(result_event(is_error=True, result="model refused")))
        with self.assertRaises(ClaudeRunError) as ctx:
            run_claude("hello", model="sonnet", spawn=spawn_returning(proc))
        self.assertIn("model refused", str(ctx.exception))

    def test_empty_stream_raises(self):
        proc = FakeProcess([])
        with self.assertRaises(ClaudeRunError):
            run_claude("hello", model="sonnet", spawn=spawn_returning(proc))

    def test_missing_cli_raises_a_friendly_error(self):
        def spawn(cmd):
            raise FileNotFoundError()

        with self.assertRaises(ClaudeRunError) as ctx:
            run_claude("hello", model="sonnet", spawn=spawn)
        self.assertIn("claude", str(ctx.exception).lower())

    def test_timeout_kills_the_process_and_raises(self):
        proc = FakeProcess(jsonl(result_event()))

        def slow_iter():
            raise TimeoutError()

        proc.stdout = iter([])
        proc.wait = lambda timeout=None: (_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(ClaudeRunError):
            run_claude("hello", model="sonnet", spawn=spawn_returning(proc), timeout=1)


class ActivityTests(unittest.TestCase):
    def test_activity_defaults_are_safe_for_display(self):
        act = Activity(kind="tool", label="WebSearch")
        self.assertEqual(act.detail, "")
        self.assertEqual(act.tokens, 0)


if __name__ == "__main__":
    unittest.main()
