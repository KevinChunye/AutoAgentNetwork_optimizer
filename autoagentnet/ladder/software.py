"""The software ladders of research/v3/program.md: W3 part b (richer markets) and W4 (agent protocol).

A software rung passes when its code downloads, its licence allows research use, it installs in a
scratch environment, and a 2-agent smoke test runs offline with one agent deciding through our
caller (the fake provider, so nothing is spent). The ladder is top-down: the first rung that
passes is chosen and the rungs below it are not tried.

Clones and virtual environments live in AAN_SOFTWARE_DIR (default data/external/v3_software/,
which git ignores). Downloaded code is run only inside its own virtual environment, and only
through the smoke scripts in this package.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import subprocess
from pathlib import Path

from .core import CheckFailed, Net, SoftwareRung, Unreachable

ROOT = Path(__file__).resolve().parents[2]
PYTHON = "python3.13"


def software_dir() -> Path:
    path = Path(os.environ.get("AAN_SOFTWARE_DIR", ROOT / "data/external/v3_software"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def run(cmd: list[str], timeout: int = 900, cwd: Path | None = None) -> str:
    """Run a command; a non-zero exit is a failed check whose evidence is the output's last lines."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CheckFailed(f"{' '.join(cmd[:3])}: {error}") from error
    if done.returncode != 0:
        tail = " | ".join((done.stdout + done.stderr).strip().splitlines()[-4:])
        raise CheckFailed(f"{' '.join(cmd[:3])} exited {done.returncode}: {tail[:400]}")
    return done.stdout


def licence_of(text: str) -> str:
    """The SPDX-style id of a LICENSE file, from its first lines."""
    head = text[:400].lower()
    for marker, spdx in (("mit license", "mit"), ("bsd 3-clause", "bsd-3-clause"), ("apache license", "apache-2.0"),
                         ("bsd 2-clause", "bsd-2-clause")):
        if marker in head:
            return spdx
    return ""


def git_fetch(name: str, url: str) -> tuple[str, str]:
    """Shallow-clone `url` (github.com web pages are blocked in this environment; git is not)."""
    target = software_dir() / name
    if not target.exists():
        try:
            run(["git", "clone", "-q", "--depth", "1", url, str(target)], timeout=600)
        except CheckFailed as error:
            raise Unreachable("github.com", None, f"git clone failed: {error}") from error
    origin = run(["git", "-C", str(target), "remote", "get-url", "origin"]).strip()
    if origin.rstrip("/").removesuffix(".git") != url.removesuffix(".git"):
        raise CheckFailed(f"{target} is a clone of {origin}, not {url}")
    commit = run(["git", "-C", str(target), "rev-parse", "HEAD"]).strip()
    licence = target / "LICENSE"
    return (licence_of(licence.read_text()) if licence.exists() else ""), f"{url.split('github.com/')[1]}@{commit[:8]}"


def pypi_fetch(packages: list[str]) -> tuple[str, str]:
    """Newest release and licence of each package, from PyPI's JSON API."""
    net, licences, versions = Net(), [], []
    for package in packages:
        info = net.json(f"https://pypi.org/pypi/{package}/json")["info"]
        licences.append((info.get("license_expression") or info.get("license") or "").lower())
        versions.append(f"{package} {info['version']}")
    return " / ".join(licences), ", ".join(versions)


def make_venv(name: str, packages: list[str]) -> Path:
    """A scratch virtual environment with `packages`, built with uv (pip when uv is missing)."""
    venv = software_dir() / f"venv_{name}"
    python = venv / "bin/python"
    uv = shutil.which("uv")
    if not python.exists():
        run([uv, "venv", "-q", "-p", PYTHON, str(venv)] if uv else [PYTHON, "-m", "venv", str(venv)])
    run([uv, "pip", "install", "-q", "--python", str(python), *packages] if uv
        else [str(python), "-m", "pip", "install", "-q", *packages], timeout=1800)
    return python


def smoke_script(python: Path, script: str) -> dict:
    """Run one of this package's smoke scripts in a scratch environment; its last line is JSON. It runs
    from the software directory, where ABIDES writes its log/ folder."""
    out = run([str(python), "-I", str(Path(__file__).with_name(script)), str(ROOT)], timeout=600, cwd=software_dir())
    return json.loads(out.strip().splitlines()[-1])


OUR_DEPS = ["pydantic>=2.7", "pyyaml>=6", "httpx>=0.27", "pandas>=2.2"]  # what the smoke scripts import from us

# ---------------------------------------------------------------- W3 part b

ABIDES_URL = "https://github.com/jpmorganchase/abides-jpmc-public"


def install_abides() -> str:
    """ABIDES pins numpy 1.22, pandas 1.2.4, gym 0.18 and ray 1.7 (no wheels for Python 3.11+), so
    abides-core and abides-markets are installed without the pins, on current numpy and pandas."""
    src = software_dir() / "abides"
    python = make_venv("abides", [str(src / "abides-core"), str(src / "abides-markets"), "numpy", "pandas",
                                  "scipy", "tqdm", "coloredlogs", "psutil", *OUR_DEPS])
    run([str(python), "-I", "-c", "import abides_core, abides_markets.agents"])
    return f"abides-core and abides-markets installed in {python.parent.parent.name} without the version pins"


