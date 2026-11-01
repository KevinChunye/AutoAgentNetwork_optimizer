"""The sealed 70/30 item split of T5.

Terms:
  fit items      70% of the testbed's items: the factor model is fitted on them, and every analysis choice not fixed
                 in the prereg is made on them.
  held-out items the other 30%: T5 is scored on them once, after the stage-1 run.
  seal           before the stage-1 run, `seal` draws the split with a fresh random key (so nobody could have chosen
                 it), writes both id lists and a MANIFEST with their sha256 hashes, and the files are committed. The
                 key is written too: it proves the split was not hand-picked, and the hashes prove it did not change.
  unseal         `heldout(unseal=True)` returns the held-out ids and appends a line to UNSEAL_LOG; a second unseal
                 refuses unless `again=True` (which is logged too), so "read once" is enforced and auditable.
T1-T4 fit nothing (their rules are fixed in the prereg), so they use every item.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEALED = ROOT / "research/v4/testbed/sealed"
FIT_SHARE = 0.7


def digest(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def seal(items: list[str], folder: Path = SEALED, key: str | None = None) -> dict:
    folder = Path(folder)
    if (folder / "MANIFEST.md").exists():
        raise FileExistsError(f"{folder} is already sealed; a new split needs a new folder and a prereg note")
    key = key or secrets.token_hex(16)
    order = sorted(set(items), key=lambda i: hashlib.sha256(f"{key}:{i}".encode()).hexdigest())
    cut = int(round(FIT_SHARE * len(order)))
    fit, held = sorted(order[:cut]), sorted(order[cut:])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fit.txt").write_text("\n".join(fit) + "\n")
    (folder / "heldout.txt").write_text("\n".join(held) + "\n")
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (folder / "MANIFEST.md").write_text(
        f"# Sealed T5 split\n\nSealed {when}. Key `{key}` (split = first {cut} of the items sorted by "
        f"sha256(key:id)).\n\n| file | n | sha256 of sorted ids |\n|---|---|---|\n"
        f"| fit.txt | {len(fit)} | `{digest(fit)}` |\n| heldout.txt | {len(held)} | `{digest(held)}` |\n")
    return {"fit": len(fit), "heldout": len(held), "key": key}


def _ids(path: Path) -> list[str]:
    return [x for x in Path(path).read_text().splitlines() if x]


def check(folder: Path = SEALED) -> None:
    """Raise if a list no longer matches its manifest hash."""
    manifest = (Path(folder) / "MANIFEST.md").read_text()
    for name in ("fit.txt", "heldout.txt"):
        if f"`{digest(_ids(Path(folder) / name))}`" not in manifest:
            raise ValueError(f"{name} does not match its MANIFEST hash")


def fit_items(folder: Path = SEALED) -> list[str]:
    check(folder)
    return _ids(Path(folder) / "fit.txt")


def heldout(folder: Path = SEALED, unseal: bool = False, again: bool = False, reason: str = "") -> list[str]:
    folder = Path(folder)
    check(folder)
    if not unseal:
        raise PermissionError("the held-out items are sealed; call heldout(unseal=True, reason=...) once, after stage 1")
    log = folder / "UNSEAL_LOG.md"
    if log.exists() and not again:
        raise PermissionError(f"already unsealed (see {log}); pass again=True to read it a second time, which is logged")
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with log.open("a") as f:
        f.write(f"- {when}: unsealed{' AGAIN' if log.exists() and again else ''}. {reason}\n")
    return _ids(folder / "heldout.txt")
