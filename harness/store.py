"""Append-only JSONL record store used for checkpointing experiment runs."""
from __future__ import annotations

import json
import threading
from pathlib import Path


class JsonlStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def append(self, rec: dict) -> None:
        with self._lock, self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def append_many(self, recs: list[dict]) -> None:
        with self._lock, self.path.open("a") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
