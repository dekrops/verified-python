"""Instrumenting an agent runtime, without changing how it runs.

A :class:`WorkSession` records what an agent runtime did: sessions, turns,
tool calls, and the work items it opened. It imposes no event loop, worker
model or tracing backend, and works the same in synchronous and asynchronous
code.

What a session records is an **execution trace**: the executor's own account
of itself. It is useful for correlation and debugging, and it is not
evidence. Three separate things can come out of a session, and they must not
be confused:

==========================  ====================================================
:meth:`WorkSession.export_trace`  An unsigned trace. Telemetry. Establishes nothing.
:meth:`WorkSession.trace_evidence`  A statement signed with the *agent runtime's own*
                                  key, of kind ``AgentTrace``, committing to the
                                  trace. Authentic if the registry lists that key;
                                  it still only says what the agent says. A contract
                                  that asks the ERP will ignore it.
:class:`verified.Work`            A claim with independently sourced evidence, issued
                                  as a package and verified by a relying party.
==========================  ====================================================
"""

from __future__ import annotations

import contextvars
import json
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType
from typing import Any, Self, TypeAlias

from verified import _bridge
from verified._time import Clock, instant, now
from verified.canonical import Digest
from verified.contracts import WorkContract
from verified.errors import LifecycleError
from verified.evidence import EvidenceKind, EvidenceSource, SignedEvidence, Subject
from verified.work import AgentIdentity, Work

__all__ = [
    "EventKind",
    "ExecutionTrace",
    "Scope",
    "TraceEvent",
    "WorkSession",
    "content_digest",
]

TRACE_FORMAT = "verified-python-execution-trace-1"

TraceContext: TypeAlias = Callable[[], Mapping[str, str]]


class EventKind(StrEnum):
    """What happened, in a vocabulary every agent framework can map onto."""

    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    TURN_STARTED = "turn_started"
    TURN_ENDED = "turn_ended"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    TOOL_FAILED = "tool_failed"
    AGENT_STARTED = "agent_started"
    AGENT_ENDED = "agent_ended"
    WORK_BEGUN = "work_begun"
    EVIDENCE_ATTACHED = "evidence_attached"
    CLAIM_FIXED = "claim_fixed"
    PACKAGE_ISSUED = "package_issued"
    NOTE = "note"


def _attribute(value: object, where: str) -> _bridge.Json:
    if isinstance(value, float):
        # The canonical encoding has no fractions. Telemetry often does.
        return repr(value)
    if isinstance(value, Mapping):
        return {str(key): _attribute(item, f"{where}.{key}") for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_attribute(item, where) for item in value]
    return _bridge.plain(value, where=where)


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One thing a runtime reported about its own execution."""

    sequence: int
    kind: EventKind
    at: str
    session_id: str
    turn: str | None = None
    name: str | None = None
    correlation_id: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind.value,
            "at": self.at,
            "sessionId": self.session_id,
            "turn": self.turn,
            "name": self.name,
            "correlationId": self.correlation_id,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    """An unsigned record of what a runtime says it did.

    **Not evidence, and not a verification artifact.** Nobody signed it and
    nothing in it was observed by anyone but the executor. Its digest lets a
    signed statement commit to it, and lets a reader check they hold the same
    trace; it does not make the trace true.
    """

    session_id: str
    tenant: str
    agent: str
    events: tuple[TraceEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": TRACE_FORMAT,
            "sessionId": self.session_id,
            "tenant": self.tenant,
            "agent": self.agent,
            "events": [event.to_wire() for event in self.events],
        }

    def to_json(self) -> bytes:
        """The trace's canonical text."""
        result: bytes = _bridge.call("canonicalize", _bridge.dumps(self.to_dict()))
        return result

    @property
    def digest(self) -> Digest:
        return Digest.of_json(self.to_dict())


def content_digest(text: str) -> str:
    """``sha-256:<hex>`` of a text, for referring to content without carrying it.

    Evidence is disclosed in full to whoever holds a package. Sign a digest
    of a message, not the message, when its text should stay where it is.
    """
    return str(Digest.of_bytes(text.encode()))


_CURRENT: contextvars.ContextVar[WorkSession | None] = contextvars.ContextVar(
    "verified_work_session", default=None
)
_TURN: contextvars.ContextVar[str | None] = contextvars.ContextVar("verified_turn", default=None)


