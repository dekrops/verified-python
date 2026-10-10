"""Work-unit identity: which unit of work a claim is about.

A unit is identified by its tenant, a scope, an operation and the values of
the claim inputs the scope names. The identity stays the same across contract
versions, so that a new contract version is not a way to count the same work
twice. Computed by the shared Rust crate ``verified-work-unit``.

This SDK computes identities and nullifiers. It does not, and cannot, say
whether a unit was already billed or settled: that needs shared state with a
first-write-wins rule, which belongs to whoever settles.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from verified import _bridge
from verified.canonical import Digest

__all__ = ["WorkUnit", "WorkUnitScope", "work_unit"]


@dataclass(frozen=True, slots=True)
class WorkUnitScope:
    """What counts as one unit of work, as the parties declared it."""

    scope: str
    """The name of the line of work."""
    operation: str
    """What is done to the object. Different operations are different units."""
    identity: tuple[str, ...]
    """The claim inputs that identify one unit, in order."""

    def to_wire(self) -> dict[str, object]:
        return {"scope": self.scope, "operation": self.operation, "identity": list(self.identity)}


@dataclass(frozen=True, slots=True)
class WorkUnit:
    """The identity of one unit of work and, given the tenant's key, its nullifier."""

    version: str
    identity: str
    """The identity's canonical text. **Plaintext**: it discloses the unit.
    Share :attr:`nullifier` where the unit itself should stay private."""
    nullifier: str | None
    """``hmac-sha-256:<hex>``. Equal nullifiers under one key are the same unit."""
    key_commitment: Digest | None
    """Pins the tenant's key without revealing it."""


def work_unit(
    *,
    tenant: str,
    scope: WorkUnitScope,
    inputs: Mapping[str, str | bool] | None = None,
    values: Sequence[str | bool] | None = None,
    key: bytes | None = None,
) -> WorkUnit:
    """The work unit a claim is about.

    Give the claim's ``inputs`` (the scope picks the identifying ones) or the
    identifying ``values`` in the scope's order. Values are compared exactly:
    ``INV-01001`` and ``INV-1001`` are different units.

    ``key`` is the tenant's 32-byte nullifier key. Generating, storing and
    rotating it is the caller's; whoever holds it can compute the nullifier
    of any guessed unit, and rotating it changes every nullifier.
    """
    if (inputs is None) == (values is None):
        raise ValueError("give exactly one of inputs and values")
    result = _bridge.call_json(
        "work_unit",
        tenant,
        _bridge.dumps(scope.to_wire(), where="scope"),
        values=None if values is None else _bridge.dumps(list(values), where="values"),
        inputs=None if inputs is None else _bridge.dumps(inputs, where="inputs"),
        key=key,
    )
    nullifier = result.get("nullifier")
    commitment = result.get("keyCommitment")
    return WorkUnit(
        version=result["version"],
        identity=result["identity"],
        nullifier=None if nullifier is None else f"{nullifier['algorithm']}:{nullifier['hex']}",
        key_commitment=None if commitment is None else Digest.from_wire(commitment),
    )
