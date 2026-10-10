"""Offline verification of Work Verification Protocol packages.

Verification is performed by the shared Rust verifier. It reads no network
and no clock, and needs no account. The result keeps apart five things that
are easy to blur:

1. the package is **well formed and unaltered** (:attr:`VerificationResult.integrity`);
2. its evidence is **authentic** under *your* registry
   (:attr:`~VerificationResult.evidence_signatures`,
   :attr:`~VerificationResult.signer_authority`);
3. the verification is **complete** (:attr:`~VerificationResult.verification_status`);
4. the decision was **reproduced** (:attr:`~VerificationResult.decision`);
5. the decision is the **outcome you need** (``require_supported()``).

A complete verification with a reproduced ``CONTRADICTED`` decision is a
successful verification of unsuccessful work. No check, here or anywhere,
establishes that a source told the truth.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, Self

from verified import _bridge
from verified.canonical import Digest
from verified.contracts import WorkContract
from verified.errors import RequirementNotMet, ResourceLimitError
from verified.records import WorkPackage, WorkRecord, _strip_final_line_end
from verified.trust import TrustRegistry

__all__ = [
    "Condition",
    "Conflict",
    "ContractReference",
    "Decision",
    "Expectations",
    "Property",
    "PropertyStatus",
    "Refusal",
    "RequirementValue",
    "StatedContent",
    "StatedStatement",
    "Truth",
    "VerificationResult",
    "VerificationStatus",
    "Verifier",
]

DEFAULT_MAX_BYTES = 32 * 1024 * 1024
"""The largest package examined unless a smaller bound is given: 32 MiB."""


class VerificationStatus(StrEnum):
    """How far a verification got. Not a judgement of the work."""

    COMPLETE = "complete"
    """Every check the protocol defines ran and passed. The decision was
    reproduced; it may be any of the three."""
    INCOMPLETE = "incomplete"
    """Integrity was established and nothing else: no trust registry was
    supplied, so no signature was checked and no decision reproduced."""
    REFUSED = "refused"
    """The package failed a protocol check. :attr:`VerificationResult.refusal`
    names the first one."""


class Decision(StrEnum):
    """What a contract yields from the evidence."""

    SUPPORTED = "SUPPORTED"
    """Every requirement is established by accepted evidence."""
    CONTRADICTED = "CONTRADICTED"
    """At least one requirement is conclusively false under accepted evidence."""
    UNDETERMINED = "UNDETERMINED"
    """The accepted evidence does not settle at least one requirement.
    Missing evidence lands here; it never becomes ``CONTRADICTED`` or
    ``SUPPORTED``."""


class Truth(StrEnum):
    """The value of one requirement (strong Kleene logic)."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class PropertyStatus(StrEnum):
    """Whether one property was established."""

    ESTABLISHED = "established"
    NOT_CHECKED = "not_checked"
    """The checks for the property did not run. Nothing is known about it."""
    ABSENT = "absent"
    """Issuer signature only: the package carries none. Nobody stands behind
    the decision, which was reproduced regardless."""
    NOT_ESTABLISHED = "not_established"
    """Source truthfulness only, always: no check can establish it."""


@dataclass(frozen=True, slots=True)
class Property:
    """One property of a verification, read on its own."""

    name: str
    status: PropertyStatus
    reason: str | None = None

    @property
    def established(self) -> bool:
        return self.status is PropertyStatus.ESTABLISHED


@dataclass(frozen=True, slots=True)
class Refusal:
    """The first protocol check a package failed."""

    code: str
    """The protocol's refusal code. Stable; match on this."""
    detail: str
    """A description for people. Not stable; do not match on it."""


@dataclass(frozen=True, slots=True)
class RequirementValue:
    """The reproduced value of one contract requirement."""

    id: str
    value: Truth


@dataclass(frozen=True, slots=True)
class Conflict:
    """Accepted records that describe one object differently."""

    kind: str
    facts: tuple[str, ...]
    resolved_to: str | None
    """The fact the contract's conflict policy settled on, if it settled."""


@dataclass(frozen=True, slots=True)
class Condition:
    """One condition of the ``wvp-0.1`` ``order-transition`` evaluator."""

    id: str
    holds: bool
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContractReference:
    """Which agreement a ``wvp-0.2`` decision is about."""

    id: str
    version: str
    digest: Digest


