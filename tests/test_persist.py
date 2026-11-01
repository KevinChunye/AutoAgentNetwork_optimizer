import subprocess

from autoagentnet.persist import code_version, git_checkpoint


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_checkpoint_commits_on_a_branch_and_refuses_main(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "state").mkdir()
    (tmp_path / "state/ledger.jsonl").write_text("")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state/ledger.jsonl").write_text('{"cost_usd": 1}\n')
    assert git_checkpoint(["state"], "state: test", push=False).startswith("on main")
    git(tmp_path, "checkout", "-q", "-b", "pilot_run")
    assert git_checkpoint(["state"], "state: test", push=False) == "committed"
    assert git_checkpoint(["state"], "state: test", push=False) == "nothing new to checkpoint"


def test_code_version_ignores_what_runs_write(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "pilot_run")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "state").mkdir()
    (tmp_path / "state/ledger.jsonl").write_text("")
    (tmp_path / "prompts.py").write_text("A = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.chdir(tmp_path)
    head = git(tmp_path, "rev-parse", "--short", "HEAD").stdout.strip()
    (tmp_path / "state/ledger.jsonl").write_text('{"cost_usd": 1}\n')
    (tmp_path / "results").mkdir()
    (tmp_path / "results/status.json").write_text("{}")
    assert code_version() == {"commit": head, "dirty": False, "dirty_paths": []}
    (tmp_path / "prompts.py").write_text("A = 2\n")
    assert code_version() == {"commit": head, "dirty": True, "dirty_paths": ["prompts.py"]}


def test_checkpoint_merges_a_remote_commit_and_pushes(tmp_path, monkeypatch):
    """If someone else pushed to the branch, the checkpoint merges it once and pushes again."""
    git(tmp_path, "init", "-q", "--bare", "origin.git")
    for clone in ("a", "b"):
        git(tmp_path, "clone", "-q", "origin.git", clone)
        git(tmp_path / clone, "config", "user.email", "t@example.com")
        git(tmp_path / clone, "config", "user.name", "t")
    a, b = tmp_path / "a", tmp_path / "b"
    git(a, "checkout", "-q", "-b", "pilot_run")
    (a / "state").mkdir()
    (a / "state/ledger.jsonl").write_text("")
    git(a, "add", ".")
    git(a, "commit", "-q", "-m", "init")
    git(a, "push", "-q", "-u", "origin", "pilot_run")
    git(b, "fetch", "-q", "origin")
    git(b, "checkout", "-q", "pilot_run")
    (b / "prices.yaml").write_text("new: 1\n")
    git(b, "add", ".")
    git(b, "commit", "-q", "-m", "Kevin's price row")
    git(b, "push", "-q", "origin", "pilot_run")
    monkeypatch.chdir(a)
    (a / "state/ledger.jsonl").write_text('{"cost_usd": 1}\n')
    assert git_checkpoint(["state"], "state: test") == "committed and pushed"
    assert (a / "prices.yaml").exists()
    log = git(a, "log", "--oneline", "origin/pilot_run").stdout
    assert "state: test" in log and "Kevin's price row" in log


def test_checkpoint_waits_for_the_shared_lock(tmp_path, monkeypatch):
    """Two paid processes may run at once; a checkpoint must wait while another holds the repository's lock."""
    import fcntl
    import threading

    from autoagentnet.persist import checkpoint_lock_path

    git(tmp_path, "init", "-q", "-b", "pilot_run")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "state").mkdir()
    (tmp_path / "state/ledger.jsonl").write_text("")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.chdir(tmp_path)
    assert checkpoint_lock_path().resolve() == (tmp_path / ".git/aan_checkpoint.lock").resolve()
    (tmp_path / "state/ledger.jsonl").write_text('{"cost_usd": 1}\n')
    results = []
    with open(checkpoint_lock_path(), "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        worker = threading.Thread(target=lambda: results.append(git_checkpoint(["state"], "state: test", push=False)))
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive() and results == []   # blocked while the lock is held
        fcntl.flock(held, fcntl.LOCK_UN)
    worker.join(timeout=10)
    assert results == ["committed"]
