"""Runs one prompt through the `claude` CLI in headless streaming mode and
reports, live, what the model is doing: which searches it runs, which pages it
fetches, how much it is thinking, and what it finally cost."""

import json
import subprocess
import threading
from dataclasses import dataclass

DEFAULT_ALLOWED_TOOLS = ("WebSearch", "WebFetch")
DEFAULT_TIMEOUT = 1800


class ClaudeRunError(RuntimeError):
    pass


class CodexRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class Activity:
    """One thing that happened inside a step, as it happened.

    kind is one of: session, thinking, tool, tool_result, text, done.
    `tokens` is a live counter whose meaning follows the kind (thinking
    tokens, response characters, tool result size)."""

    kind: str
    label: str
    detail: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0


def build_command(*, model, allowed_tools=DEFAULT_ALLOWED_TOOLS, max_budget_usd=None):
    """Headless, streaming, and isolated from local customisation so a run is
    reproducible on any machine."""
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--safe-mode",
        "--model",
        model,
    ]
    if allowed_tools:
        cmd += ["--tools", *allowed_tools, "--allowedTools", *allowed_tools]
    if max_budget_usd:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    return cmd


def build_codex_command(*, model):
    """Headless Codex run with a read-only workspace and no saved session."""
    cmd = [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="never"',
    ]
    if model:
        cmd += ["--model", model]
    return cmd


def _shorten(text, limit=72):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_detail(name, payload):
    if not isinstance(payload, dict):
        return ""
    if name == "WebSearch":
        return _shorten(payload.get("query", ""))
    if name == "WebFetch":
        url = str(payload.get("url", ""))
        for prefix in ("https://", "http://", "www."):
            if url.startswith(prefix):
                url = url[len(prefix) :]
        return _shorten(url)
    for value in payload.values():
        if isinstance(value, str) and value.strip():
            return _shorten(value)
    return ""


def _text_length(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(str(block.get("text", ""))) for block in content
                   if isinstance(block, dict))
    return 0


class StreamParser:
    """Turns `claude --output-format stream-json` lines into Activities and
    collects the totals for the finished call."""

    TEXT_EMIT_EVERY = 200  # response characters between live updates

    def __init__(self):
        self.result_text = None
        self.is_error = False
        self.error_message = ""
        self.model = ""
        self.cost_usd = 0.0
        self.duration_s = 0.0
        self.num_turns = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.thinking_tokens = 0
        self.text_chars = 0
        self.web_searches = 0
        self.web_fetches = 0
        self._tool_names = {}
        self._last_text_emit = 0

    def feed(self, event):
        if not isinstance(event, dict):
            return []
        handler = getattr(self, "_on_" + str(event.get("type", "")), None)
        return handler(event) if handler else []

    # -- event handlers ----------------------------------------------------

    def _on_system(self, event):
        subtype = event.get("subtype")
        if subtype == "init":
            self.model = event.get("model", "")
            return [Activity(kind="session", label="session started", detail=self.model)]
        if subtype == "thinking_tokens":
            self.thinking_tokens = int(event.get("estimated_tokens") or 0)
            return [
                Activity(kind="thinking", label="thinking", tokens=self.thinking_tokens)
            ]
        return []

    def _on_assistant(self, event):
        message = event.get("message") or {}
        activities = []
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                name = block.get("name", "tool")
                self._tool_names[block.get("id")] = name
                if name == "WebSearch":
                    self.web_searches += 1
                elif name == "WebFetch":
                    self.web_fetches += 1
                activities.append(
                    Activity(
                        kind="tool",
                        label=name,
                        detail=_tool_detail(name, block.get("input")),
                    )
                )
            elif block_type == "text":
                self.text_chars = max(self.text_chars, len(block.get("text", "")))
                activities.append(
                    Activity(kind="text", label="writing answer", tokens=self.text_chars)
                )
        return activities

    def _on_user(self, event):
        message = event.get("message") or {}
        activities = []
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            name = self._tool_names.get(block.get("tool_use_id"), "tool")
            activities.append(
                Activity(
                    kind="tool_result",
                    label=name,
                    tokens=_text_length(block.get("content")),
                )
            )
        return activities

    def _on_stream_event(self, event):
        inner = event.get("event") or {}
        if inner.get("type") != "content_block_delta":
            return []
        delta = inner.get("delta") or {}
        if delta.get("type") != "text_delta":
            return []
        self.text_chars += len(delta.get("text", ""))
        if self.text_chars - self._last_text_emit < self.TEXT_EMIT_EVERY:
            return []
        self._last_text_emit = self.text_chars
        return [Activity(kind="text", label="writing answer", tokens=self.text_chars)]

    def _on_result(self, event):
        self.result_text = event.get("result")
        self.is_error = bool(event.get("is_error"))
        self.cost_usd = float(event.get("total_cost_usd") or 0.0)
        self.duration_s = float(event.get("duration_ms") or 0) / 1000.0
        self.num_turns = int(event.get("num_turns") or 0)

        usage = event.get("usage") or {}
        self.input_tokens = int(usage.get("input_tokens") or 0)
        self.output_tokens = int(usage.get("output_tokens") or 0)
        server_tools = usage.get("server_tool_use") or {}
        self.web_searches = max(
            self.web_searches, int(server_tools.get("web_search_requests") or 0)
        )
        self.web_fetches = max(
            self.web_fetches, int(server_tools.get("web_fetch_requests") or 0)
        )

        if self.is_error:
            self.error_message = str(
                event.get("result") or event.get("subtype") or "unknown error"
            )
            return [Activity(kind="error", label="failed", detail=self.error_message)]

        return [
            Activity(
                kind="done",
                label="done",
                detail=f"{self.num_turns} turns",
                tokens=self.output_tokens,
                cost_usd=self.cost_usd,
                duration_s=self.duration_s,
            )
        ]


