"""Producing evidence from a business system without overstating its authority.

Run with:  python examples/enterprise-evidence/order_gateway.py

A small integration watches a (simulated) order system and signs the state
transitions it observes. The points this example makes:

1. Signing authority is configured explicitly and scoped: one key, one
   issuer, one tenant, named source systems. The integration cannot sign for
   a system outside that scope.
2. The signer is an interface. Here it is an in-memory test key; in
   production it is your KMS or HSM, and the SDK never sees the private key.
3. What the integration hands to a relying party is a registry *record* for
   its key. Whether to trust it is the relying party's decision.
4. A signature establishes who said something and that it was not altered.
   It does not establish that it is true.

Everything is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime

from verified import (
    Authentication,
    Ed25519Signer,
    EvidenceKind,
    EvidenceSource,
    Signer,
    SigningAuthority,
    SigningAuthorityError,
    Subject,
    TrustRegistry,
)

TENANT = "acme-synthetic"


class AuditedSigner:
    """A signer that wraps another and logs every request, the way a KMS
    client would. It satisfies ``verified.Signer`` by shape alone."""

    def __init__(self, inner: Signer) -> None:
        self._inner = inner
        self.requests = 0

    @property
    def key_id(self) -> str:
        return self._inner.key_id

    def sign(self, message: bytes) -> bytes:
        self.requests += 1
        domain = message.split(b"\n", 1)[0].decode()
        print(f"  [signer] request {self.requests}: {len(message)} bytes under {domain!r}")
        return self._inner.sign(message)


def show(outcome: Authentication) -> str:
    return "authenticated" if outcome.refusal is None else f"refused: {outcome.refusal.code}"


def main() -> None:
    key = Ed25519Signer(key_id="order-gateway-2026-1", seed=bytes([31]) * 32)
    signer = AuditedSigner(key)
    authority = SigningAuthority(
        key_id="order-gateway-2026-1",
        issuer="00000000-0000-4000-8000-0000000000a1",
        tenant=TENANT,
        sources=["order-system"],
    )
    gateway = EvidenceSource(system="order-system", authority=authority, signer=signer)

    print("1. An observed state transition, signed by the gateway")
    observed_at = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    evidence = gateway.record(
        "order_state",
        {"order": "SO-1001", "state": "shipped", "changedAt": int(observed_at.timestamp())},
        subject=Subject(system="order-system", kind="order", key="SO-1001"),
        evidence_kind=EvidenceKind.STATE_TRANSITION,
        observed_at=observed_at,
        observation_id="order-system:change-log:88213",
    )
    print(f"  statement  {evidence.id}")
    print(f"  source     {evidence.source} (kind {evidence.kind.value})")
    print(f"  observed   {evidence.observed_at}  <- asserted by the signer, not authenticated")
    print(f"  signed by  {evidence.key_id}")
    print(f"  digest     {evidence.digest}")

    print("\n2. The same integration asked to speak for a system it has no authority over")
    try:
        EvidenceSource(system="payments", authority=authority, signer=signer)
    except SigningAuthorityError as error:
        print(f"  refused: {error}")

    print("\n3. What a relying party is offered, and decides for itself")
    record = authority.trusted_key(key.public_key, valid_from="2026-01-01T00:00:00Z")
    print(f"  registry record for {record['keyId']}: sources {record['sources']}")

    adopted = TrustRegistry.from_keys([record])
    print(f"  relying party that adopted the key:     {show(evidence.authenticate(adopted))}")

    narrower = TrustRegistry.from_keys([{**record, "sources": ["warehouse"]}])
    print(f"  relying party that trusts it for less:  {show(evidence.authenticate(narrower))}")

    revoked = TrustRegistry.from_keys([{**record, "revokedAt": {"value": "2026-02-01T00:00:00Z"}}])
    print(f"  relying party that revoked it earlier:  {show(evidence.authenticate(revoked))}")

    print("\n4. What the signature does not say")
    print("  The statement is authentic. Whether SO-1001 really shipped is the order")
    print("  system's word. No verifier can establish source truthfulness.")


if __name__ == "__main__":
    main()
