"""Trust registries: the relying party's own statement of whom it trusts.

A registry is verifier configuration. It is never taken from a package, and
this SDK has no default one. Without a registry a verifier establishes
package integrity and nothing else.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from verified import _bridge
from verified.canonical import Digest
from verified.errors import ResourceLimitError, TrustRegistryError

__all__ = ["TrustRegistry", "TrustedKey"]

_MAX_REGISTRY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TrustedKey:
    """One key a relying party trusts, and exactly what for."""

    key_id: str
    algorithm: str
    public_key: str
    issuer: str
    tenant: str
    sources: tuple[str, ...]
    valid_from: str
    valid_until: str | None
    revoked_at: str | None

    def speaks_for(self, source: str) -> bool:
        """Whether the key may sign for ``source``."""
        return source in self.sources


class TrustRegistry:
    """A validated trust registry, with the exact bytes it was read from.

    Build one with :meth:`load`, :meth:`from_json` or :meth:`from_keys`.
    Validation is the shared verifier's: malformed records, unknown members
    (so a misspelt ``revokedAt`` is an error, not silently no revocation),
    duplicate keys and unusable key material are all refused here, when the
    registry is loaded, not in the middle of verifying a package.
    """

    __slots__ = ("_keys", "_text")

    def __init__(self, text: bytes) -> None:
        if len(text) > _MAX_REGISTRY_BYTES:
            raise ResourceLimitError(
                f"trust registry: larger than {_MAX_REGISTRY_BYTES} bytes; not examined"
            )
        parsed = _bridge.call_json("trust_registry", text)
        self._text = bytes(text)
        self._keys = tuple(
            TrustedKey(
                key_id=key["keyId"],
                algorithm=key["algorithm"],
                public_key=key["publicKey"],
                issuer=key["issuer"],
                tenant=key["tenant"],
                sources=tuple(key["sources"]),
                valid_from=key["validFrom"],
                valid_until=key["validUntil"],
                revoked_at=key["revokedAt"],
            )
            for key in parsed["keys"]
        )

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Self:
        """Reads a registry file: ``{"keys": [...]}``."""
        file = Path(path)
        try:
            if file.stat().st_size > _MAX_REGISTRY_BYTES:
                raise ResourceLimitError(
                    f"trust registry {file}: larger than {_MAX_REGISTRY_BYTES} bytes"
                )
            return cls(file.read_bytes())
        except OSError as error:
            raise TrustRegistryError(f"trust registry {file}: {error.strerror}") from error

    @classmethod
    def from_json(cls, text: bytes | str) -> Self:
        """Reads registry JSON text."""
        return cls(text.encode() if isinstance(text, str) else text)

    @classmethod
    def from_keys(cls, keys: Iterable[Mapping[str, Any]]) -> Self:
        """Builds a registry from records in wire form.

        :meth:`verified.SigningAuthority.trusted_key` produces such records.
        Composing a registry is a decision to trust every key in it.
        """
        return cls(_bridge.dumps({"keys": list(keys)}, where="registry"))

    @property
    def keys(self) -> tuple[TrustedKey, ...]:
        """The keys, in registry order."""
        return self._keys

    def find(self, key_id: str) -> TrustedKey | None:
        """The key with this identifier, if the registry holds it."""
        return next((key for key in self._keys if key.key_id == key_id), None)

    def to_json(self) -> bytes:
        """The exact bytes this registry was read from."""
        return self._text

    def to_dict(self) -> dict[str, Any]:
        """The registry as a JSON object."""
        result: dict[str, Any] = json.loads(self._text)
        return result

    @property
    def byte_digest(self) -> Digest:
        """The SHA-256 of the registry's exact bytes: which registry was used."""
        return Digest.of_bytes(self._text)

    def save(self, path: str | os.PathLike[str]) -> None:
        """Writes the registry's bytes to a file."""
        Path(path).write_bytes(self._text)

    def __len__(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        return f"TrustRegistry({len(self._keys)} keys, {self.byte_digest})"
