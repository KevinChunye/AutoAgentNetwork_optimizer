"""Commit and push the spend ledger and call cache after each chunk of a run.

Cloud sessions run in containers that can be reclaimed at any time; anything
not pushed is lost, including the record of money already spent. Checkpoints
go to the current branch and never to main.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def checkpoint_lock_path() -> Path:
    """One lock file per repository (in the common git dir), shared by every paid process and by `flock(1)`."""
    common = _git("rev-parse", "--git-common-dir").stdout.strip() or ".git"
    return Path(common) / "aan_checkpoint.lock"


def git_checkpoint(paths: list[str | Path], message: str, push: bool = True) -> str:
    """Stage `paths`, commit if anything changed, push the current branch.
    Returns a short status string; never raises (a failed push is reported).
    The stage-commit-push sequence holds an exclusive lock (flock on checkpoint_lock_path), so two paid processes
    running at once (Kevin, 2026-11-01: one PHOENIX and one Self-or-Social) never collide on git's index or push."""
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        return "not a git repository; state not checkpointed"
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch in ("main", "master"):
        return f"on {branch}; refusing to checkpoint (work on a research branch)"
    import fcntl
    with open(checkpoint_lock_path(), "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            return _commit_and_push(paths, message, push, branch)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _commit_and_push(paths, message, push, branch) -> str:
    _git("add", *[str(p) for p in paths])
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return "nothing new to checkpoint"
    commit = _git("commit", "-m", message)
    if commit.returncode != 0:
        return f"commit failed: {commit.stderr.strip()[:200]}"
    if not push:
        return "committed"
    pushed = _git("push", "-u", "origin", branch)
    if pushed.returncode != 0:
        # Someone else pushed to the branch (e.g. Kevin's config commit): merge it once and push again.
        merged = _git("pull", "--no-rebase", "--no-edit", "origin", branch)
        if merged.returncode == 0:
            pushed = _git("push", "-u", "origin", branch)
    return "committed and pushed" if pushed.returncode == 0 else f"committed; PUSH FAILED: {pushed.stderr.strip()[:200]}"


def code_version() -> dict:
    """The commit a run starts from, and whether the tree differs from it (audit 44). `dirty` counts
    tracked or untracked changes outside state/ and results/, which runs themselves write; `dirty_paths` lists
    them (audit 75: a record of what differed, so a dirty start can be checked against the runtime code)."""
    commit = _git("rev-parse", "--short", "HEAD")
    if commit.returncode != 0:
        return {"commit": "", "dirty": None, "dirty_paths": []}
    changes = _git("status", "--porcelain", "--", ".", ":!state", ":!results").stdout.splitlines()
    paths = [line[3:] for line in changes if line.strip()]
    return {"commit": commit.stdout.strip(), "dirty": bool(paths), "dirty_paths": paths}
