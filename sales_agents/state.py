import json
import re
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")

STATE_FILENAME = "state.json"


def slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "run"


@dataclass
class RunState:
    run_dir: Path
    company: str
    industry: str
    model: str
    group: str
    date: str
    seller: str = ""
    offering: str = ""
    completed: dict = field(default_factory=dict)

    def save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["run_dir"] = str(self.run_dir)
        path = self.run_dir / STATE_FILENAME
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    @classmethod
    def load(cls, run_dir: Path) -> "RunState":
        run_dir = Path(run_dir)
        raw = json.loads((run_dir / STATE_FILENAME).read_text())
        raw["run_dir"] = run_dir
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})
