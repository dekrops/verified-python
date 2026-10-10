"""Signed evidence: what an identified source says it observed.

An evidence statement is an attributable, tamper-evident assertion. It is not
truth (a correctly signed statement can be false), not a claim, and not a
verification result. What makes one count for a claim is decided by two
separate parties: the **relying party's registry** says which key may speak
for which source system, and the **contract** says which sources count for
which kind of record.

That is why an agent cannot upgrade its own account of what happened into an
observation by the system of record: its key is not authorized for that
system, and a relying party's verifier refuses the statement
(``SOURCE_NOT_AUTHORIZED``).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from verified import _bridge
from verified._time import Clock, epoch_seconds, instant, now
from verified.canonical import Digest
from verified.signing import Signer, SigningAuthority, encode_signature
from verified.trust import TrustRegistry
from verified.verification import Refusal

__all__ = [
    "Authentication",
    "Completeness",
    "EvidenceKind",
    "EvidenceSource",
    "Record",
    "SignedEvidence",
    "Subject",
]

STATEMENT_PROTOCOL = "verified-evidence-statement-v1"


class EvidenceKind(StrEnum):
    """How a statement came to be. A label on the statement.

    The kind does not confer authority: a statement labelled
    ``StateTransition`` and signed by a key that cannot speak for the system
    it names is refused all the same.
    """

    STATE_TRANSITION = "StateTransition"
    DATABASE_CHANGE = "DatabaseChange"
    API_RESPONSE = "ApiResponse"
    EVENT = "Event"
    DOCUMENT = "Document"
    AGENT_TRACE = "AgentTrace"
    SIGNED_ATTESTATION = "SignedAttestation"
    HUMAN_WITNESS = "HumanWitness"
    SENSOR_OBSERVATION = "SensorObservation"
    EXTERNAL_ASSERTION = "ExternalAssertion"
    CRYPTOGRAPHIC_PROOF = "CryptographicProof"


@dataclass(frozen=True, slots=True)
class Subject:
    """The business object a statement is about."""

    system: str
    kind: str
    key: str


def _field(name: str, value: object) -> str | bool:
    if isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        # The contract language writes every number as text.
        return str(value)
    raise TypeError(
        f"field {name!r}: a record field is text, a boolean or a whole number. "
        "Write amounts as whole units of the contract's scale (12.50 EUR at scale 2 is 1250) "
        "and times as seconds since 1970."
    )


@dataclass(frozen=True, slots=True, init=False)
class Record:
    """One record a source reported, in a contract's vocabulary.

    ``fields`` maps field names to text, booleans or whole numbers. Numbers
    are written as text on the wire; fractions do not exist in the protocol.
    """

    kind: str
    fields: Mapping[str, str | bool]

    def __init__(self, kind: str, fields: Mapping[str, str | bool | int]) -> None:
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "fields", {name: _field(name, value) for name, value in fields.items()}
        )

    def to_wire(self) -> dict[str, Any]:
        return {"record": {"kind": self.kind, "fields": dict(self.fields)}}


@dataclass(frozen=True, slots=True)
class Completeness:
    """A source's assertion that it has reported *every* record of a kind it
    holds for this claim, as of a time.

    It matters because of what its absence means: without it, not finding a
    record shows nothing, and "there is none" stays ``UNKNOWN``. A source
    cannot vouch for a time after it spoke.
    """

    kind: str
    as_of: int
    """Seconds since 1970-01-01T00:00:00Z."""

    def to_wire(self) -> dict[str, Any]:
        return {"complete": {"kind": self.kind, "asOf": str(self.as_of)}}


@dataclass(frozen=True, slots=True)
class Authentication:
    """Whether one statement is authentic under a relying party's registry.

    Authentic means: the registry holds the signing key, for the statement's
    tenant, issuer and source system, valid at the asserted time, and the
    signature verifies. It says who made the statement and that it was not
    altered. It does not say the statement is true, and it is not a
    verification of any claim.
    """

    refusal: Refusal | None
    """The first check that failed, or ``None``."""

    @property
    def authenticated(self) -> bool:
        return self.refusal is None


@dataclass(frozen=True, slots=True)
class SignedEvidence:
    """A signed statement together with the body it commits to.

    Immutable, and reusable: the same signed statement may be attached to
    several claims.
    """

    statement_json: bytes
    """The signed statement, ``{"statement": …, "signature": …}``, canonical."""
    body_json: bytes
    """The body the statement's ``payload`` commits to, canonical."""

    def _statement(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.statement_json)["statement"]
        return result

    @property
    def id(self) -> str:
        return str(self._statement()["id"]["value"])

    @property
    def tenant(self) -> str:
        return str(self._statement()["tenant"]["value"])

    @property
    def issuer(self) -> str:
        return str(self._statement()["issuer"]["value"])

    @property
    def source(self) -> str:
        """The system the issuer says it observed."""
        return str(self._statement()["source"]["system"])

    @property
    def kind(self) -> EvidenceKind:
        return EvidenceKind(next(iter(self._statement()["kind"])))

    @property
    def observed_at(self) -> str:
        """The asserted observation time. Asserted by the signer; not authenticated."""
        return str(self._statement()["observedAt"]["value"])

    @property
    def key_id(self) -> str:
        return str(json.loads(self.statement_json)["signature"]["keyId"])

    @property
    def digest(self) -> Digest:
        """The statement digest, which identifies it in chains and decisions."""
        return Digest.of_json(self._statement())

    def authenticate(self, trust: TrustRegistry) -> Authentication:
        """Checks this statement under ``trust``: the protocol's ten statement
        checks, in order, by the shared verifier."""
        if not isinstance(trust, TrustRegistry):
            raise TypeError("trust is a TrustRegistry")
        outcome = _bridge.call_json("check_statement", self.statement_json, trust=trust.to_json())
        if outcome["outcome"] == "refused":
            return Authentication(Refusal(outcome["refusal"]["code"], outcome["refusal"]["detail"]))
        return Authentication(None)

    def statement(self) -> dict[str, Any]:
        """The signed statement as a JSON object."""
        result: dict[str, Any] = json.loads(self.statement_json)
        return result

    def body(self) -> dict[str, Any]:
        """The body as a JSON object."""
        result: dict[str, Any] = json.loads(self.body_json)
        return result

    def to_wire(self) -> dict[str, Any]:
        return {"statement": self.statement(), "body": self.body()}

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> SignedEvidence:
        """Reads ``{"statement": signed, "body": body}`` received from elsewhere.

        Only the structure is checked. Authenticity is established when a
        verifier checks the statement under a registry.
        """
        signed = _bridge.dumps(value["statement"], where="statement")
        info = _bridge.call_json("check_statement", signed)
        if info["outcome"] == "refused":
            raise ValueError(f"not an evidence statement: {info['refusal']['detail']}")
        return cls(
            statement_json=_bridge.call("canonicalize", signed),
            body_json=_bridge.call("canonicalize", _bridge.dumps(value["body"], where="body")),
        )

    def __repr__(self) -> str:
        return (
            f"SignedEvidence({self.kind.value} {self.id} from {self.source!r}, key {self.key_id!r})"
        )


