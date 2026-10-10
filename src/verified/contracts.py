"""Work contracts: what counts as done, as data.

A contract is written in Work Contract Language 1. It is read and checked by
the shared Rust crate ``verified-contract``; this module never evaluates one.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from verified import _bridge
from verified.canonical import Digest

__all__ = ["WorkContract"]


class WorkContract:
    """A well-formed work contract and the digest that identifies it.

    The digest is over the contract's canonical text. It binds the language
    version, the vocabulary, the accepted sources per kind of record, the
    conflict policy, every policy value and the requirements. A relying party
    pins the contract it means by this digest (see
    :class:`verified.Expectations`); the identifier and version alone are
    only what the document says about itself.
    """

    __slots__ = ("_canonical", "_summary")

    def __init__(self, text: bytes) -> None:
        self._summary = _bridge.call_json("contract_summary", text)
        self._canonical: bytes = self._summary["canonical"].encode()

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Self:
        """Reads a contract file. Raises :class:`verified.ContractError` if
        it is not a well-formed contract."""
        return cls(Path(path).read_bytes())

    @classmethod
    def from_json(cls, text: bytes | str) -> Self:
        """Reads contract JSON text."""
        return cls(text.encode() if isinstance(text, str) else text)

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> Self:
        """Reads a contract held as a mapping."""
        return cls(_bridge.dumps(document, where="contract"))

    @property
    def id(self) -> str:
        return str(self._summary["id"])

    @property
    def version(self) -> str:
        return str(self._summary["version"])

    @property
    def language(self) -> str:
        return str(self._summary["language"])

    @property
    def semantics(self) -> str:
        return str(self._summary["semantics"])

    @property
    def digest(self) -> Digest:
        """The contract digest: SHA-256 of the canonical text."""
        return Digest.from_wire(self._summary["digest"])

    @property
    def canonical(self) -> bytes:
        """The contract's canonical text."""
        return self._canonical

    def to_dict(self) -> dict[str, Any]:
        """The contract as a JSON object (a fresh copy)."""
        result: dict[str, Any] = json.loads(self._canonical)
        return result

    @property
    def input_names(self) -> tuple[str, ...]:
        """The inputs a claim must supply, as the contract declares them."""
        return tuple(self.to_dict()["inputs"])

    @property
    def accepted_sources(self) -> dict[str, tuple[str, ...]]:
        """For each kind of record, the sources the contract accepts.

        A validly signed record from any other source is authentic and is
        ignored by evaluation. This is read from the contract for display;
        it is the evaluator, not this property, that applies it.
        """
        sources = self.to_dict()["evidence"]["sources"]
        return {kind: tuple(names) for kind, names in sources.items()}

    @property
    def requirement_ids(self) -> tuple[str, ...]:
        """The identifiers of the contract's requirements, in order."""
        return tuple(item["id"] for item in self.to_dict()["requires"])

    def save(self, path: str | os.PathLike[str]) -> None:
        """Writes the canonical text to a file."""
        Path(path).write_bytes(self._canonical)

    def __repr__(self) -> str:
        return f"WorkContract({self.id} {self.version}, {self.digest})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, WorkContract) and other._canonical == self._canonical

    def __hash__(self) -> int:
        return hash(self._canonical)
