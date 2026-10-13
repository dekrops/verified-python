"""A recomputed authorization, replayed (a draft, and not part of the
protocol).

A work contract often requires that someone was authorized. A relying party
that trusts neither a directory's flat list nor the enforcing system's word
can hold the policy set and the entity records as signed evidence, and the
decision follows from them by the `Cedar <https://www.cedarpolicy.com/>`_
policy language. A *replay package* carries a contract, signed statements
and the result a first verifier arrived at. :func:`replay_derivation`
computes that result again from the evidence, under *your* trust registry,
and compares.

What a replay establishes is narrow:

- ``REPRODUCED`` means this verifier computed the presented result again
  from the statements. It does not mean the action was authorized: look at
  each authorization's outcome and at the contract's decision.
- Nothing presented is believed. A result with consistent digests that the
  evidence does not yield is ``NOT_REPRODUCED``, with the member that
  differs.
- ``engine_decision`` is what Cedar itself returned. It is never the
  outcome: Cedar answers ``Allow`` when it has skipped a policy that failed
  to evaluate, and the outcome is then ``UNDETERMINED``.
- No source is shown to have told the truth.

This is proposed for the protocol as RFC 0005 and is not part of it. The
formats say ``experimental``; this function may change or be removed.

Every rule is in the shared Rust replayer (``verified-derivation``).
Nothing in this module prepares, decides or compares anything.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn

from verified import _bridge
from verified.canonical import Digest
from verified.trust import TrustRegistry

__all__ = [
    "AuthorizationOutcome",
    "AuthorizationReplay",
    "BoundDerivation",
    "DerivationReplay",
    "ReplayOutcome",
    "RequirementBinding",
    "replay_derivation",
]


class ReplayOutcome(StrEnum):
    """Whether the presented result was computed again."""

    REPRODUCED = "reproduced"
    """Every commitment was computed again and is the one presented. Not a
    statement that anything was authorized."""
    NOT_REPRODUCED = "not-reproduced"
    """A stage did not hold: see ``stage``, ``code`` and ``detail``."""


class AuthorizationOutcome(StrEnum):
    """What the evidence yields for one work event."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    UNDETERMINED = "UNDETERMINED"
    """Not a denial. Nothing is established: see ``reasons``."""


def _digest(raw: Mapping[str, Any]) -> Digest:
    return Digest(raw["hex"], raw["algorithm"])


@dataclass(frozen=True, slots=True)
class AuthorizationReplay:
    """One authorization, recomputed for one work event."""

    correlation: str
    """The work event's identifier."""
    outcome: AuthorizationOutcome
    reasons: tuple[str, ...]
    """The failed guards. Empty for a definite outcome."""
    engine_decision: str | None
    """What Cedar itself returned, ``Allow`` or ``Deny``; ``None`` if a guard
    failed first and it was never asked. A diagnostic, never the outcome."""
    commitment: Digest
    diagnostics: Mapping[str, Any]
    """This verifier's own account: its engine and its messages."""


@dataclass(frozen=True, slots=True)
class BoundDerivation:
    """A derivation a requirement depends on."""

    correlation: str
    commitment: Digest
    record: str | None
    """The identifier of the record it yielded; ``None`` if it yielded none."""


@dataclass(frozen=True, slots=True)
class RequirementBinding:
    """A contract requirement and the derivations it depends on, read from
    the contract. It names every derivation the requirement can see, not the
    record that decided it."""

    requirement: str
    method: str
    method_version: str
    derivations: tuple[BoundDerivation, ...]


@dataclass(frozen=True, slots=True)
class DerivationReplay:
    """What a replay arrived at. This object has no truth value."""

    outcome: ReplayOutcome
    commitment: Digest | None
    """The commitment of the derived evaluation, when reproduced."""
    decision: str | None
    """The contract's decision, when reproduced: ``SUPPORTED``,
    ``CONTRADICTED`` or ``UNDETERMINED``."""
    authorizations: tuple[AuthorizationReplay, ...]
    bindings: tuple[RequirementBinding, ...]
    stage: str | None
    """Where a replay stopped: ``PACKAGE``, ``EVIDENCE``, ``CONTRACT``,
    ``PROFILE``, ``DERIVATION`` or ``EVALUATION``."""
    code: str | None
    detail: tuple[str, ...]
    """Each member that differs, with the presented and the computed value."""
    raw: Mapping[str, Any]
    """The report exactly as the shared replayer states it."""

    draft: bool = True
    """Always ``True``: this is not a WVP verification and not a Work Record."""

    def __bool__(self) -> NoReturn:
        raise TypeError(
            "a DerivationReplay has no truth value: look at its outcome, at each "
            "authorization and at the contract's decision"
        )

    @classmethod
    def _from_raw(cls, raw: Mapping[str, Any]) -> DerivationReplay:
        return cls(
            outcome=ReplayOutcome(raw["outcome"]),
            commitment=_digest(raw["commitment"]) if "commitment" in raw else None,
            decision=raw.get("decision"),
            authorizations=tuple(
                AuthorizationReplay(
                    correlation=item["correlation"],
                    outcome=AuthorizationOutcome(item["outcome"]),
                    reasons=tuple(item["reasons"]),
                    engine_decision=item["engineDecision"],
                    commitment=_digest(item["commitment"]),
                    diagnostics=item["diagnostics"],
                )
                for item in raw.get("authorization", ())
            ),
            bindings=tuple(
                RequirementBinding(
                    requirement=item["requirement"],
                    method=item["method"]["name"],
                    method_version=item["method"]["version"],
                    derivations=tuple(
                        BoundDerivation(
                            correlation=bound["correlation"],
                            commitment=_digest(bound["commitment"]),
                            record=bound["record"],
                        )
                        for bound in item["derivations"]
                    ),
                )
                for item in raw.get("bindings", ())
            ),
            stage=raw.get("stage"),
            code=raw.get("code"),
            detail=tuple(raw.get("detail", ())),
            raw=raw,
        )


def replay_derivation(package: Mapping[str, Any], trust: TrustRegistry) -> DerivationReplay:
    """Computes a presented recomputed authorization again from its evidence.

    ``package`` is a replay package: a contract, a profile, signed statements
    with their bodies, and the result a first verifier presented. ``trust``
    is your registry: a statement is read only from a key it trusts for the
    statement's source, and the registry is never taken from the package.

    Every statement is authenticated, the authorization is prepared again
    from the statements and decided by the Cedar policy engine, the contract
    is evaluated again, and only then is the result compared with the one
    presented.

    Offline. The time and memory the engine spends are not bounded: do not
    call this on packages from parties you would not let run code.
    """
    if not isinstance(trust, TrustRegistry):
        raise TypeError("trust is a TrustRegistry")
    raw = _bridge.call_json(
        "replay_derivation",
        _bridge.dumps(package, where="package"),
        trust.to_json(),
    )
    return DerivationReplay._from_raw(raw)