class EvidenceSource:
    """An identified source that signs what it observed in one system.

    Construct one where the observation is actually made: in a gateway beside
    the ERP, in the tool gateway, in the agent runtime for its own trace. The
    ``authority`` must name ``system``; otherwise construction fails, before
    anything can be signed. The SDK will not sign an observation of a system
    on behalf of a key that is not declared to speak for it.

    The local check is a guard against mistakes, not the security boundary.
    The boundary is the relying party's registry, which a source cannot write.
    """

    __slots__ = ("_authority", "_clock", "_signer", "_system")

    def __init__(
        self,
        *,
        system: str,
        authority: SigningAuthority,
        signer: Signer,
        clock: Clock = now,
    ) -> None:
        if signer.key_id != authority.key_id:
            from verified.errors import SigningAuthorityError  # noqa: PLC0415

            raise SigningAuthorityError(
                f"the signer holds key {signer.key_id!r} but the authority is declared "
                f"for key {authority.key_id!r}"
            )
        authority.require(source=system, tenant=authority.tenant)
        self._system = system
        self._authority = authority
        self._signer = signer
        self._clock = clock

    @property
    def system(self) -> str:
        return self._system

    @property
    def authority(self) -> SigningAuthority:
        return self._authority

    def _sign(
        self,
        body: Mapping[str, Any],
        *,
        subject: Subject,
        evidence_kind: EvidenceKind,
        observed_at: datetime | str,
        observation_id: str | None,
        evidence_id: str | uuid.UUID | None,
    ) -> SignedEvidence:
        identifier = str(uuid.UUID(str(evidence_id))) if evidence_id else str(uuid.uuid4())
        body_json = _bridge.dumps(body, where="body")
        statement: dict[str, Any] = {
            "protocol": STATEMENT_PROTOCOL,
            "id": {"value": identifier},
            "tenant": {"value": self._authority.tenant},
            "kind": {EvidenceKind(evidence_kind).value: {}},
            "subject": {"system": subject.system, "kind": subject.kind, "key": subject.key},
            "issuer": {"value": self._authority.issuer},
            "source": {
                "system": self._system,
                "observationId": observation_id or f"{self._system}:{identifier}",
            },
            "observedAt": {"value": instant(observed_at)},
            "payload": {
                "algorithm": "sha-256",
                "hex": _bridge.call("payload_digest", body_json),
            },
            "chain": None,
        }
        message: bytes = _bridge.call("statement_signing_input", _bridge.dumps(statement))
        signed = _bridge.dumps(
            {"statement": statement, "signature": encode_signature(self._signer, message)}
        )
        info = _bridge.call_json("check_statement", signed)
        if info["outcome"] == "refused":
            raise ValueError(f"the statement is not well formed: {info['refusal']['detail']}")
        return SignedEvidence(
            statement_json=_bridge.call("canonicalize", signed),
            body_json=_bridge.call("canonicalize", body_json),
        )

    def record(
        self,
        kind: str,
        fields: Mapping[str, str | bool | int],
        *,
        subject: Subject,
        evidence_kind: EvidenceKind = EvidenceKind.EVENT,
        observed_at: datetime | str | None = None,
        observation_id: str | None = None,
        evidence_id: str | uuid.UUID | None = None,
    ) -> SignedEvidence:
        """Signs one record this source observed.

        ``kind`` and ``fields`` are in the vocabulary of the contract the
        evidence is meant for. ``observed_at`` defaults to the source's
        clock; it is asserted by the signer and not authenticated.
        """
        return self._sign(
            Record(kind, fields).to_wire(),
            subject=subject,
            evidence_kind=evidence_kind,
            observed_at=observed_at if observed_at is not None else self._clock(),
            observation_id=observation_id,
            evidence_id=evidence_id,
        )

    def complete(
        self,
        kind: str,
        *,
        subject: Subject,
        as_of: datetime | int | None = None,
        evidence_kind: EvidenceKind = EvidenceKind.EXTERNAL_ASSERTION,
        observed_at: datetime | None = None,
        observation_id: str | None = None,
        evidence_id: str | uuid.UUID | None = None,
    ) -> SignedEvidence:
        """Signs this source's assertion that its records of ``kind`` for
        this subject are complete as of a time.

        Sign this only when the source really has listed everything it
        holds. It is what lets a contract conclude "there is none"; a false
        one is a false statement by the source, which no verifier can detect.
        """
        observed = observed_at if observed_at is not None else self._clock()
        if as_of is None:
            moment = epoch_seconds(observed)
        elif isinstance(as_of, datetime):
            moment = epoch_seconds(as_of)
        else:
            moment = as_of
        return self._sign(
            Completeness(kind, moment).to_wire(),
            subject=subject,
            evidence_kind=evidence_kind,
            observed_at=observed,
            observation_id=observation_id,
            evidence_id=evidence_id,
        )