def smoke_abides() -> str:
    result = smoke_script(software_dir() / "venv_abides/bin/python", "smoke_abides.py")
    if result["llm_calls"] < 1 or result["orders_placed"] < 1:
        raise CheckFailed(f"the LLM agent did not trade through our caller: {result}")
    return (f"exchange + ValueAgent + LLM buyer for 30 simulated minutes: {result['llm_calls']} calls through "
            f"MarketCaller (fake provider), {result['orders_placed']} orders accepted, {result['executed']} filled; "
            "rmsc04's noise-agent order sizes need pomegranate 0.14, which does not build on Python 3.13")


MAGENTIC_URL = "https://github.com/microsoft/multi-agent-marketplace"


def install_magentic() -> str:
    python = make_venv("magentic", [str(software_dir() / "magentic/packages/magentic-marketplace"), *OUR_DEPS])
    run([str(python), "-I", "-c", "import magentic_marketplace"])
    return "magentic-marketplace installed"


def smoke_magentic() -> str:
    raise CheckFailed("2-agent smoke test not written: Magentic's agents call their own provider SDKs and its "
                      "platform expects Postgres (docker); an adapter to our caller is S4 work, needed only if ABIDES fails")


def engine_fetch() -> tuple[str, str]:
    commit = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip()
    return "project code", f"autoagentnet/market@{commit[:8]}"


def smoke_engine() -> str:
    """One fake-provider LLM buyer and one zero-intelligence seller for one 8-round period."""
    from ..cache import CallCache
    from ..market.caller import MarketCaller
    from ..market.engine import make_traders, run_session
    from ..market.fake import FakeTraderClient
    from ..market.schedule import Schedule
    from ..market.traders import LLMTrader, ZICTrader, rules_text
    from ..providers.registry import ProviderRegistry
    from ..runtime.local import LocalRuntime

    registry = ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")
    registry.set_client("fake", FakeTraderClient())
    caller = MarketCaller(LocalRuntime(registry), registry, pricebook=None, cache=CallCache(), governor=None,
                          run_id="smoke", market="engine-smoke", condition="fake")
    schedule = Schedule(values=[2.5], costs=[1.5])
    traders = make_traders(schedule, lambda role, rank: "fake" if role == "buyer" else "zic")
    agents = {"B1": LLMTrader(caller, "fake", rules_text(1, 1, 1, 8), 1, 200, 1.0),
              "S1": ZICTrader(random.Random(1), 75, 325)}
    log = asyncio.run(run_session(schedule, traders, agents, seed=1, periods=1, rounds=8))
    if caller.live_calls < 1:
        raise CheckFailed("the LLM buyer made no call")
    return f"1 LLM buyer (fake provider) + 1 ZI-C seller, 1 period: {caller.live_calls} calls, {len(log.turns)} turns"


def w3b_rungs() -> list[SoftwareRung]:
    return [
        SoftwareRung("W3b", 1, "ABIDES (abides-jpmc-public)", ABIDES_URL, "bsd-3-clause",
                     lambda: git_fetch("abides", ABIDES_URL), install_abides, smoke_abides),
        SoftwareRung("W3b", 2, "Magentic Marketplace", MAGENTIC_URL, "mit",
                     lambda: git_fetch("magentic", MAGENTIC_URL), install_magentic, smoke_magentic),
        SoftwareRung("W3b", 3, "Our engine with strategy bots", "autoagentnet/market", "project code",
                     engine_fetch, lambda: "nothing to install (part of autoagentnet)", smoke_engine),
    ]


# ---------------------------------------------------------------- W4


def install_a2a() -> str:
    python = make_venv("a2a", ["a2a-sdk[http-server]", "mcp", "uvicorn", *OUR_DEPS])
    out = run([str(python), "-I", "-c", "import importlib.metadata as m; print(m.version('a2a-sdk'), m.version('mcp'))"])
    sdk, mcp = out.split()
    return f"a2a-sdk {sdk} and mcp {mcp} installed in venv_a2a"


def smoke_a2a() -> str:
    result = smoke_script(software_dir() / "venv_a2a/bin/python", "smoke_a2a.py")
    if not (result["reply_has_caller_text"] and result["reply_has_tool_result"] and result["caller_live_calls"] >= 1):
        raise CheckFailed(f"the A2A exchange did not complete: {result}")
    return ("buyer fetched the seller's Agent Card and sent a message over JSON-RPC/HTTP; the seller answered "
            "through MarketCaller (fake provider) after calling its MCP `reserve` tool")


def not_built(what: str) -> str:
    raise CheckFailed(f"{what} not built: needed only if the rungs above fail (S5 builds it then)")


def w4_rungs() -> list[SoftwareRung]:
    return [
        SoftwareRung("W4", 1, "Official A2A Python SDK + MCP Python SDK", "https://pypi.org/project/a2a-sdk/",
                     "apache-2.0 / mit", lambda: pypi_fetch(["a2a-sdk", "mcp"]), install_a2a, smoke_a2a),
        SoftwareRung("W4", 2, "Minimal JSON-RPC over HTTP (A2A v1.0 spec) + plain function tools",
                     "https://a2a-protocol.org/latest/specification/", "project code",
                     lambda: ("project code", "A2A spec v1.0.0"), lambda: "nothing to install",
                     lambda: not_built("the minimal JSON-RPC agent server")),
        SoftwareRung("W4", 3, "In-process bus with A2A-shaped messages", "autoagentnet", "project code",
                     engine_fetch, lambda: "nothing to install", lambda: not_built("the in-process message bus")),
    ]
