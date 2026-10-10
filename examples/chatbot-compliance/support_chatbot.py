"""A support chatbot under two policies, attested per turn and per session.

Run with:  python examples/chatbot-compliance/support_chatbot.py

Policies (synthetic):

- a credit must not exceed EUR 100.00 in one turn;
- credits must not exceed EUR 150.00 in one session.

Each agent turn gets its own claim under the *turn* contract. The session gets
one claim under the *session* contract. The session claim is evaluated on its
own evidence: it is not the sum, the conjunction or any other function of the
turn decisions. The example shows it both ways round.

This example carries no compliance logic. The rules are in the two contract
files; the shared evaluator applies them. Mapping a decision to "compliant" or
"in breach", wording reasons and deciding what to do about it belong to an
application such as Agent Compliance Center.

Two things worth knowing about the contract language:

- It has no arithmetic. A session total cannot be computed by the contract;
  it is a value the tool gateway reports (``sessionTotal``) and stands or
  falls with that source.
- "No credit exceeded the limit" is a statement about *all* credits, and can
  only be concluded when the tool gateway declares its listing complete.
  If the gateway is unreachable, the answer is ``UNDETERMINED``, not "fine".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from verified import (
    AgentIdentity,
    Ed25519Signer,
    EvidenceKind,
    EvidenceSource,
    Expectations,
    SignedEvidence,
    SigningAuthority,
    Subject,
    TrustRegistry,
    Verifier,
    WorkContract,
    WorkSession,
    content_digest,
)
from verified.integrations import verified_tool

TENANT = "acme-synthetic"
CONTRACTS = Path(__file__).parent.parent / "contracts"
TURN_CONTRACT = WorkContract.load(CONTRACTS / "support-chatbot-turn.json")
SESSION_CONTRACT = WorkContract.load(CONTRACTS / "support-chatbot-session.json")
AGENT = AgentIdentity("support-agent", version="3")


def source(system: str, seed: int) -> tuple[EvidenceSource, dict[str, object]]:
    """An independent source with its own key, and the registry record a
    relying party would hold for it."""
    signer = Ed25519Signer(key_id=f"{system}-1", seed=bytes([seed]) * 32)
    authority = SigningAuthority(
        key_id=signer.key_id,
        issuer=f"00000000-0000-4000-8000-0000000000{seed:02x}",
        tenant=TENANT,
        sources=[system],
    )
    record = authority.trusted_key(signer.public_key, valid_from="2026-01-01T00:00:00Z")
    return EvidenceSource(system=system, authority=authority, signer=signer), record


CHAT_PLATFORM, CHAT_KEY = source("chat-platform", 21)
TOOL_GATEWAY, GATEWAY_KEY = source("tool-gateway", 22)
TRUST = TrustRegistry.from_keys([CHAT_KEY, GATEWAY_KEY])


@dataclass
class ToolGateway:
    """The system through which credits are actually issued. It keeps the
    ledger of credits and signs what it holds; the agent does neither."""

    reachable: bool = True
    credits: list[dict[str, str | int]] = field(default_factory=list)

    def issue_credit(self, session: str, turn: str, cents: int) -> None:
        total = cents + sum(int(c["amount"]) for c in self.credits if c["session"] == session)
        self.credits.append(
            {
                "id": f"CR-{len(self.credits) + 1}",
                "session": session,
                "turn": turn,
                "amount": cents,
                "sessionTotal": total,
            }
        )

    def evidence(self, session: str, turn: str | None = None) -> list[SignedEvidence]:
        """Signed credits for a session (or one turn of it), with a statement
        that the listing is complete. An unreachable gateway says nothing."""
        if not self.reachable:
            return []
        subject = Subject(system="support-chat", kind="session", key=session)
        chosen = [c for c in self.credits if c["session"] == session and turn in (None, c["turn"])]
        signed = [
            TOOL_GATEWAY.record(
                "credit", c, subject=subject, evidence_kind=EvidenceKind.API_RESPONSE
            )
            for c in chosen
        ]
        return [*signed, TOOL_GATEWAY.complete("credit", subject=subject)]


def run_session(title: str, script: list[tuple[str, int | None]], gateway: ToolGateway) -> None:
    print(f"\n=== {title} ===")

    @verified_tool(work_type="credit.issue")
    def issue_credit(cents: int) -> str:
        session = WorkSession.current()
        assert session is not None
        gateway.issue_credit(session.session_id, current_turn, cents)
        return "credited"

    turn_work = []
    with WorkSession(agent=AGENT, tenant=TENANT) as session:
        sid = session.session_id
        for reply, credit in script:
            with session.turn() as turn:
                current_turn = turn.name
                if credit is not None:
                    issue_credit(credit)
            # The chat platform, not the agent, records that the turn happened.
            # It signs a digest of the reply; the text stays where it is.
            turn_record = CHAT_PLATFORM.record(
                "turn",
                {"id": current_turn, "session": sid, "content": content_digest(reply)},
                subject=Subject(system="support-chat", kind="turn", key=current_turn),
            )
            work = session.begin_work(
                contract=TURN_CONTRACT,
                inputs={"session": sid, "turn": current_turn},
                label="turn",
            )
            work.attach(turn_record, *gateway.evidence(sid, current_turn))
            turn_work.append(work)

        session_work = session.begin_work(
            contract=SESSION_CONTRACT, inputs={"session": sid}, label="session"
        )
        session_work.attach(
            CHAT_PLATFORM.record(
                "session",
                {"id": sid, "turns": len(script)},
                subject=Subject(system="support-chat", kind="session", key=sid),
            ),
            *gateway.evidence(sid),
        )

    for work, contract, name in [
        *((w, TURN_CONTRACT, f"turn {i}") for i, w in enumerate(turn_work, 1)),
        (session_work, SESSION_CONTRACT, "session"),
    ]:
        work.claim()
        issued = work.issue(trust=TRUST)
        result = Verifier(
            trust=TRUST, expect=Expectations(tenant=TENANT, contract=contract)
        ).verify(issued.package)
        values = ", ".join(f"{r.id}={r.value}" for r in result.requirements)
        print(f"{name:<8} {result.verification_status.value:<9} {result.decision!s:<13} {values}")


def main() -> None:
    run_session(
        "A. Every turn within its limit; the session over its limit",
        [("Credited EUR 60.", 6_000), ("Another EUR 60.", 6_000), ("And EUR 40.", 4_000)],
        ToolGateway(),
    )
    run_session(
        "B. One turn over its limit; the session within its limit",
        [("Hello.", None), ("Credited EUR 120.", 12_000)],
        ToolGateway(),
    )
    run_session(
        "C. The tool gateway cannot be reached: nothing is concluded",
        [("Credited EUR 20.", 2_000)],
        ToolGateway(reachable=False),
    )


if __name__ == "__main__":
    main()
