"""Remembers the few answers that stay the same between runs, so the wizard
can offer them as defaults. Never stores anything about a target account."""

import json
import os
from pathlib import Path

REMEMBERED_KEYS = ("seller", "offering", "model")


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "sales-agents" / "recent.json"


def load_recent(path=None) -> dict:
    path = Path(path or default_path())
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: str(raw[key]) for key in REMEMBERED_KEYS if raw.get(key)}


def save_recent(values: dict, path=None) -> None:
    path = Path(path or default_path())
    payload = {key: values[key] for key in REMEMBERED_KEYS if values.get(key)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    except OSError:  # a read-only home should never fail a run
        pass