@dataclass(frozen=True, slots=True)
class Expectations:
    """What the relying party expects a package to be about (``wvp-0.2``).

    A package verifies against its own claim and contract. That they are the
    ones you mean can only be established from outside it. An expectation
    that is not given is not checked; an unmet one refuses the package
    (``TENANT_NOT_EXPECTED``, ``CONTRACT_NOT_EXPECTED``, ``CLAIM_NOT_EXPECTED``).
    """

    tenant: str | None = None
    contract: Digest | WorkContract | str | None = None
    claim: str | None = None

    @property
    def contract_digest(self) -> Digest | None:
        if self.contract is None:
            return None
        if isinstance(self.contract, WorkContract):
            return self.contract.digest
        if isinstance(self.contract, Digest):
            return self.contract
        return Digest.parse(self.contract)

    def __bool__(self) -> bool:
        return not (self.tenant is None and self.contract is None and self.claim is None)


@dataclass(frozen=True, slots=True)
class StatedStatement:
    """One evidence statement, as the package states it."""

    id: str
    kind: str
    source: str
    issuer: str
    key_id: str
    observed_at: str
    body: str
    claimed: bool


@dataclass(frozen=True, slots=True)
class StatedContent:
    """What a package says about itself.

    **Stated, not verified.** These values are covered by the package's
    commitment, so they are the values of exactly the package the result is
    about; whether anyone stands behind them is what the result's properties
    say. In particular :attr:`recorded_decision` is the issuer's claim. Only
    :attr:`VerificationResult.decision` says a decision was reproduced.
    """

    claim_id: str
    claimant: str
    inputs: Mapping[str, Any] | None
    recorded_decision: str
    contract_reference: str
    statements: tuple[StatedStatement, ...]
    issuer_signature_keys: tuple[str, ...]
    claimed_but_absent: tuple[str, ...]


