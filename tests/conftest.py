"""Shared fixtures. Every key, tenant and record here is synthetic."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from verified import (
    AgentIdentity,
    DecisionIssuer,
    Ed25519Signer,
    EvidenceSource,
    SignedEvidence,
    SigningAuthority,
    Subject,
    TrustRegistry,
    Work,
    WorkContract,
)

ROOT = Path(__file__).parent.parent
CONTRACTS = ROOT / "examples" / "contracts"


def corpus_dir() -> Path | None:
    """The published WVP conformance corpus, or ``None``.

    ``VERIFIED_CONFORMANCE_DIR`` overrides the pinned submodule. With
    ``VERIFIED_CONFORMANCE_REQUIRED=1`` a missing corpus is a failure, so a
    run that claims conformance cannot skip silently.
    """
    override = os.environ.get("VERIFIED_CONFORMANCE_DIR")
    directory = Path(override) if override else ROOT / "conformance" / "wvp" / "test-vectors"
    if (directory / "canonical-hash-v1.json").is_file():
        return directory
    if os.environ.get("VERIFIED_CONFORMANCE_REQUIRED"):
        raise RuntimeError(
            f"VERIFIED_CONFORMANCE_REQUIRED is set but there is no corpus at {directory}; "
            "run `git submodule update --init`"
        )
    return None


@pytest.fixture(scope="session")
def corpus() -> Path:
    directory = corpus_dir()
    if directory is None:
        pytest.skip("the WVP corpus is not checked out (git submodule update --init)")
    return directory


class Clock:
    """A clock that advances one second each time it is read."""

    def __init__(self, start: datetime | None = None) -> None:
        self.at = start or datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.at += timedelta(seconds=1)
        return self.at


@dataclass
class Parties:
    """An agent, an ERP gateway, a decision issuer and a relying party."""

    tenant: str
    contract: WorkContract
    clock: Clock
    agent: AgentIdentity
    gateway_signer: Ed25519Signer
    gateway_authority: SigningAuthority
    agent_signer: Ed25519Signer
    agent_authority: SigningAuthority
    issuer_signer: Ed25519Signer
    issuer_authority: SigningAuthority
    trust: TrustRegistry

    @property
    def gateway(self) -> EvidenceSource:
        return EvidenceSource(
            system="erp",
            authority=self.gateway_authority,
            signer=self.gateway_signer,
            clock=self.clock,
        )

    @property
    def agent_runtime(self) -> EvidenceSource:
        return EvidenceSource(
            system="agent-runtime",
            authority=self.agent_authority,
            signer=self.agent_signer,
            clock=self.clock,
        )

    @property
    def issuer(self) -> DecisionIssuer:
        return DecisionIssuer(authority=self.issuer_authority, signer=self.issuer_signer)

    def subject(self, invoice: str = "INV-1") -> Subject:
        return Subject(system="erp", kind="invoice", key=invoice)

    def posting(self, invoice: str = "INV-1", document: str = "D-1") -> SignedEvidence:
        return self.gateway.record(
            "posting",
            {"document": document, "invoice": invoice, "amount": 125_000},
            subject=self.subject(invoice),
        )

    def listing_complete(self, invoice: str = "INV-1") -> SignedEvidence:
        return self.gateway.complete("posting", subject=self.subject(invoice))

    def work(self, invoice: str = "INV-1", **kwargs: object) -> Work:
        return Work.begin(
            contract=self.contract,
            tenant=self.tenant,
            claimant=self.agent,
            inputs={"invoice": invoice},
            clock=self.clock,
            **kwargs,  # type: ignore[arg-type]
        )


def make_parties(tenant: str = "tenant-synthetic", seed: int = 1) -> Parties:
    agent = AgentIdentity("invoice-agent", version="1")
    gateway_signer = Ed25519Signer(key_id="erp-gateway-1", seed=bytes([seed]) * 32)
    agent_signer = Ed25519Signer(key_id="agent-runtime-1", seed=bytes([seed + 1]) * 32)
    issuer_signer = Ed25519Signer(key_id="decision-issuer-1", seed=bytes([seed + 2]) * 32)
    gateway_authority = SigningAuthority(
        key_id="erp-gateway-1",
        issuer="00000000-0000-4000-8000-0000000000e1",
        tenant=tenant,
        sources=["erp"],
    )
    agent_authority = SigningAuthority(
        key_id="agent-runtime-1", issuer=agent.id, tenant=tenant, sources=["agent-runtime"]
    )
    issuer_authority = SigningAuthority(
        key_id="decision-issuer-1",
        issuer="00000000-0000-4000-8000-0000000000d1",
        tenant=tenant,
        sources=["wvp-decision"],
    )
    valid_from = "2026-01-01T00:00:00Z"
    trust = TrustRegistry.from_keys(
        [
            gateway_authority.trusted_key(gateway_signer.public_key, valid_from=valid_from),
            agent_authority.trusted_key(agent_signer.public_key, valid_from=valid_from),
            issuer_authority.trusted_key(issuer_signer.public_key, valid_from=valid_from),
        ]
    )
    return Parties(
        tenant=tenant,
        contract=WorkContract.load(CONTRACTS / "invoice-posting.json"),
        clock=Clock(),
        agent=agent,
        gateway_signer=gateway_signer,
        gateway_authority=gateway_authority,
        agent_signer=agent_signer,
        agent_authority=agent_authority,
        issuer_signer=issuer_signer,
        issuer_authority=issuer_authority,
        trust=trust,
    )


@pytest.fixture
def parties() -> Parties:
    return make_parties()


@pytest.fixture
def parties_factory() -> Callable[..., Parties]:
    return make_parties
