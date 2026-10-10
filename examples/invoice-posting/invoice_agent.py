"""An agent posts an invoice. Did the ERP actually post it?

Run with:  python examples/invoice-posting/invoice_agent.py

Everything here is synthetic: the tenant, the systems, the invoices and the
keys. Three parties appear, and keeping them apart is the whole point.

- The **agent runtime** runs a tool and reports what the tool returned. That
  is its own account of itself.
- The **ERP gateway** sits beside the (simulated) ERP and signs what the ERP
  holds. It has its own key, authorized for the source ``erp``.
- The **relying party** holds a trust registry it composed itself, and
  verifies the resulting package offline.

The same agent run is evaluated three times, against three states of the ERP.
The agent says "posted" every time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from verified import (
    AgentIdentity,
    AssemblyError,
    Ed25519Signer,
    EvidenceSource,
    Expectations,
    RequirementNotMet,
    SignedEvidence,
    SigningAuthority,
    Subject,
    TrustRegistry,
    Verifier,
    WorkContract,
    WorkSession,
)
from verified.integrations import verified_tool

TENANT = "acme-synthetic"
CONTRACT = WorkContract.load(Path(__file__).parent.parent / "contracts" / "invoice-posting.json")
VALID_FROM = "2026-01-01T00:00:00Z"


class SimulatedErp:
    """A stand-in for the system of record. It can silently drop a posting,
    which is exactly the failure an agent cannot see from the tool's return."""

    def __init__(self, *, drops_postings: bool = False) -> None:
        self.postings: dict[str, dict[str, str]] = {}
        self.drops_postings = drops_postings

    async def post_invoice(self, invoice_id: str, amount_cents: int) -> dict[str, str]:
        document = f"DOC-{invoice_id}"
        if not self.drops_postings:
            self.postings[document] = {"invoice": invoice_id, "amount": str(amount_cents)}
        # The API answers "accepted" either way.
        return {"status": "accepted", "document": document}


# --- the agent runtime -------------------------------------------------------

AGENT = AgentIdentity("invoice-agent", version="1")


def make_tool(erp: SimulatedErp) -> Callable[[str, int], Awaitable[dict[str, str]]]:
    @verified_tool(
        work_type="invoice.post",
        contract=CONTRACT,
        inputs=lambda invoice_id, amount_cents: {"invoice": invoice_id},
    )
    async def post_invoice(invoice_id: str, amount_cents: int) -> dict[str, str]:
        return await erp.post_invoice(invoice_id, amount_cents)

    return post_invoice


# --- the ERP gateway: a separate party with a separate key -------------------

GATEWAY_SIGNER = Ed25519Signer(key_id="erp-gateway-1", seed=bytes([11]) * 32)
GATEWAY_AUTHORITY = SigningAuthority(
    key_id="erp-gateway-1",
    issuer="00000000-0000-4000-8000-0000000000e1",
    tenant=TENANT,
    sources=["erp"],
)


def observe_erp(
    erp: SimulatedErp, invoice_id: str, *, vouch_complete: bool
) -> list[SignedEvidence]:
    """What the gateway signs after reading the ERP for one invoice."""
    gateway = EvidenceSource(system="erp", authority=GATEWAY_AUTHORITY, signer=GATEWAY_SIGNER)
    subject = Subject(system="erp", kind="invoice", key=invoice_id)
    evidence = [
        gateway.record(
            "posting",
            {"document": document, "invoice": row["invoice"], "amount": int(row["amount"])},
            subject=subject,
        )
        for document, row in erp.postings.items()
        if row["invoice"] == invoice_id
    ]
    if vouch_complete:
        # "These are all the postings I hold for this invoice." Only this lets
        # a contract conclude that there is none.
        evidence.append(gateway.complete("posting", subject=subject))
    return evidence


# --- the agent's own key: authorized for its runtime, and nothing else -------

AGENT_SIGNER = Ed25519Signer(key_id="invoice-agent-runtime-1", seed=bytes([12]) * 32)
AGENT_AUTHORITY = SigningAuthority(
    key_id="invoice-agent-runtime-1",
    issuer=AGENT.id,
    tenant=TENANT,
    sources=["agent-runtime"],
)