def _property(name: str, raw: Mapping[str, Any]) -> Property:
    return Property(name, PropertyStatus(raw["status"]), raw.get("reason"))


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """What verifying one package established.

    Read the properties you need; there is deliberately no single "valid"
    flag, and a result cannot be used as a boolean. To enforce an outcome use
    :meth:`require_complete` or :meth:`require_supported`.
    """

    verification_status: VerificationStatus
    refusal: Refusal | None
    """Set exactly when the status is ``REFUSED``."""

    protocol: str | None
    package_id: str | None
    """The package identifier, recomputed by the verifier."""
    tenant: str | None
    claim_id: str | None
    statement_count: int | None
    contract: ContractReference | None

    integrity: Property
    """Steps 1 to 7: the components are well formed and are the ones the
    package commits to."""
    evidence_signatures: Property
    """Every evidence statement's signature verifies."""
    signer_authority: Property
    """Every signer is authorized by *your* registry for its statement's
    tenant, issuer, source and time."""
    decision_reproduced: Property
    """The decision recomputed from the package equals the one it carries."""
    issuer_signature: Property
    """Whether someone you trust for decisions signed this one."""
    source_truthfulness: Property
    """Always ``not_established``. A correctly signed statement can be false."""

    decision: Decision | None
    """The **reproduced** decision, or ``None`` when none was reproduced.
    The decision a package merely carries is never shown here; see
    :attr:`StatedContent.recorded_decision`."""
    requirements: tuple[RequirementValue, ...]
    ignored: tuple[str, ...]
    """Authentic records the contract does not accept (wrong source or kind)."""
    conflicts: tuple[Conflict, ...]
    conditions: tuple[Condition, ...]
    """``wvp-0.1`` only."""

    work_record: WorkRecord | None
    """``wvp-0.2``: the work record computed from the package. It records a
    verification only when this result is complete."""
    record_matched: bool
    """Whether a work record you supplied was compared and matched."""
    expectations_met: Expectations
    """The expectations you gave. All were met; an unmet one is a refusal."""
    verified_issuer_keys: tuple[str, ...] | None
    """The keys whose decision signatures were verified, if any were."""
    stated: StatedContent | None

    trust_registry: Digest | None
    """The byte digest of the registry used, or ``None`` if none was."""
    verifier: str
    """The verifier build: ``verified-verifier-<upstream revision>``."""
    raw: Mapping[str, Any] = field(repr=False, compare=False)
    """The verifier's JSON, in the upstream ``verify --json`` shape."""

    @property
    def is_complete(self) -> bool:
        """Whether every check the protocol defines ran and passed.

        Completeness says nothing about which decision was reproduced.
        """
        return self.verification_status is VerificationStatus.COMPLETE

    @property
    def properties(self) -> tuple[Property, ...]:
        """The six properties, in report order."""
        return (
            self.integrity,
            self.evidence_signatures,
            self.signer_authority,
            self.decision_reproduced,
            self.issuer_signature,
            self.source_truthfulness,
        )

    def __bool__(self) -> NoReturn:
        raise TypeError(
            "a VerificationResult has no truth value: read verification_status and decision, "
            "or call require_complete() / require_supported()"
        )

    def require_complete(self) -> Self:
        """Returns the result if verification was complete; raises otherwise.

        A complete result may carry any decision. Use this to accept a
        package as *verified*, whatever it says about the work.
        """
        if self.verification_status is VerificationStatus.REFUSED and self.refusal is not None:
            raise RequirementNotMet(
                f"the package was refused: {self.refusal.code}: {self.refusal.detail}", self
            )
        if not self.is_complete:
            raise RequirementNotMet(
                "verification is incomplete: no trust registry was supplied, so no signature "
                "was checked and no decision was reproduced",
                self,
            )
        return self

    def require_decision(self, decision: Decision, *, issuer_signed: bool = False) -> Self:
        """Returns the result if verification was complete and reproduced
        exactly ``decision``; raises :class:`verified.RequirementNotMet` otherwise.

        With ``issuer_signed=True`` the decision must also carry a signature
        from a key your registry trusts for decisions. Without one the
        decision is reproduced but nobody stands behind it.
        """
        self.require_complete()
        if self.decision is not decision:
            raise RequirementNotMet(
                f"the reproduced decision is {self.decision}, not {decision}", self
            )
        if issuer_signed and not self.issuer_signature.established:
            raise RequirementNotMet(
                f"the decision is {decision} but its issuer signature is "
                f"{self.issuer_signature.status.value}",
                self,
            )
        return self

    def require_supported(self, *, issuer_signed: bool = False) -> Self:
        """Refuses anything but a complete verification that reproduced
        ``SUPPORTED``.

        Raises for a refused package, an incomplete verification, and a
        reproduced ``CONTRADICTED`` or ``UNDETERMINED``. Passing means the
        signed records, from signers your registry authorizes, establish
        every requirement of the package's contract. It does not mean the
        sources told the truth, and it is not acceptance, billing
        eligibility or settlement.
        """
        return self.require_decision(Decision.SUPPORTED, issuer_signed=issuer_signed)

    def explain(self) -> str:
        """A plain-text report of what was and was not established."""
        if self.refusal is not None:
            return (
                "Work Verification Protocol package\n"
                f"refused               {self.refusal.code}\n"
                f"                      {self.refusal.detail}\n"
                "Nothing else was established about this package."
            )
        lines = [f"Work Verification Protocol package ({self.protocol})"]

        def row(label: str, value: str) -> None:
            lines.append(f"{label:<22}{value}")

        def shown(prop: Property, established: str) -> str:
            if prop.established:
                return established
            return f"{prop.status.value.replace('_', ' ')}" + (
                f": {prop.reason.replace('_', ' ')}" if prop.reason else ""
            )

        row("verification", self.verification_status.value)
        row("package", str(self.package_id))
        row("tenant", f"{self.tenant} (as the package states)")
        row("claim", str(self.claim_id))
        row("package integrity", shown(self.integrity, "established"))
        if self.contract is not None:
            row("contract", f"{self.contract.id} {self.contract.version}, {self.contract.digest}")
        row(
            "evidence signatures",
            shown(self.evidence_signatures, f"established ({self.statement_count} statements)"),
        )
        row(
            "signer authority",
            shown(self.signer_authority, f"established under registry {self.trust_registry}"),
        )
        row(
            "decision reproduced",
            shown(self.decision_reproduced, f"{self.decision}, matches the package"),
        )
        for requirement in self.requirements:
            lines.append(f"  {requirement.id:<30}{requirement.value}")
        for condition in self.conditions:
            lines.append(f"  {condition.id:<30}{'holds' if condition.holds else 'does not hold'}")
        if self.ignored:
            lines.append(
                f"  {len(self.ignored)} authentic record(s) ignored: "
                "source not accepted by the contract"
            )
        if self.conflicts:
            open_ = sum(1 for conflict in self.conflicts if conflict.resolved_to is None)
            lines.append(
                f"  {len(self.conflicts)} conflict(s) among accepted records, {open_} unresolved"
            )
        row("issuer signature", shown(self.issuer_signature, "established"))
        expected = self.expectations_met
        if expected:
            met = [
                name
                for name, value in (
                    ("tenant", expected.tenant),
                    ("contract", expected.contract),
                    ("claim", expected.claim),
                )
                if value is not None
            ]
            row("expectations met", ", ".join(met))
        if self.record_matched:
            row("work record", "the supplied record is about this package")
        row("source truthfulness", "NOT established: no check can establish it")
        if not self.is_complete:
            lines.append(
                "The decision this package carries is its issuer's claim; it was not reproduced."
            )
        return "\n".join(lines)


