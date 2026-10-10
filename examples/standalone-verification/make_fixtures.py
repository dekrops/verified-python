"""Regenerates the synthetic packages in this directory.

Run with:  python examples/standalone-verification/make_fixtures.py

The keys are derived from fixed, published seeds. Anyone can sign with them.
Never put them in a registry you rely on. ``tests/unit/test_examples.py``
fails if the checked-in files differ from what this script produces.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

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

HERE = Path(__file__).parent
TENANT = "acme-synthetic"
CONTRACT = WorkContract.load(HERE.parent / "contracts" / "invoice-posting.json")


def build() -> dict[str, bytes]:
    """Every fixture, by file name. Fully deterministic."""
    start = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)

    def party(key_id: str, seed: int, source: str) -> tuple[SigningAuthority, Ed25519Signer]:
        authority = SigningAuthority(
            key_id=key_id,
            issuer=f"00000000-0000-4000-8000-0000000000{seed:02x}",
            tenant=TENANT,
            sources=[source],
        )
        return authority, Ed25519Signer(key_id=key_id, seed=bytes([seed]) * 32)

    gateway_authority, gateway_signer = party("synthetic-erp-gateway", 51, "erp")
    issuer_authority, issuer_signer = party("synthetic-decision-issuer", 52, "wvp-decision")
    trust = TrustRegistry.from_keys(
        [
            gateway_authority.trusted_key(
                gateway_signer.public_key, valid_from="2026-01-01T00:00:00Z"
            ),
            issuer_authority.trusted_key(
                issuer_signer.public_key, valid_from="2026-01-01T00:00:00Z"
            ),
        ]
    )
    gateway = EvidenceSource(system="erp", authority=gateway_authority, signer=gateway_signer)
    issuer = DecisionIssuer(authority=issuer_authority, signer=issuer_signer)
    subject = Subject(system="erp", kind="invoice", key="INV-123")
    posting = gateway.record(
        "posting",
        {"document": "DOC-1", "invoice": "INV-123", "amount": 125_000},
        subject=subject,
        observed_at=start,
        evidence_id="00000000-0000-4000-8000-000000000001",
    )
    complete = gateway.complete(
        "posting",
        subject=subject,
        observed_at=start,
        evidence_id="00000000-0000-4000-8000-000000000002",
    )

    def package(number: int, *evidence: SignedEvidence) -> bytes:
        work = Work.begin(
            contract=CONTRACT,
            tenant=TENANT,
            claimant=AgentIdentity("invoice-agent", "1"),
            inputs={"invoice": "INV-123"},
            claim_id=f"00000000-0000-4000-8000-0000000005{number:02d}",
        )
        work.attach(*evidence)
        work.claim(submitted_at=start + timedelta(minutes=5))
        issued = work.issue(
            trust=trust,
            issuer=issuer,
            evaluated_at=start + timedelta(minutes=10),
            package_id=f"00000000-0000-4000-8000-0000000009{number:02d}",
        )
        return issued.package.text

    return {
        "trust.json": trust.to_json(),
        "supported.json": package(1, posting, complete),
        "contradicted.json": package(2, complete),
        "undetermined.json": package(3),
    }


if __name__ == "__main__":
    for name, content in build().items():
        (HERE / name).write_bytes(content)
        print(f"wrote {name} ({len(content)} bytes)")
