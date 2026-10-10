"""Independently verifying packages someone else produced.

Run with:  python examples/standalone-verification/verify_packages.py

You are a third party. You hold three package files and a trust registry
that *you* decided on. You have no account, no network, no agent framework
and no access to the system the work was done in.

All three packages verify completely. Only one of them says the work was done.
"""

from __future__ import annotations

from pathlib import Path

from verified import Expectations, RequirementNotMet, TrustRegistry, Verifier, WorkContract

HERE = Path(__file__).parent


def main() -> None:
    # Your registry, from your configuration. Never one that came with a package.
    trust = TrustRegistry.load(HERE / "trust.json")
    # The contract you agreed to, pinned by digest: a package about any other
    # contract, or another tenant, is refused.
    contract = WorkContract.load(HERE.parent / "contracts" / "invoice-posting.json")
    verifier = Verifier(
        trust=trust, expect=Expectations(tenant="acme-synthetic", contract=contract)
    )

    for name in ("supported.json", "contradicted.json", "undetermined.json"):
        result = verifier.verify(HERE / name)
        print(f"\n--- {name} ---")
        print(result.explain())
        try:
            result.require_supported(issuer_signed=True)
            print("=> rely on it: the work is supported by the evidence")
        except RequirementNotMet as error:
            print(f"=> do not rely on it: {error}")

    print("\n--- supported.json, without a trust registry ---")
    integrity_only = Verifier(trust=None).verify(HERE / "supported.json")
    print(f"verification status   {integrity_only.verification_status.value}")
    print(f"decision reproduced   {integrity_only.decision}")
    assert integrity_only.stated is not None
    print(f"the package says      {integrity_only.stated.recorded_decision} (its issuer's claim)")

    print("\n--- supported.json, one byte changed ---")
    text = (HERE / "supported.json").read_bytes().replace(b"INV-123", b"INV-124", 1)
    tampered = verifier.verify(text)
    assert tampered.refusal is not None
    print(f"verification status   {tampered.verification_status.value}: {tampered.refusal.code}")


if __name__ == "__main__":
    main()