# --- the relying party's registry, composed by the relying party -------------

RELYING_PARTY_TRUST = TrustRegistry.from_keys(
    [
        GATEWAY_AUTHORITY.trusted_key(GATEWAY_SIGNER.public_key, valid_from=VALID_FROM),
        AGENT_AUTHORITY.trusted_key(AGENT_SIGNER.public_key, valid_from=VALID_FROM),
    ]
)


async def scenario(title: str, erp: SimulatedErp, *, gateway_reports: bool, vouch: bool) -> None:
    print(f"\n=== {title} ===")
    post_invoice = make_tool(erp)

    async with WorkSession(agent=AGENT, tenant=TENANT) as session:
        async with session.turn():
            answer = await post_invoice("INV-123", 125_000)
        print(f"agent reports          {answer['status']} ({answer['document']})")

        (work,) = session.works
        print(f"work after the tool    {work.state.value}: nothing is established yet")

        # The agent may sign its own trace. It is authentic and it is still
        # only the agent's word; the contract asks the ERP.
        agent_runtime = EvidenceSource(
            system="agent-runtime", authority=AGENT_AUTHORITY, signer=AGENT_SIGNER
        )
        work.attach(session.trace_evidence(agent_runtime))

        if gateway_reports:
            work.attach(*observe_erp(erp, "INV-123", vouch_complete=vouch))

        work.claim()
        issued = work.issue(trust=RELYING_PARTY_TRUST)

    # A third party, later, with only the package and its own registry.
    result = Verifier(
        trust=RELYING_PARTY_TRUST,
        expect=Expectations(tenant=TENANT, contract=CONTRACT),
    ).verify(issued.package)

    print(f"verification           {result.verification_status.value}")
    print(f"decision reproduced    {result.decision}")
    for requirement in result.requirements:
        print(f"  {requirement.id:<20} {requirement.value}")
    print(
        f"ignored records        {len(result.ignored)} (authentic, but not from an accepted source)"
    )
    try:
        result.require_supported()
        print("require_supported()    passed")
    except RequirementNotMet as error:
        print(f"require_supported()    refused: {error}")


async def impersonation() -> None:
    print("\n=== The agent tries to sign as the ERP ===")
    try:
        EvidenceSource(system="erp", authority=AGENT_AUTHORITY, signer=AGENT_SIGNER)
    except Exception as error:
        print(f"refused locally        {type(error).__name__}: {error}")

    # A process that lies about its authority gets past the local guard. It
    # does not get past the relying party's registry.
    lying = SigningAuthority(
        key_id="invoice-agent-runtime-1", issuer=AGENT.id, tenant=TENANT, sources=["erp"]
    )
    forged = EvidenceSource(system="erp", authority=lying, signer=AGENT_SIGNER).record(
        "posting",
        {"document": "DOC-INV-123", "invoice": "INV-123", "amount": 125_000},
        subject=Subject(system="erp", kind="invoice", key="INV-123"),
    )
    from verified import Work

    work = Work.begin(
        contract=CONTRACT, tenant=TENANT, claimant=AGENT, inputs={"invoice": "INV-123"}
    )
    work.attach(forged).claim()
    try:
        work.issue(trust=RELYING_PARTY_TRUST)
    except AssemblyError as error:
        print(f"refused by the registry {error}")


async def main() -> None:
    await scenario(
        "1. The ERP posted it, and the gateway saw it",
        SimulatedErp(),
        gateway_reports=True,
        vouch=True,
    )
    await scenario(
        "2. Only the agent's word: no evidence from the ERP",
        SimulatedErp(),
        gateway_reports=False,
        vouch=False,
    )
    await scenario(
        "3. The ERP dropped the posting, and says its listing is complete",
        SimulatedErp(drops_postings=True),
        gateway_reports=True,
        vouch=True,
    )
    await impersonation()


if __name__ == "__main__":
    asyncio.run(main())
