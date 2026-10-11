"""Work relations (work relation v1, a draft): what authorities say about the
records of one unit of work.

One unit of work leaves several records: a package, a work record in a
ledger, a registration at a claim registry. A *work relation* is a signed
statement by which an authority says how records it knows are related.
:func:`read_history` reads relations against the records given with them,
under *your* trust registry, and reports each relation on its own.

What a reading establishes is narrow:

- A relation shows that an authority said something within its scope. It
  does not show that the thing is true.
- ``CHECKED`` means the statement is consistent with the records in hand.
  It is not a verification result. **No record is verified here**: verify a
  package with :class:`~verified.Verifier`.
- A record that was not given never makes a reading fail. It makes the
  relations to it ``STATED``: read, and not checked.
- Nothing is known about relations that were not presented, unless their
  authority chained them, and never about what follows the last one.

Every rule is in the shared Rust reader (``verified-history``). Nothing in
this module decides anything about a relation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn

from verified import _bridge
from verified.canonical import Digest
from verified.trust import TrustRegistry

__all__ = [
    "HistoryReading",
    "OfferedRecord",
    "RecordKind",
    "Reference",
    "RelationRead",
    "SameClaim",
    "Standing",
    "StreamCompleteness",
    "StreamRead",
    "read_history",
]


class RecordKind(StrEnum):
    """The kinds of record a relation can name."""

    PACKAGE = "package"
    WORK_RECORD = "work-record"
    AGREEMENT = "agreement"
    CLAIM_COMMITMENT = "claim-commitment"
    RECEIPT = "receipt"


class Standing(StrEnum):
    """How one relation stands, given the records in hand."""

    CHECKED = "CHECKED"
    """Authentic, every record it names is held, and they state what it
    states. Not a verification result."""
    STATED = "STATED"
    """Authentic, nothing held contradicts it, and a record it names was not
    given. Read, and not checked."""
    CONTRADICTED = "CONTRADICTED"
    """Authentic, and a held record states otherwise."""
    REFUSED = "REFUSED"
    """Not a relation the reader accepts."""


class StreamCompleteness(StrEnum):
    """What the presented statements of one stream show."""

    UNINTERRUPTED = "UNINTERRUPTED"
    """Step 0 and every step up to the last one presented are present.
    Nothing is known about what follows."""
    UNKNOWN = "UNKNOWN"
    """A step is missing, or the stream's first step was not presented."""


@dataclass(frozen=True, slots=True)
class Reference:
    """A record, named by its kind and that kind's own digest. A reference of
    one kind never names a record of another."""

    kind: str
    digest: Digest


@dataclass(frozen=True, slots=True)
class OfferedRecord:
    """A record text, offered as one kind. It is held only as that kind."""

    kind: str
    text: str

    def to_wire(self) -> dict[str, str]:
        return {"kind": str(self.kind), "text": self.text}


@dataclass(frozen=True, slots=True)
class RelationRead:
    """One relation as read: who said it, if anyone you trust did, and how it
    stands."""

    standing: Standing
    relation: str | None
    """The relation's name (``recorded``, ``linked``, ``groups``), once its
    body was read."""
    source: str | None
    """The source the statement speaks as, once the statement verified."""
    key_id: str | None
    code: str | None
    """Why it is refused, or what a held record contradicts."""
    absent: tuple[Reference, ...]
    """The records it names that were not given, when it is ``STATED``."""


@dataclass(frozen=True, slots=True)
class SameClaim:
    """Whether one package's claim and one registered claim are the same
    claim. Nobody signs this: it is computed from the three records."""

    package: Digest
    claim: Digest
    agreement: Digest
    result: str
    """``SAME_CLAIM``, or the first condition that does not hold."""

    @property
    def same(self) -> bool:
        return self.result == "SAME_CLAIM"


@dataclass(frozen=True, slots=True)
class StreamRead:
    """What the presented statements of one stream show."""

    tenant: str
    issuer: str
    stream: str
    completeness: str
    """A :class:`StreamCompleteness` value, or the chain code the stream fails
    with (for example ``CHAIN_EQUIVOCATION``)."""
    last: int | None
    """The last step presented, when the stream is uninterrupted."""


def _reference(raw: Mapping[str, Any]) -> Reference:
    return Reference(raw["kind"], Digest(raw["digest"]["hex"], raw["digest"]["algorithm"]))


def _digest(raw: Mapping[str, Any]) -> Digest:
    return Digest(raw["hex"], raw["algorithm"])


@dataclass(frozen=True, slots=True)
class HistoryReading:
    """What a set of relations and records shows. Each part stands on its
    own: there is no single result, and this object has no truth value."""

    records: tuple[Reference | str, ...]
    """Each offered record, in the order given: the reference it is held
    under, or why it is not held (``MALFORMED_RECORD``, ``UNKNOWN_KIND``)."""
    relations: tuple[RelationRead, ...]
    same_claims: tuple[SameClaim, ...]
    streams: tuple[StreamRead, ...]
    raw: Mapping[str, Any]
    """The reading exactly as the shared reader states it."""

    records_verified: bool = False
    """Always ``False``: reading relations verifies no record."""

    def __bool__(self) -> NoReturn:
        raise TypeError(
            "a HistoryReading has no truth value: look at each relation's standing, "
            "and verify each record with its own verifier"
        )

    @classmethod
    def _from_raw(cls, raw: Mapping[str, Any]) -> HistoryReading:
        return cls(
            records=tuple(
                record["error"] if "error" in record else _reference(record)
                for record in raw["records"]
            ),
            relations=tuple(
                RelationRead(
                    standing=Standing(read["standing"]),
                    relation=read.get("relation"),
                    source=read.get("source"),
                    key_id=read.get("keyId"),
                    code=read.get("code"),
                    absent=tuple(_reference(r) for r in read.get("absent", ())),
                )
                for read in raw["relations"]
            ),
            same_claims=tuple(
                SameClaim(
                    package=_digest(same["package"]),
                    claim=_digest(same["claim"]),
                    agreement=_digest(same["agreement"]),
                    result=same["result"],
                )
                for same in raw["sameClaims"]
            ),
            streams=tuple(
                StreamRead(
                    tenant=stream["tenant"]["value"],
                    issuer=stream["issuer"]["value"],
                    stream=stream["stream"],
                    completeness=stream["completeness"],
                    last=stream.get("last"),
                )
                for stream in raw["streams"]
            ),
            raw=raw,
        )


def read_history(
    relations: Iterable[Mapping[str, Any]],
    records: Iterable[OfferedRecord | Mapping[str, Any]],
    trust: TrustRegistry,
) -> HistoryReading:
    """Reads work relations against the records given with them.

    ``relations`` are ``{"statement": ..., "body": ...}`` objects: a signed
    evidence statement and the relation body its payload commits to.
    ``records`` are record texts with the kind each is offered as. Both are
    what a ledger exports for one claim. ``trust`` is your registry: a
    relation is accepted only from a key it trusts for the relation's source.

    Offline, and without a clock. It verifies no record.
    """
    if not isinstance(trust, TrustRegistry):
        raise TypeError("trust is a TrustRegistry")
    offered = [r.to_wire() if isinstance(r, OfferedRecord) else r for r in records]
    raw = _bridge.call_json(
        "read_history",
        _bridge.dumps(list(relations), where="relations"),
        _bridge.dumps(offered, where="records"),
        trust.to_json(),
    )
    return HistoryReading._from_raw(raw)
