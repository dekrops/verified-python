"""Canonical encoding (``verified-json-v1``) and digests.

Every digest and signature in the protocol is over canonical bytes. The
encoding is implemented once, in the shared Rust crate ``verified-canonical``;
this module only calls it. It is not RFC 8785.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from verified import _bridge

__all__ = ["Digest", "canonicalize"]

_HEX = frozenset("0123456789abcdef")


def _text(value: object) -> bytes:
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value)
    return _bridge.dumps(value)


def canonicalize(value: object) -> bytes:
    """The canonical bytes of a JSON value.

    ``value`` is JSON text as ``bytes``, or a JSON-like Python value. Floats
    are refused: the encoding has integers only.
    """
    result: bytes = _bridge.call("canonicalize", _text(value))
    return result


@dataclass(frozen=True, slots=True)
class Digest:
    """A SHA-256 digest, as the protocol writes it.

    The wire form is ``{"algorithm": "sha-256", "hex": "<64 hex>"}``; the
    compact form, used in logs and by consuming applications, is
    ``sha-256:<64 hex>``.
    """

    hex: str
    algorithm: str = "sha-256"

    def __post_init__(self) -> None:
        if self.algorithm != "sha-256":
            raise ValueError(f"unsupported digest algorithm {self.algorithm!r}")
        if len(self.hex) != 64 or not set(self.hex) <= _HEX:
            raise ValueError("a sha-256 digest is 64 lowercase hexadecimal digits")

    @classmethod
    def of_json(cls, value: object) -> Self:
        """The digest of a JSON value's canonical bytes."""
        return cls(_bridge.call("canonical_digest", _text(value)))

    @classmethod
    def of_bytes(cls, data: bytes) -> Self:
        """The digest of exact bytes, such as a file. No canonicalization."""
        return cls(hashlib.sha256(data).hexdigest())

    @classmethod
    def parse(cls, text: str) -> Self:
        """Reads ``sha-256:<hex>`` or bare ``<hex>``."""
        return cls(text.removeprefix("sha-256:"))

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> Self:
        """Reads the wire form."""
        return cls(hex=str(value["hex"]), algorithm=str(value["algorithm"]))

    def to_wire(self) -> dict[str, str]:
        """The wire form."""
        return {"algorithm": self.algorithm, "hex": self.hex}

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.hex}"
