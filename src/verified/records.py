"""The portable artifacts: packages and work records.

Terminology differs between audiences, so to be exact:

- A **package** (:class:`WorkPackage`) is the portable file: claim, contract,
  signed evidence and decision, sealed by digest. Product material calls this
  file "the portable Work Record".
- A **work record** (:class:`WorkRecord`) is, in the protocol's words, the
  record of one verification: fifteen values computed from a package. A
  relying party stores it and can later check that a package is the one the
  record is about.

Holding either object establishes nothing. Only a
:class:`verified.VerificationResult` says what was checked.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from verified import _bridge
from verified.canonical import Digest
from verified.errors import MalformedInputError

__all__ = ["WorkPackage", "WorkRecord"]


def _strip_final_line_end(data: bytes) -> bytes:
    """A package is canonical text, which has no trailing line end; a package
    *file* conventionally has one. Exactly one is the file's, as in the
    upstream command-line tool."""
    if data.endswith(b"\r\n"):
        return data[:-2]
    if data.endswith(b"\n"):
        return data[:-1]
    return data


@dataclass(frozen=True, slots=True)
class WorkPackage:
    """The exact bytes of a WVP package.

    The bytes are kept as received and are never re-serialized: consumers
    re-verify from them, and a re-encoded package is a different file.
    """

    text: bytes

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Self:
        """Reads a package file, without examining it."""
        return cls(_strip_final_line_end(Path(path).read_bytes()))

    def save(self, path: str | os.PathLike[str]) -> None:
        """Writes the package text, with no trailing line end."""
        Path(path).write_bytes(self.text)

    @property
    def byte_digest(self) -> Digest:
        """The SHA-256 of the file's bytes.

        Not the package commitment: issuer signatures lie outside the
        commitment, so a signed and an unsigned package share an identifier
        and differ in this digest.
        """
        return Digest.of_bytes(self.text)

    @property
    def stated_package_id(self) -> str | None:
        """The identifier the package states, **unverified**.

        Use :attr:`verified.VerificationResult.package_id`, which the
        verifier recomputes, for anything that matters.
        """
        try:
            value = json.loads(self.text).get("packageId")
        except (ValueError, AttributeError):
            return None
        return value if isinstance(value, str) else None

    def __repr__(self) -> str:
        return f"WorkPackage({len(self.text)} bytes, {self.byte_digest})"


@dataclass(frozen=True, slots=True)
class WorkRecord:
    """A work record: what one verification of a ``wvp-0.2`` package states.

    Every member is a function of the package, so two verifiers compute the
    same record. It is a record of a *decision*, which may be
    ``CONTRADICTED`` or ``UNDETERMINED``; it is not an acceptance, and it is
    not a verification result on its own. Pass it to
    :meth:`verified.Verifier.verify` to check that a package is the one it
    is about.
    """

    members: Mapping[str, Any]

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Self:
        """Reads a work record file."""
        return cls.from_json(Path(path).read_bytes())

    @classmethod
    def from_json(cls, text: bytes | str) -> Self:
        """Reads work record JSON."""
        value = json.loads(
            _bridge.call("canonicalize", text.encode() if isinstance(text, str) else text)
        )
        if not isinstance(value, dict):
            raise MalformedInputError("a work record is a JSON object")
        return cls(value)

    def to_json(self) -> bytes:
        """The record's canonical text."""
        result: bytes = _bridge.call("canonicalize", _bridge.dumps(self.members))
        return result

    def save(self, path: str | os.PathLike[str]) -> None:
        """Writes the record's canonical text to a file."""
        Path(path).write_bytes(self.to_json())

    @property
    def claim_id(self) -> str:
        return str(self.members["claimId"]["value"])

    @property
    def decision(self) -> str:
        """The decision the package carries. Recorded, not re-established."""
        return str(self.members["decision"])

    @property
    def contract_id(self) -> str:
        return str(self.members["contractId"])

    @property
    def contract_version(self) -> str:
        return str(self.members["contractVersion"])

    @property
    def contract_digest(self) -> Digest:
        return Digest.from_wire(self.members["contract"])

    @property
    def package_commitment(self) -> Digest:
        return Digest.from_wire(self.members["packageCommitment"])