class Scope:
    """A turn or a tool call, usable with ``with`` and ``async with`` alike.

    ``name`` is the turn's identifier or the tool's name; ``correlation_id``
    ties the start and end events together.
    """

    __slots__ = ("_closed", "_ended", "_failed", "_session", "_token", "correlation_id", "name")

    def __init__(
        self,
        session: WorkSession,
        *,
        started: EventKind,
        ended: EventKind,
        failed: EventKind,
        name: str,
        correlation_id: str,
        attributes: Mapping[str, Any],
        turn: bool,
    ) -> None:
        self._session = session
        self._ended = ended
        self._failed = failed
        self.name = name
        self._closed = False
        self._token: contextvars.Token[str | None] | None = None
        self.correlation_id = correlation_id
        if turn:
            self._token = _TURN.set(name)
        session.emit(started, name=name, correlation_id=correlation_id, attributes=attributes)

    def close(
        self, error: BaseException | None = None, attributes: Mapping[str, Any] | None = None
    ) -> None:
        """Ends the span. A raised exception is recorded by type only: its
        message may hold data that does not belong in a trace."""
        if self._closed:
            return
        self._closed = True
        if error is None:
            self._session.emit(
                self._ended,
                name=self.name,
                correlation_id=self.correlation_id,
                attributes=attributes or {},
            )
        else:
            self._session.emit(
                self._failed,
                name=self.name,
                correlation_id=self.correlation_id,
                attributes={**(attributes or {}), "error": type(error).__name__},
            )
        if self._token is not None:
            _TURN.reset(self._token)
            self._token = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close(error)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close(error)