def _result(
    raw: Mapping[str, Any], trust: TrustRegistry | None, verifier: str
) -> VerificationResult:
    registry = trust.byte_digest if trust is not None else None
    if raw["outcome"] == "refused":
        refusal = Refusal(raw["refusal"]["code"], raw["refusal"]["detail"])
        blank = {
            name: Property(name, PropertyStatus.NOT_CHECKED, "package_refused")
            for name in (
                "packageIntegrity",
                "evidenceSignatures",
                "signerAuthority",
                "decisionReproduced",
                "issuerSignature",
            )
        }
        return VerificationResult(
            verification_status=VerificationStatus.REFUSED,
            refusal=refusal,
            protocol=None,
            package_id=None,
            tenant=None,
            claim_id=None,
            statement_count=None,
            contract=None,
            integrity=blank["packageIntegrity"],
            evidence_signatures=blank["evidenceSignatures"],
            signer_authority=blank["signerAuthority"],
            decision_reproduced=blank["decisionReproduced"],
            issuer_signature=blank["issuerSignature"],
            source_truthfulness=Property(
                "sourceTruthfulness", PropertyStatus.NOT_ESTABLISHED, "no_check_can_establish_it"
            ),
            decision=None,
            requirements=(),
            ignored=(),
            conflicts=(),
            conditions=(),
            work_record=None,
            record_matched=False,
            expectations_met=Expectations(),
            verified_issuer_keys=None,
            stated=None,
            trust_registry=registry,
            verifier=verifier,
            raw=raw,
        )

    properties = raw["properties"]
    reproduced = properties["decisionReproduced"]
    established = reproduced["status"] == "established"
    contract = raw.get("contract")
    met = raw["expectationsMet"]
    stated = raw["stated"]
    keys = raw.get("verifiedIssuerKeys")
    record = raw.get("workRecord")
    return VerificationResult(
        verification_status=VerificationStatus(raw["outcome"]),
        refusal=None,
        protocol=raw["protocol"],
        package_id=raw["packageId"],
        tenant=raw["tenant"],
        claim_id=raw["claim"],
        statement_count=raw["statements"],
        contract=None
        if contract is None
        else ContractReference(
            contract["id"], contract["version"], Digest.from_wire(contract["digest"])
        ),
        integrity=_property("packageIntegrity", properties["packageIntegrity"]),
        evidence_signatures=_property("evidenceSignatures", properties["evidenceSignatures"]),
        signer_authority=_property("signerAuthority", properties["signerAuthority"]),
        decision_reproduced=_property("decisionReproduced", reproduced),
        issuer_signature=_property("issuerSignature", properties["issuerSignature"]),
        source_truthfulness=_property("sourceTruthfulness", properties["sourceTruthfulness"]),
        decision=Decision(reproduced["decision"]) if established else None,
        requirements=tuple(
            RequirementValue(item["id"], Truth(item["value"]))
            for item in reproduced.get("requirements", ())
        ),
        ignored=tuple(reproduced.get("ignored", ())),
        conflicts=tuple(
            Conflict(item["kind"], tuple(item["facts"]), item["resolvedTo"])
            for item in reproduced.get("conflicts", ())
        ),
        conditions=tuple(
            Condition(item["id"], item["holds"], tuple(item["evidence"]))
            for item in reproduced.get("conditions", ())
        ),
        work_record=None if record is None else WorkRecord(record),
        record_matched=bool(raw.get("recordMatched", False)),
        expectations_met=Expectations(
            tenant=met["tenant"],
            contract=None if met["contract"] is None else Digest.from_wire(met["contract"]),
            claim=met["claim"],
        ),
        verified_issuer_keys=None if keys is None else tuple(keys),
        stated=StatedContent(
            claim_id=stated["claim"]["id"],
            claimant=stated["claim"]["claimant"],
            inputs=stated["claim"]["inputs"],
            recorded_decision=stated["recordedDecision"],
            contract_reference=stated["contractReference"],
            statements=tuple(
                StatedStatement(
                    id=item["id"],
                    kind=item["kind"],
                    source=item["source"],
                    issuer=item["issuer"],
                    key_id=item["keyId"],
                    observed_at=item["observedAt"],
                    body=item["body"],
                    claimed=item["claimed"],
                )
                for item in stated["statements"]
            ),
            issuer_signature_keys=tuple(stated["issuerSignatureKeys"]),
            claimed_but_absent=tuple(stated["claimedButAbsent"]),
        ),
        trust_registry=registry,
        verifier=verifier,
        raw=raw,
    )


