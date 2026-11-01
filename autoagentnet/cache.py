"""Call cache: remembers each agent output, keyed by everything that determines it.

The key is the agent's spec (role, prompt, model), its exact input (task and
upstream outputs) and a replicate number. Consequences for the budget:

- Re-running an experiment costs nothing for calls already made.
- A pruned network that shares an upstream sub-network with one already run
  re-uses those calls. Enumerating all 216 configs of the 3x6+1 network costs
  474 calls per task instead of 216 x up to 19.
- A second independent sample of the same call needs a new replicate number.

Storage is a folder of append-only shards tracked in git (state/cache/), because
cloud sessions run in throwaway containers and every cached call was paid for.
The open shard is plain JSONL; ``rotate()`` gzips it and starts a new one, so
each committed file stays small.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any


def make_key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class CallCache:
    def __init__(self, folder: str | Path | None = None, shard_prefix: str | None = None):
        """folder=None keeps the cache in memory (tests and estimates)."""
        self.folder = Path(folder) if folder else None
        self.shard_prefix = shard_prefix or f"shard-{int(time.time())}"
        self._shard_number = 0
        self._data: dict[str, str] = {}
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=True)
            for path in sorted(self.folder.glob("*.jsonl.gz")):
                with gzip.open(path, "rt") as f:
                    self._load_lines(f)
            for path in sorted(self.folder.glob("*.jsonl")):  # shards left open by a crash
                with path.open() as f:
                    self._load_lines(f)

    def _load_lines(self, lines) -> None:
        for line in lines:
            if line.strip():
                entry = json.loads(line)
                self._data[entry["key"]] = entry["value"]

    def _open_shard(self) -> Path:
        return self.folder / f"{self.shard_prefix}-{self._shard_number:03d}.jsonl"

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def put(self, key: str, value: str) -> None:
        self._data[key] = value
        if self.folder:
            with self._open_shard().open("a") as f:
                f.write(json.dumps({"key": key, "value": value}) + "\n")

    def rotate(self) -> None:
        """Compress the open shard and start a new one."""
        if not self.folder:
            return
        shard = self._open_shard()
        if shard.exists():
            with shard.open("rb") as src, gzip.open(shard.with_suffix(".jsonl.gz"), "wb") as dst:
                shutil.copyfileobj(src, dst)
            shard.unlink()
        self._shard_number += 1

    def __len__(self) -> int:
        return len(self._data)
