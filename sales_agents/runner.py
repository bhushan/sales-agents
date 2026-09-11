import subprocess

DEFAULT_ALLOWED_TOOLS = ("WebSearch", "WebFetch")
DEFAULT_TIMEOUT = 900


class ClaudeRunError(RuntimeError):
    pass


def run_claude(
    prompt: str,
    *,
    model: str = "sonnet",
    allowed_tools=DEFAULT_ALLOWED_TOOLS,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Run one prompt through the `claude` CLI in headless print mode and
    return the response text. Uses WebSearch/WebFetch only, so it never
    edits files or runs shell commands."""
    cmd = ["claude", "-p", "--output-format", "text", "--model", model]
    if allowed_tools:
        cmd += ["--allowedTools", *allowed_tools]

    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as exc:
        raise ClaudeRunError(
            "`claude` CLI not found on PATH. Install Claude Code first."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ClaudeRunError(f"claude call timed out after {timeout}s") from exc

    if result.returncode != 0:
        raise ClaudeRunError(
            f"claude exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()
