"""The bill: an append-only ledger of every paid (live) LLM call.

The ledger lives in git (state/ledger.jsonl) because Claude Code cloud sessions
run in throwaway containers: a ledger that vanished with a container would let
the next session believe nothing had been spent. Opening the project ledger
fails if the file is missing; it is never recreated silently.
Calls served from the call cache are free and are not written here.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field


class LedgerMissing(FileNotFoundError):
    pass


class CallRecord(BaseModel):
    run_id: str
    purpose: str = "network"  # "network", "judge", "prompt_optimizer", ...
    network: str = ""
    config_id: str = ""
    task_id: str = ""
    stage: str = ""
    agent_id: str = ""
    account: str  # who is billed, e.g. "anthropic" or "openai"
    provider: str
    model: str
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    stop_reason: str | None = None
    estimated_prompt_tokens: int | None = None  # estimate_tokens() before the call (3 characters per token since v2)
    timestamp: float = Field(default_factory=time.time)


class Ledger:
    def __init__(self, path: str | Path | None = None, must_exist: bool = False):
        """path=None keeps the ledger in memory (tests). must_exist=True refuses to
        start without the file, so a lost ledger can never reset the budget.

        Two paid processes may share one ledger file (Kevin, 2026-11-01). `_offset` is the number of bytes of the
        file this object has already read or written; refresh() reads the complete lines other processes appended
        after it, so each process's governor sees the other's spend before every check. Appends and refreshes hold
        an flock on the file, so a line is never half-read and our own lines are never read twice."""
        self.path = Path(path) if path else None
        self.records: list[CallRecord] = []
        self._spent: dict[str, float] = {}
        self._offset = 0
        if self.path and not self.path.exists():
            if must_exist:
                raise LedgerMissing(
                    f"{self.path} is missing. Pull the repo (it is tracked in git); never recreate it by hand."
                )
        elif self.path:
            self.refresh()

    def _add(self, record: CallRecord) -> None:
        self.records.append(record)
        self._spent[record.account] = self._spent.get(record.account, 0.0) + record.cost_usd

    def _read_new(self, handle) -> int:
        """Add the complete lines after `_offset` from an open, locked handle; return how many."""
        handle.seek(self._offset)
        data = handle.read()
        end = data.rfind(b"\n") + 1   # complete lines; a tail without its newline is read only if it is a whole record
        lines = data[:end].decode().splitlines()
        tail = data[end:].decode().strip()
        if tail:
            try:
                CallRecord.model_validate_json(tail)
                lines.append(tail)
                end = len(data)
            except ValueError:
                pass                  # another process is mid-write; read it next time
        added = 0
        for line in lines:
            if line.strip():
                self._add(CallRecord.model_validate_json(line))
                added += 1
        self._offset += end
        return added

    def refresh(self) -> int:
        """Read what other processes appended since the last read or write; return the number of new records."""
        if not self.path or not self.path.exists():
            return 0
        import fcntl
        with self.path.open("rb") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return self._read_new(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def record(self, record: CallRecord) -> None:
        if not self.path:
            self._add(record)
            return
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+b") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                self._read_new(f)            # other processes' lines first, so the offset stays exact
                size = f.seek(0, 2)
                lead = b""
                if size:
                    f.seek(size - 1)
                    lead = b"" if f.read(1) == b"\n" else b"\n"   # never glue a record onto an unterminated line
                f.write(lead + (record.model_dump_json() + "\n").encode())
                f.flush()
                self._offset = f.tell()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        self._add(record)

    def spent_usd(self, account: str | None = None) -> float:
        if account is None:
            return sum(self._spent.values())
        return self._spent.get(account, 0.0)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.model_dump() for r in self.records])

    def bill(self) -> pd.DataFrame:
        """Spend, tokens and calls by account and model."""
        df = self.to_frame()
        if df.empty:
            return df
        cols = ["cost_usd", "input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens"]
        out = df.groupby(["account", "model"])[cols].sum()
        out["calls"] = df.groupby(["account", "model"]).size()
        return out.sort_values("cost_usd", ascending=False)
