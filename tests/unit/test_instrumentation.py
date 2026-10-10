"""Instrumentation records execution. It never turns execution into evidence."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from verified import (
    Decision,
    EventKind,
    EvidenceKind,
    LifecycleError,
    TraceEvent,
    Verifier,
    WorkSession,
    WorkState,
    content_digest,
)
from verified.integrations import verified_tool

from ..conftest import CONTRACTS, Parties, make_parties


def kinds(session: WorkSession) -> list[str]:
    return [event.kind.value for event in session.events]


def test_a_tool_returning_is_not_recorded_as_success(parties: Parties) -> None:
    @verified_tool(
        work_type="invoice.post",
        contract=parties.contract,
        inputs=lambda invoice_id: {"invoice": invoice_id},
    )
    def post_invoice(invoice_id: str) -> str:
        return "posted"

    with WorkSession(agent=parties.agent, tenant=parties.tenant, clock=parties.clock) as session:
        assert post_invoice("INV-1") == "posted"
        (work,) = session.works
        assert work.state is WorkState.OPEN
        assert work.evidence == ()
        assert work.issued is None
    assert kinds(session) == [
        "session_started",
        "work_begun",
        "tool_started",
        "tool_finished",
        "session_ended",
    ]
    finished = session.events[3]
    assert "posted" not in str(finished.attributes)
    assert "success" not in str(session.export_trace().to_dict())
    # Evaluated with nothing but the tool's word, the claim is undetermined.
    work.claim()
    assert work.issue(trust=parties.trust).decision is Decision.UNDETERMINED


async def test_async_tools_and_error_paths(parties: Parties) -> None:
    @verified_tool(
        work_type="invoice.post",
        contract=CONTRACTS / "invoice-posting.json",
        inputs=lambda invoice_id: {"invoice": invoice_id},
    )
    async def post_invoice(invoice_id: str) -> str:
        await asyncio.sleep(0)
        if invoice_id == "INV-BAD":
            raise ConnectionError("erp.internal:8443 refused, token=secret")
        return "ok"

    async with WorkSession(agent=parties.agent, tenant=parties.tenant) as session:
        async with session.turn() as turn:
            assert await post_invoice("INV-1") == "ok"
            with pytest.raises(ConnectionError):
                await post_invoice("INV-BAD")
        assert turn.correlation_id
    failed = [event for event in session.events if event.kind is EventKind.TOOL_FAILED]
    assert len(failed) == 1
    # The exception's type is recorded; its message, which may hold secrets, is not.
    assert failed[0].attributes["error"] == "ConnectionError"
    assert "secret" not in session.export_trace().to_json().decode()
    assert failed[0].turn == f"{session.session_id}#1"
    # A failed tool leaves its work open; it is not contradicted by the failure.
    assert [work.state for work in session.works] == [WorkState.OPEN, WorkState.OPEN]
    assert kinds(session)[-1] == "session_ended"


async def test_a_session_that_raises_still_ends_and_is_no_longer_current(parties: Parties) -> None:
    with pytest.raises(RuntimeError):  # noqa: PT012 - the session must be entered inside
        async with WorkSession(agent=parties.agent, tenant=parties.tenant) as session:
            assert WorkSession.current() is session
            raise RuntimeError("agent crashed")
    assert WorkSession.current() is None
    assert session.events[-1].kind is EventKind.SESSION_ENDED
    assert session.events[-1].attributes == {"error": "RuntimeError"}
    with pytest.raises(LifecycleError, match="entered once"):
        async with session:
            pass


async def test_concurrent_sessions_do_not_see_each_other() -> None:
    seen: dict[str, list[str]] = {}

    @verified_tool(work_type="lookup")
    async def lookup(name: str) -> str:
        await asyncio.sleep(0.001)
        session = WorkSession.current()
        assert session is not None
        return session.session_id

    async def run(name: str) -> None:
        parties = make_parties(tenant=f"tenant-{name}")
        async with WorkSession(agent=parties.agent, tenant=parties.tenant, session_id=name) as s:
            async with s.turn():
                results = await asyncio.gather(*(lookup(name) for _ in range(5)))
            assert set(results) == {name}
            seen[name] = [event.session_id for event in s.events]

    await asyncio.gather(*(run(f"session-{i}") for i in range(10)))
    assert len(seen) == 10
    for name, sessions in seen.items():
        assert set(sessions) == {name}
        assert len(sessions) == 1 + 1 + 10 + 1  # start, turn, 5 tools x2, turn end is below
    assert WorkSession.current() is None


def test_turns_are_numbered_and_scoped(parties: Parties) -> None:
    with WorkSession(agent=parties.agent, tenant=parties.tenant, session_id="S-1") as session:
        with session.turn(), session.tool("credit"):
            pass
        session.emit(EventKind.NOTE, name="between turns")
        with session.turn("custom"):
            pass
    by_kind = {event.kind: event for event in session.events}
    assert [e.name for e in session.events if e.kind is EventKind.TURN_STARTED] == [
        "S-1#1",
        "custom",
    ]
    assert by_kind[EventKind.TOOL_STARTED].turn == "S-1#1"
    assert by_kind[EventKind.NOTE].turn is None
    assert [event.sequence for event in session.events] == list(range(len(session.events)))


def test_tools_outside_a_session_run_untouched_unless_one_is_required() -> None:
    @verified_tool(work_type="plain")
    def plain(x: int) -> int:
        return x + 1

    @verified_tool(work_type="strict", require_session=True)
    def strict() -> None:
        return None

    assert plain(1) == 2
    assert plain.__name__ == "plain"
    with pytest.raises(LifecycleError, match="outside a WorkSession"):
        strict()
    with pytest.raises(ValueError, match="together"):
        verified_tool(work_type="x", inputs=lambda: {})


def test_a_trace_is_not_evidence_and_signing_it_does_not_make_it_about_the_erp(
    parties: Parties,
) -> None:
    with WorkSession(agent=parties.agent, tenant=parties.tenant, clock=parties.clock) as session:
        work = session.begin_work(contract=parties.contract, inputs={"invoice": "INV-1"})
        trace = session.export_trace()
        with pytest.raises(TypeError, match="not evidence"):
            work.attach(trace)  # type: ignore[arg-type]
        signed = session.trace_evidence(parties.agent_runtime)
        assert signed.kind is EvidenceKind.AGENT_TRACE
        assert signed.source == "agent-runtime"
        assert signed.key_id == "agent-runtime-1"
        work.attach(signed).claim()
        issued = work.issue(trust=parties.trust)
    result = Verifier(trust=parties.trust).verify(issued.package)
    assert result.decision is Decision.UNDETERMINED
    assert result.ignored == (f"e-{signed.id}",)
    assert "package_issued" in kinds(session)
    # The gateway's key cannot be borrowed to sign the agent's trace as the ERP's.
    other = make_parties(tenant="another-tenant", seed=30)
    with pytest.raises(LifecycleError, match="another-tenant"):
        session.trace_evidence(other.agent_runtime)


def test_trace_context_is_attached_as_correlation_only(parties: Parties) -> None:
    def otel() -> dict[str, str]:
        return {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7"}

    events: list[TraceEvent] = []
    with (
        WorkSession(
            agent=parties.agent, tenant=parties.tenant, trace_context=otel, on_event=events.append
        ) as session,
        session.tool("credit", latency=0.25),
    ):
        pass
    assert all(event.attributes["trace_id"] == otel()["trace_id"] for event in session.events)
    assert session.events[1].attributes["latency"] == "0.25"
    assert events == list(session.events)
    assert session.export_trace().digest == session.export_trace().digest


def test_content_digest_keeps_text_out_of_evidence() -> None:
    digest = content_digest("I have credited your account with EUR 40.")
    assert digest.startswith("sha-256:")
    assert len(digest) == len("sha-256:") + 64


def test_contract_paths_are_read_lazily(tmp_path: Path) -> None:
    @verified_tool(
        work_type="x", contract=tmp_path / "missing.json", inputs=lambda: {"invoice": "I"}
    )
    def tool() -> None:
        return None

    tool()  # outside a session nothing is read
    parties = make_parties()
    with WorkSession(agent=parties.agent, tenant=parties.tenant), pytest.raises(FileNotFoundError):
        tool()
