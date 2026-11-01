"""Print (or run) the Maritime CLI commands that put a network's agents on Maritime.

One Maritime agent per network agent (19 machines for dense_3x6):
    python scripts/deploy_maritime.py configs/networks/dense_3x6.yaml
A pool of N generic workers instead (any worker can play any agent):
    python scripts/deploy_maritime.py configs/networks/dense_3x6.yaml --pool 5

API keys are passed as references to your shell ($AAN_ANTHROPIC_API_KEY) and are never
printed. Add --execute to run the commands (needs the `maritime` CLI, logged in).
Then copy the Maritime agent ids into configs/runtime/maritime.yaml.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoagentnet.network.spec import NetworkSpec  # noqa: E402

DEFAULT_REPO = "https://github.com/KevinChunye/AutoAgentNetwork"


def machine_name(prefix: str, *parts: str) -> str:
    return "-".join([prefix, *parts]).replace("_", "-").replace(".", "-").lower()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("network", help="network YAML, e.g. configs/networks/dense_3x6.yaml")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--pool", type=int, default=0, help="deploy N generic workers instead")
    parser.add_argument("--prefix", default="aan")
    parser.add_argument("--secret", action="append", default=None,
                        help="env var to forward (repeatable); default AAN_ANTHROPIC_API_KEY and AAN_OPENAI_API_KEY")
    parser.add_argument("--model-override", default=None, help="sets AAN_MODEL_OVERRIDE in every container")
    parser.add_argument("--execute", action="store_true", help="run the commands instead of printing them")
    args = parser.parse_args()

    network = NetworkSpec.from_yaml(args.network)
    secrets = args.secret or ["AAN_ANTHROPIC_API_KEY", "AAN_OPENAI_API_KEY"]

    machines: list[tuple[str, dict[str, str]]] = []
    if args.pool:
        for i in range(args.pool):
            machines.append((machine_name(args.prefix, "worker", str(i)), {}))
    else:
        for spec in network.all_agents():
            env = {"AAN_NETWORK": args.network, "AAN_AGENT_ID": spec.agent_id}
            machines.append((machine_name(args.prefix, network.name, spec.agent_id), env))

    print(f"# {len(machines)} Maritime agents for network {network.name!r}\n")
    for name, env in machines:
        if args.model_override:
            env = {**env, "AAN_MODEL_OVERRIDE": args.model_override}
        shown = ["maritime", "create", name, "--repo", args.repo, "--branch", args.branch]
        run = list(shown)
        for key, value in env.items():
            shown += ["-e", f"{key}={value}"]
            run += ["-e", f"{key}={value}"]
        for key in secrets:
            shown += ["-e", f'"{key}=${key}"']
            if os.getenv(key):
                run += ["-e", f"{key}={os.environ[key]}"]
        print(" ".join(shown))
        if args.execute:
            subprocess.run(run, check=True)

    print("\n# configs/runtime/maritime.yaml (replace names with Maritime agent ids if the API needs ids)")
    if args.pool:
        print("pool:")
        for name, _ in machines:
            print(f"  - {name}")
    else:
        print("agent_map:")
        for name, env in machines:
            print(f"  {env['AAN_AGENT_ID']}: {name}")


if __name__ == "__main__":
    main()
