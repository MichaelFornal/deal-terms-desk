import json
import os
from pathlib import Path


class Ledger:
    """Append-only JSONL keyed by url. A torn last line (a kill mid-write) is ignored."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._recs: dict[str, dict] = {}
        if self.path.exists():
            data = self.path.read_text(encoding="utf-8")
            lines = data.split("\n")
            if not data.endswith("\n"):
                lines = lines[:-1]
            for line in lines:
                if line.strip():
                    rec = json.loads(line)
                    self._recs[rec["url"]] = rec

    def get(self, url: str) -> dict | None:
        return self._recs.get(url)

    def put(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._recs[rec["url"]] = rec