class CodexStreamParser:
    """Collects the final answer from `codex exec --json` events."""

    def __init__(self):
        self.result_text = None
        self.error_message = ""

    def feed(self, event):
        if not isinstance(event, dict):
            return []
        event_type = event.get("type")
        if event_type == "thread.started":
            return [Activity(kind="session", label="session started")]
        if event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") != "agent_message":
                return []
            self.result_text = str(item.get("text") or "")
            return [Activity(kind="done", label="done")]
        if event_type == "turn.failed":
            self.error_message = str(event.get("error") or "Codex turn failed")
            return [Activity(kind="error", label="failed", detail=self.error_message)]
        return []


def _spawn(cmd):
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _send_prompt(process, prompt):
    try:
        process.stdin.write(prompt)
        process.stdin.flush()
        process.stdin.close()
    except (BrokenPipeError, ValueError, OSError):
        pass


def _drain(stream, sink):
    try:
        sink.append(stream.read() if stream else "")
    except (ValueError, OSError):
        sink.append("")


def run_claude(
    prompt,
    *,
    model="sonnet",
    allowed_tools=DEFAULT_ALLOWED_TOOLS,
    timeout=DEFAULT_TIMEOUT,
    max_budget_usd=None,
    on_activity=None,
    spawn=None,
):
    """Run one prompt and return the model's final text.

    `on_activity` is called with an Activity for everything the model does
    while the call is in flight."""
    cmd = build_command(
        model=model, allowed_tools=allowed_tools, max_budget_usd=max_budget_usd
    )
    spawn = spawn or _spawn

    try:
        process = spawn(cmd)
    except FileNotFoundError as exc:
        raise ClaudeRunError(
            "`claude` CLI not found on PATH. Install Claude Code and log in first."
        ) from exc

    parser = StreamParser()
    stderr_sink = []
    timed_out = threading.Event()

    threading.Thread(target=_send_prompt, args=(process, prompt), daemon=True).start()
    stderr_reader = threading.Thread(
        target=_drain, args=(process.stderr, stderr_sink), daemon=True
    )
    stderr_reader.start()

    def _expire():
        timed_out.set()
        try:
            process.kill()
        except Exception:
            pass

    watchdog = threading.Timer(timeout, _expire)
    watchdog.daemon = True
    watchdog.start()

    try:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            for activity in parser.feed(event):
                if on_activity:
                    on_activity(activity)
        returncode = _wait(process)
    except BaseException:  # Ctrl-C included: never leave the child running
        try:
            process.kill()
        except Exception:
            pass
        raise
    finally:
        watchdog.cancel()
        stderr_reader.join(timeout=1.0)

    stderr_text = (stderr_sink[0] if stderr_sink else "").strip()

    if timed_out.is_set():
        raise ClaudeRunError(f"claude call timed out after {timeout}s")
    if parser.is_error:
        raise ClaudeRunError(f"claude reported an error: {parser.error_message}")
    if returncode not in (0, None):
        detail = stderr_text or "no stderr output"
        raise ClaudeRunError(f"claude exited {returncode}: {detail}")
    if not parser.result_text:
        detail = stderr_text or "no result message in the stream"
        raise ClaudeRunError(f"claude returned no output: {detail}")

    return parser.result_text.strip()


def run_codex(
    prompt,
    *,
    model="gpt-5.6-terra",
    timeout=DEFAULT_TIMEOUT,
    on_activity=None,
    spawn=None,
):
    """Run one prompt through Codex and return its final agent message."""
    cmd = build_codex_command(model=model) + [prompt]
    spawn = spawn or _spawn

    try:
        process = spawn(cmd)
    except FileNotFoundError as exc:
        raise CodexRunError(
            "`codex` CLI not found on PATH. Install Codex and sign in first."
        ) from exc

    try:
        process.stdin.close()
    except (AttributeError, ValueError, OSError):
        pass

    parser = CodexStreamParser()
    stderr_sink = []
    timed_out = threading.Event()
    stderr_reader = threading.Thread(
        target=_drain, args=(process.stderr, stderr_sink), daemon=True
    )
    stderr_reader.start()

    def _expire():
        timed_out.set()
        try:
            process.kill()
        except Exception:
            pass

    watchdog = threading.Timer(timeout, _expire)
    watchdog.daemon = True
    watchdog.start()

    try:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            for activity in parser.feed(event):
                if on_activity:
                    on_activity(activity)
        returncode = _wait(process)
    except BaseException:
        try:
            process.kill()
        except Exception:
            pass
        raise
    finally:
        watchdog.cancel()
        stderr_reader.join(timeout=1.0)

    stderr_text = (stderr_sink[0] if stderr_sink else "").strip()
    if timed_out.is_set():
        raise CodexRunError(f"Codex call timed out after {timeout}s")
    if parser.error_message:
        raise CodexRunError(f"Codex reported an error: {parser.error_message}")
    if returncode not in (0, None):
        raise CodexRunError(f"Codex exited {returncode}: {stderr_text or 'no stderr output'}")
    if not parser.result_text:
        raise CodexRunError(f"Codex returned no output: {stderr_text or 'no agent message'}")
    return parser.result_text.strip()


def _wait(process):
    try:
        return process.wait(timeout=30)
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        try:
            process.kill()
        except Exception:
            pass
        raise ClaudeRunError("claude did not exit after the stream closed") from exc