def run(
    text: bytes,
    *,
    trust: TrustRegistry | None,
    expect: Expectations | None = None,
    record: WorkRecord | None = None,
    protocol: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> VerificationResult:
    """Verifies package text. The one place the native verifier is called."""
    if len(text) > max_bytes:
        raise ResourceLimitError(f"package: larger than {max_bytes} bytes; not examined")
    expect = expect or Expectations()
    digest = expect.contract_digest
    raw = _bridge.call_json(
        "verify",
        text,
        trust=None if trust is None else trust.to_json(),
        protocol=protocol,
        expect_tenant=expect.tenant,
        expect_contract=None if digest is None else digest.hex,
        expect_claim=expect.claim,
        record=None if record is None else record.to_json(),
        max_bytes=max_bytes,
    )
    verifier: str = _bridge.call_json("build_info")["verifier"]
    return _result(raw, trust, verifier)


class Verifier:
    """An offline verifier configured with the relying party's trust.

    ``trust`` has no default and must be written out. ``Verifier(trust=None)``
    is a legitimate, explicit choice: it establishes package integrity only,
    and every result it returns is ``INCOMPLETE`` or ``REFUSED``, never
    ``COMPLETE``. A registry that travels with a package is not a trust
    registry; load yours from your own configuration.

    A verifier holds no state between calls and may be shared across threads
    and tasks.
    """

    __slots__ = ("_expect", "_max_bytes", "_protocol", "_trust")

    def __init__(
        self,
        *,
        trust: TrustRegistry | None,
        expect: Expectations | None = None,
        protocol: str | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        if trust is not None and not isinstance(trust, TrustRegistry):
            raise TypeError("trust is a TrustRegistry: load one with TrustRegistry.load(path)")
        if max_bytes <= 0 or max_bytes > DEFAULT_MAX_BYTES:
            raise ValueError(f"max_bytes is between 1 and {DEFAULT_MAX_BYTES}")
        self._trust = trust
        self._expect = expect
        self._protocol = protocol
        self._max_bytes = max_bytes

    @property
    def trust(self) -> TrustRegistry | None:
        return self._trust

    def verify(
        self,
        package: WorkPackage | bytes | str | os.PathLike[str],
        *,
        expect: Expectations | None = None,
        record: WorkRecord | None = None,
    ) -> VerificationResult:
        """Verifies a package and reports what was established.

        ``package`` is a :class:`verified.WorkPackage`, the package text as
        ``bytes``, or a path (``str`` or ``os.PathLike``) to a package file.

        ``expect`` overrides the verifier's expectations for this call.
        ``record`` is a work record you hold; the package must be the one it
        is about, member for member, or it is refused (``RECORD_MISMATCH``).

        Returns a result for every package that could be examined, including
        refused ones. Raises only when nothing could be concluded: an
        unreadable file, an oversized input, or a request the package's
        protocol version does not define.
        """
        if isinstance(package, WorkPackage):
            text = package.text
        elif isinstance(package, bytes | bytearray | memoryview):
            text = bytes(package)
        else:
            if isinstance(package, str) and package.lstrip().startswith(("{", "[")):
                raise TypeError("a str is a path to a package file; pass package text as bytes")
            path = Path(package)
            size = path.stat().st_size
            if size > self._max_bytes + 2:
                raise ResourceLimitError(
                    f"package {path}: larger than {self._max_bytes} bytes; not examined"
                )
            text = _strip_final_line_end(path.read_bytes())
        return run(
            text,
            trust=self._trust,
            expect=expect if expect is not None else self._expect,
            record=record,
            protocol=self._protocol,
            max_bytes=self._max_bytes,
        )
