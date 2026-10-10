"""Tools for building packages that should be refused. Test code only."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from verified import Digest, WorkPackage, canonicalize

PATHS = [
    "claim.json",
    "contract.json",
    "decision.json",
    "evidence/bodies.json",
    "evidence/statements.json",
    "inputs.json",
]


def edit(package: WorkPackage, change: Callable[[dict[str, Any]], None]) -> WorkPackage:
    """Changes a package and leaves its digests as they were."""
    value = json.loads(package.text)
    change(value)
    return WorkPackage(canonicalize(value))


def component(value: dict[str, Any], path: str) -> Any:
    return value["files"][PATHS.index(path)]["content"]


def reseal(value: dict[str, Any]) -> None:
    """Recomputes every digest, the commitment and the identifier, as someone
    who altered a package and wanted to hide it would."""
    for entry, file in zip(value["manifest"]["files"], value["files"], strict=True):
        entry["hash"] = Digest.of_json(file["content"]).to_wire()
    commitment = Digest.of_json(value["manifest"])
    value["packageCommitment"] = commitment.to_wire()
    value["packageId"] = f"wvp:sha-256:{commitment.hex}"


def edit_and_reseal(package: WorkPackage, change: Callable[[dict[str, Any]], None]) -> WorkPackage:
    def both(value: dict[str, Any]) -> None:
        change(value)
        reseal(value)

    return edit(package, both)