class WorkSession:
    """One run of an agent, as its runtime reports it.

    Use it as a context manager (``with`` or ``async with``). While it is
    entered it is the current session of that thread or task, which is how
    :func:`verified.integrations.verified_tool` and framework adapters find
    it; concurrent sessions in different tasks do not see each other.

    A session never issues or verifies anything by being closed. Work opened
    through :meth:`begin_work` stays in whatever state it reached.
    """

    def __init__(
        self,
        *,
        agent: AgentIdentity | str,
        tenant: str,
        session_id: str | None = None,
        clock: Clock = now,
        on_event: Callable[[TraceEvent], None] | None = None,
        trace_context: TraceContext | None = None,
    ) -> None:
        self.agent = agent if isinstance(agent, AgentIdentity) else AgentIdentity(agent)
        self.tenant = tenant
        self.session_id = session_id or str(uuid.uuid4())
        self._clock = clock
        self._on_event = on_event
        self._trace_context = trace_context
        self._events: list[TraceEvent] = []
        self._works: list[Work] = []
        self._turns = 0
        self._lock = threading.Lock()
        self._token: contextvars.Token[WorkSession | None] | None = None
        self._started = False
        self._ended = False

    @staticmethod
    def current() -> WorkSession | None:
        """The session entered in this thread or task, if any."""
        return _CURRENT.get()

    # -- recording ---------------------------------------------------------

    def emit(
        self,
        kind: EventKind,
        *,
        name: str | None = None,
        correlation_id: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TraceEvent:
        """Records one event. The primitive framework adapters build on."""
        merged: dict[str, Any] = {}
        if self._trace_context is not None:
            merged.update(self._trace_context())
        merged.update(attributes or {})
        recorded = {key: _attribute(value, key) for key, value in merged.items()}
        with self._lock:
            event = TraceEvent(
                sequence=len(self._events),
                kind=kind,
                at=instant(self._clock()),
                session_id=self.session_id,
                turn=_TURN.get(),
                name=name,
                correlation_id=correlation_id,
                attributes=recorded,
            )
            self._events.append(event)
        if self._on_event is not None:
            self._on_event(event)
        return event

    def turn(self, turn_id: str | None = None, **attributes: Any) -> Scope:
        """Opens a turn: one exchange within the session.

        The default identifier is ``<session>#<n>``, counting from 1.
        """
        with self._lock:
            self._turns += 1
            index = self._turns
        return Scope(
            self,
            started=EventKind.TURN_STARTED,
            ended=EventKind.TURN_ENDED,
            failed=EventKind.TURN_ENDED,
            name=turn_id or f"{self.session_id}#{index}",
            correlation_id=str(uuid.uuid4()),
            attributes=attributes,
            turn=True,
        )

    def tool(self, name: str, *, correlation_id: str | None = None, **attributes: Any) -> Scope:
        """Opens a tool call. Leaving the block records that the call
        returned or raised; neither says the operation took effect."""
        return Scope(
            self,
            started=EventKind.TOOL_STARTED,
            ended=EventKind.TOOL_FINISHED,
            failed=EventKind.TOOL_FAILED,
            name=name,
            correlation_id=correlation_id or str(uuid.uuid4()),
            attributes=attributes,
            turn=False,
        )

    # -- work --------------------------------------------------------------

    def begin_work(
        self,
        *,
        contract: WorkContract,
        inputs: Mapping[str, str | bool | int],
        claimant: AgentIdentity | uuid.UUID | str | None = None,
        label: str | None = None,
    ) -> Work:
        """Declares work under a contract, associated with this session.

        The work starts ``OPEN`` and stays so until evidence from identified
        sources is attached and a claim is fixed. The session records the
        work's transitions in its trace.
        """
        correlation = str(uuid.uuid4())

        def observe(event: str, work: Work, attributes: Mapping[str, Any]) -> None:
            self.emit(
                EventKind(event),
                name=work.label,
                correlation_id=correlation,
                attributes={"claim": work.claim_id, **attributes},
            )

        work = Work.begin(
            contract=contract,
            tenant=self.tenant,
            claimant=claimant if claimant is not None else self.agent,
            inputs=inputs,
            clock=self._clock,
            label=label,
            _observer=observe,
        )
        with self._lock:
            self._works.append(work)
        return work

    @property
    def works(self) -> tuple[Work, ...]:
        """The work items opened in this session, in order."""
        with self._lock:
            return tuple(self._works)

    # -- output ------------------------------------------------------------

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def export_trace(self) -> ExecutionTrace:
        """The session's execution trace: unsigned telemetry, not evidence."""
        return ExecutionTrace(
            session_id=self.session_id,
            tenant=self.tenant,
            agent=self.agent.id,
            events=self.events,
        )

    def trace_evidence(
        self, source: EvidenceSource, *, record_kind: str = "agent_trace"
    ) -> SignedEvidence:
        """Signs the trace as the agent runtime's own statement.

        The statement is of kind ``AgentTrace``, from ``source``, whose key
        must be the agent runtime's own. It commits to the trace by digest
        and says only that this runtime reports this trace. A relying party
        that trusts the key learns who produced the trace and that it was
        not altered. It does not learn that anything in it happened.
        """
        if source.authority.tenant != self.tenant:
            raise LifecycleError(
                f"the source signs for tenant {source.authority.tenant!r}, "
                f"and this session is tenant {self.tenant!r}"
            )
        trace = self.export_trace()
        return source.record(
            record_kind,
            {
                "session": self.session_id,
                "agent": self.agent.id,
                "trace": str(trace.digest),
                "events": len(trace.events),
            },
            subject=Subject(system=source.system, kind="session", key=self.session_id),
            evidence_kind=EvidenceKind.AGENT_TRACE,
            observation_id=f"{source.system}:trace:{self.session_id}",
        )

    # -- context management ------------------------------------------------

    def _enter(self) -> Self:
        if self._started:
            raise LifecycleError("a session is entered once; start a new one for a new run")
        self._started = True
        self._token = _CURRENT.set(self)
        self.emit(EventKind.SESSION_STARTED, name=self.agent.name)
        return self

    def _exit(self, error: BaseException | None) -> None:
        if self._ended:
            return
        self._ended = True
        attributes = {} if error is None else {"error": type(error).__name__}
        try:
            self.emit(EventKind.SESSION_ENDED, name=self.agent.name, attributes=attributes)
        finally:
            if self._token is not None:
                _CURRENT.reset(self._token)
                self._token = None

    def __enter__(self) -> Self:
        return self._enter()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._exit(error)

    async def __aenter__(self) -> Self:
        return self._enter()

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._exit(error)

    def __repr__(self) -> str:
        return (
            f"WorkSession({self.session_id}, agent {self.agent.name!r}, {len(self._events)} events)"
        )


def trace_json(trace: ExecutionTrace) -> str:
    """The trace as indented JSON, for people."""
    return json.dumps(trace.to_dict(), indent=2, ensure_ascii=False)
