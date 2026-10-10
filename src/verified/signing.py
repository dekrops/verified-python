"""Signers and the authority they are declared to have.

The SDK never assumes it holds trusted credentials. A signature is produced
only through an explicit :class:`Signer`, and only for what an explicit
:class:`SigningAuthority` names. Whether a relying party *accepts* the key for
that authority is theirs to decide, in their own trust registry.
"""

from __future__ import annotations

import base64
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Self, runtime_checkable

from verified import _bridge
from verified._time import instant
from verified.errors import SigningAuthorityError

__all__ = ["DECISION_SOURCE", "Ed25519Signer", "Signer", "SigningAuthority"]

DECISION_SOURCE = "wvp-decision"
"""The source name through which a registry authorizes a key to sign decisions."""


@runtime_checkable
class Signer(Protocol):
    """Something that can produce Ed25519 signatures with one key.

    Implement this over a KMS, an HSM or a signing service. The SDK hands the
    signer the exact bytes to sign (a domain prefix followed by canonical
    text) and never sees the private key.
    """

    @property
    def key_id(self) -> str:
        """The identifier a trust registry lists this key under."""
        ...

    def sign(self, message: bytes) -> bytes:
        """The 64-byte Ed25519 signature (RFC 8032) over ``message``."""
        ...


def _uuid(value: str | uuid.UUID, what: str) -> str:
    try:
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(value))
    except ValueError as error:
        raise ValueError(f"{what} must be a UUID") from error


@dataclass(frozen=True, slots=True, init=False)
class SigningAuthority:
    """What one key is declared to be allowed to sign for.

    It mirrors one record of a trust registry: a key belongs to one issuer,
    is trusted for one tenant, and may speak for the listed source systems
    and no others. An agent runtime's key lists the runtime, not the ERP.

    Declaring an authority grants nothing. It scopes what this process will
    ask the signer to sign, and it produces the registry record
    (:meth:`trusted_key`) that a relying party may choose to adopt.
    """

    key_id: str
    issuer: str
    tenant: str
    sources: frozenset[str]

    def __init__(
        self, *, key_id: str, issuer: str | uuid.UUID, tenant: str, sources: Iterable[str]
    ) -> None:
        if isinstance(sources, str):
            raise TypeError("sources is a collection of source names, not one string")
        names = frozenset(sources)
        if not names:
            raise ValueError("an authority names at least one source")
        object.__setattr__(self, "key_id", key_id)
        object.__setattr__(self, "issuer", _uuid(issuer, "issuer"))
        object.__setattr__(self, "tenant", tenant)
        object.__setattr__(self, "sources", names)

    def speaks_for(self, source: str) -> bool:
        """Whether this authority names ``source``."""
        return source in self.sources

    def require(self, *, source: str, tenant: str) -> None:
        """Raises unless this authority covers ``source`` for ``tenant``."""
        if tenant != self.tenant:
            raise SigningAuthorityError(
                f"key {self.key_id!r} is declared for tenant {self.tenant!r}, not {tenant!r}"
            )
        if source not in self.sources:
            raise SigningAuthorityError(
                f"key {self.key_id!r} is not declared to speak for source {source!r} "
                f"(declared: {', '.join(sorted(self.sources))}). A key cannot sign an "
                "observation of a system it has no authority over."
            )

    def trusted_key(
        self,
        public_key: str,
        *,
        valid_from: datetime | str,
        valid_until: datetime | str | None = None,
        revoked_at: datetime | str | None = None,
    ) -> dict[str, object]:
        """The trust-registry record a relying party would hold for this key.

        ``public_key`` is base64 of the DER ``SubjectPublicKeyInfo``.
        """
        return {
            "keyId": self.key_id,
            "algorithm": "Ed25519",
            "publicKey": public_key,
            "issuer": {"value": self.issuer},
            "tenant": {"value": self.tenant},
            "sources": sorted(self.sources),
            "validFrom": {"value": instant(valid_from)},
            "validUntil": None if valid_until is None else {"value": instant(valid_until)},
            "revokedAt": None if revoked_at is None else {"value": instant(revoked_at)},
        }


class Ed25519Signer:
    """An in-process Ed25519 signer holding its seed in memory.

    Suitable for tests, examples and development. A production evidence
    source should keep its key in a KMS or HSM behind its own :class:`Signer`.
    """

    __slots__ = ("_key_id", "_seed")

    def __init__(self, *, key_id: str, seed: bytes) -> None:
        if len(seed) != 32:
            raise ValueError("an Ed25519 seed is exactly 32 bytes")
        self._key_id = key_id
        self._seed = bytes(seed)

    @classmethod
    def generate(cls, *, key_id: str) -> Self:
        """A signer with a fresh random key."""
        return cls(key_id=key_id, seed=secrets.token_bytes(32))

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def public_key(self) -> str:
        """The public key as a trust registry spells it."""
        result: str = _bridge.call("ed25519_public_key", self._seed)
        return result

    def sign(self, message: bytes) -> bytes:
        encoded: str = _bridge.call("ed25519_sign", self._seed, message)
        return base64.b64decode(encoded)

    def __repr__(self) -> str:
        return f"Ed25519Signer(key_id={self._key_id!r})"


def encode_signature(signer: Signer, message: bytes) -> dict[str, str]:
    """Signs ``message`` and returns the wire signature object."""
    signature = signer.sign(message)
    if len(signature) != 64:
        raise SigningAuthorityError(
            f"signer {signer.key_id!r} returned {len(signature)} bytes; "
            "an Ed25519 signature is 64 bytes"
        )
    return {
        "scheme": "Ed25519",
        "keyId": signer.key_id,
        "encoded": base64.b64encode(signature).decode("ascii"),
    }
