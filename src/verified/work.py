"""The lifecycle of one claim about one unit of work.

The states follow the protocol, not a convenient story:

``OPEN``
    A contract and its inputs are declared. Evidence is being collected.
    Nothing has been claimed and nothing is known.
``CLAIMED``
    The claim is fixed: it names its contract by digest and lists exactly
    the evidence it relies on. Nothing has been evaluated. A claim is an
    assertion by the claimant and is never evidence for itself.
``ISSUED``
    The contract was evaluated against the admitted evidence and the result
    sealed into a package, with a decision of ``SUPPORTED``, ``CONTRADICTED``
    or ``UNDETERMINED``.

There is no step from a claim alone to a supported outcome. A claim with no
accepted evidence is evaluated like any other and yields ``UNDETERMINED``.

Issuing is not verifying. An issued package carries its issuer's decision;
a relying party establishes what it will rely on by verifying the package
under its own registry (:class:`verified.Verifier`). Acceptance, dispute,
finalization and settlement are states of other systems and are not modelled
here.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Self, TypeAlias

from verified import _bridge
from verified._time import Clock, instant, now
from verified.canonical import Digest
from verified.contracts import WorkContract
from verified.errors import LifecycleError, SigningAuthorityError
from verified.evidence import SignedEvidence
from verified.records import WorkPackage
from verified.signing import DECISION_SOURCE, Signer, SigningAuthority, encode_signature
from verified.trust import TrustRegistry
from verified.verification import Decision, VerificationResult, _result

__all__ = ["AgentIdentity", "Claim", "DecisionIssuer", "IssuedWork", "Work", "WorkState"]

_NAMESPACE = uuid.UUID("6f1d5f0e-6c0b-5e0a-9d55-2a0f8a3f7c11")


def derived_id(*parts: str) -> str:
    """A stable UUID for the given parts (length-prefixed, so ``("ab", "c")``
    and ``("a", "bc")`` differ). An SDK convention, not part of the protocol."""
    return str(uuid.uuid5(_NAMESPACE, "".join(f"{len(part)}:{part}" for part in parts)))


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """A named agent and the UUID the protocol knows it by.

    The protocol identifies a claimant by UUID. Give the UUID your identity
    system assigned, or let one be derived from the name and version. A
    derived identifier is only a stable label: it authenticates nobody.
    """

    name: str
    version: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        identifier = self.id or derived_id("agent", self.name, self.version)
        object.__setattr__(self, "id", str(uuid.UUID(identifier)))


class WorkState(StrEnum):
    """Where a work item is in its lifecycle."""

    OPEN = "open"
    CLAIMED = "claimed"
    ISSUED = "issued"


@dataclass(frozen=True, slots=True)
class Claim:
    """A fixed claim: what the claimant asserts, against which contract, and
    which evidence it relies on. An assertion, not a finding."""

    id: str
    tenant: str
    claimant: str
    contract: Digest
    inputs: Mapping[str, str | bool]
    evidence: tuple[str, ...]
    submitted_at: str


@dataclass(frozen=True, slots=True)
class IssuedWork:
    """A package this process issued, and its issuer's own check of it.

    ``decision`` is what the contract yields from the evidence, as evaluated
    here and reproduced by the shared verifier under the **issuer's**
    registry. It is not an independent verification: a relying party
    verifies ``package`` under a registry of its own choosing.
    """

    package: WorkPackage
    decision: Decision
    issuer_check: VerificationResult
    """The verifier's report under the issuer's registry. Always complete."""

    @property
    def package_id(self) -> str:
        return str(self.issuer_check.package_id)


class DecisionIssuer:
    """A party that stands behind decisions by signing them.

    Its authority must name the ``wvp-decision`` source. A key authorized
    only for evidence cannot sign a decision that counts, and the reverse.
    Signing a decision vouches for the evaluation, not for the sources.
    """

    __slots__ = ("_authority", "_signer")

    def __init__(self, *, authority: SigningAuthority, signer: Signer) -> None:
        if signer.key_id != authority.key_id:
            raise SigningAuthorityError(
                f"the signer holds key {signer.key_id!r} but the authority is declared "
                f"for key {authority.key_id!r}"
            )
        if not authority.speaks_for(DECISION_SOURCE):
            raise SigningAuthorityError(
                f"key {authority.key_id!r} is not declared for {DECISION_SOURCE!r} and "
                "cannot sign decisions"
            )
        self._authority = authority
        self._signer = signer

    @property
    def authority(self) -> SigningAuthority:
        return self._authority

    @property
    def signer(self) -> Signer:
        return self._signer


def _input(name: str, value: object) -> str | bool:
    if isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return str(value)
    raise TypeError(f"input {name!r}: a claim input is text, a boolean or a whole number")


Observer: TypeAlias = Callable[[str, "Work", Mapping[str, Any]], None]


class Work:
    """One claim about one unit of work, from declaration to issued package.

    Create one with :meth:`begin`. Safe to use from several threads; each
    transition happens once.
    """

    __slots__ = (
        "_claim",
        "_claim_id",
        "_claimant",
        "_clock",
        "_contract",
        "_evidence",
        "_inputs",
        "_issued",
        "_lock",
        "_observer",
        "_state",
        "_tenant",
        "label",
    )

    def __init__(
        self,
        *,
        contract: WorkContract,
        tenant: str,
        claimant: str,
        inputs: Mapping[str, str | bool],
        claim_id: str,
        clock: Clock,
        label: str | None,
        observer: Observer | None,
    ) -> None:
        self._contract = contract
        self._tenant = tenant
        self._claimant = claimant
        self._inputs = dict(inputs)
        self._claim_id = claim_id
        self._clock = clock
        self._observer = observer
        self._evidence: dict[str, SignedEvidence] = {}
        self._state = WorkState.OPEN
        self._claim: Claim | None = None
        self._issued: IssuedWork | None = None
        self._lock = threading.Lock()
        self.label = label

    @classmethod
    def begin(
        cls,
        *,
        contract: WorkContract,
        tenant: str,
        claimant: AgentIdentity | uuid.UUID | str,
        inputs: Mapping[str, str | bool | int],
        claim_id: uuid.UUID | str | None = None,
        clock: Clock = now,
        label: str | None = None,
        _observer: Observer | None = None,
    ) -> Self:
        """Declares work under a contract.

        ``inputs`` are the values the contract declares a claim must supply
        (an invoice number, a session identifier, a cutoff). They are what
        the claim is *about*; they prove nothing.
        """
        if not isinstance(contract, WorkContract):
            raise TypeError("contract is a WorkContract: load one with WorkContract.load(path)")
        who = claimant.id if isinstance(claimant, AgentIdentity) else str(uuid.UUID(str(claimant)))
        declared = set(contract.input_names)
        if set(inputs) != declared:
            raise ValueError(
                f"contract {contract.id} {contract.version} declares the inputs "
                f"{sorted(declared)}; got {sorted(inputs)}"
            )
        work = cls(
            contract=contract,
            tenant=tenant,
            claimant=who,
            inputs={name: _input(name, value) for name, value in inputs.items()},
            claim_id=str(uuid.UUID(str(claim_id))) if claim_id else str(uuid.uuid4()),
            clock=clock,
            label=label,
            observer=_observer,
        )
        work._notify("work_begun", {"contract": str(contract.digest)})
        return work

    def _notify(self, event: str, attributes: Mapping[str, Any]) -> None:
        if self._observer is not None:
            self._observer(event, self, attributes)

    @property
    def state(self) -> WorkState:
        return self._state

    @property
    def claim_id(self) -> str:
        return self._claim_id

    @property
    def tenant(self) -> str:
        return self._tenant

    @property
    def claimant(self) -> str:
        return self._claimant

    @property
    def contract(self) -> WorkContract:
        return self._contract

    @property
    def inputs(self) -> dict[str, str | bool]:
        return dict(self._inputs)

    @property
    def evidence(self) -> tuple[SignedEvidence, ...]:
        """The evidence attached so far, in ascending order of identifier."""
        return tuple(self._evidence[key] for key in sorted(self._evidence))

    @property
    def issued(self) -> IssuedWork | None:
        return self._issued

    def attach(self, *evidence: SignedEvidence) -> Self:
        """Attaches signed evidence the claim will rely on.

        Attaching does not authenticate anything; that happens under a
        registry when the package is issued and again whenever it is
        verified. Evidence of another tenant is refused here, since a
        package carrying it would be refused anyway.
        """
        with self._lock:
            if self._state is not WorkState.OPEN:
                raise LifecycleError(
                    f"evidence can be attached only while work is open; it is {self._state.value}. "
                    "A fixed claim lists exactly the evidence it relies on."
                )
            for item in evidence:
                if not isinstance(item, SignedEvidence):
                    raise TypeError(
                        "only SignedEvidence can be attached: an execution trace, a tool's "
                        "return value or a log line is not evidence until an identified "
                        "source signs it"
                    )
                if item.tenant != self._tenant:
                    raise LifecycleError(
                        f"evidence {item.id} belongs to tenant {item.tenant!r}, "
                        f"not {self._tenant!r}"
                    )
                existing = self._evidence.get(item.id)
                if existing is not None and existing != item:
                    raise LifecycleError(f"two different statements share the identifier {item.id}")
                self._evidence[item.id] = item
        for item in evidence:
            self._notify(
                "evidence_attached",
                {"evidence": item.id, "source": item.source, "kind": item.kind.value},
            )
        return self

    def claim(self, *, submitted_at: datetime | str | None = None) -> Claim:
        """Fixes the claim with the evidence attached so far.

        After this the evidence list is closed. The claim is the claimant's
        assertion; it is not evaluated here and it supports nothing by itself.
        """
        with self._lock:
            if self._state is not WorkState.OPEN:
                raise LifecycleError(f"the claim is already fixed (state {self._state.value})")
            self._claim = Claim(
                id=self._claim_id,
                tenant=self._tenant,
                claimant=self._claimant,
                contract=self._contract.digest,
                inputs=dict(self._inputs),
                evidence=tuple(sorted(self._evidence)),
                submitted_at=instant(submitted_at if submitted_at is not None else self._clock()),
            )
            self._state = WorkState.CLAIMED
            claim = self._claim
        self._notify("claim_fixed", {"evidence": list(claim.evidence)})
        return claim

    def issue(
        self,
        *,
        trust: TrustRegistry,
        issuer: DecisionIssuer | None = None,
        evaluated_at: datetime | str | None = None,
        ingested_at: datetime | str | None = None,
        assembled_at: datetime | str | None = None,
        package_id: uuid.UUID | str | None = None,
    ) -> IssuedWork:
        """Evaluates the contract against the claim's evidence and seals the
        result into a ``wvp-0.2`` package.

        ``trust`` is the registry the issuer authenticates evidence under. It
        is required: an issuer that cannot authenticate its evidence has no
        business issuing a decision. The package is returned only if the
        shared verifier reproduces its decision completely under that
        registry; otherwise :class:`verified.AssemblyError` names the refusal
        (for example ``SOURCE_NOT_AUTHORIZED`` for a statement whose key may
        not speak for the system it names).

        The decision may be ``CONTRADICTED`` or ``UNDETERMINED``. Those are
        results, not errors.

        ``issuer``, if given, signs the decision. Without one the package
        carries no issuer signature: the decision can be reproduced by
        anyone, and nobody stands behind it.
        """
        with self._lock:
            if self._state is WorkState.OPEN or self._claim is None:
                raise LifecycleError(
                    "there is no claim yet: call claim() to fix what is asserted and which "
                    "evidence it relies on"
                )
            if self._state is WorkState.ISSUED:
                raise LifecycleError(
                    "this work was already issued; a decision about new evidence is a new claim"
                )
            claim = self._claim
            evaluated = instant(evaluated_at if evaluated_at is not None else self._clock())
            parts = {
                "tenant": self._tenant,
                "contract": self._contract.to_dict(),
                "claim": {
                    "id": claim.id,
                    "claimant": claim.claimant,
                    "inputs": dict(claim.inputs),
                    "submittedAt": claim.submitted_at,
                },
                "evidence": [self._evidence[key].to_wire() for key in claim.evidence],
                "evaluation": {
                    "packageId": str(uuid.UUID(str(package_id)))
                    if package_id
                    else str(uuid.uuid4()),
                    "ingestedAt": instant(ingested_at) if ingested_at is not None else evaluated,
                    "assembledAt": instant(assembled_at) if assembled_at is not None else evaluated,
                    "evaluatedAt": evaluated,
                },
            }
            registry = trust.to_json()
            text, report = _bridge.call("assemble_package", _bridge.dumps(parts), registry)
            if issuer is not None:
                issuer.authority.require(source=DECISION_SOURCE, tenant=self._tenant)
                message: bytes = _bridge.call("decision_signing_input", text)
                signature = encode_signature(issuer.signer, message)
                text, report = _bridge.call(
                    "attach_issuer_signature",
                    text,
                    signature["keyId"],
                    signature["encoded"],
                    registry,
                )
            verifier: str = _bridge.call_json("build_info")["verifier"]
            check = _result(json.loads(report), trust, verifier)
            if check.decision is None:  # pragma: no cover - the native side guarantees it
                raise LifecycleError("the issuer's check did not reproduce a decision")
            self._issued = IssuedWork(
                package=WorkPackage(text), decision=check.decision, issuer_check=check
            )
            self._state = WorkState.ISSUED
            issued = self._issued
        self._notify(
            "package_issued", {"package": issued.package_id, "decision": issued.decision.value}
        )
        return issued

    def __repr__(self) -> str:
        return (
            f"Work(claim {self._claim_id}, {self._contract.id} {self._contract.version}, "
            f"{self._state.value}, {len(self._evidence)} evidence)"
        )
