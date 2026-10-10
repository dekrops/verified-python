"""Adapter for the OpenAI Agents SDK (``pip install verified-python[openai-agents]``).

:class:`VerifiedRunHooks` translates the SDK's run lifecycle (agent start and
end, tool start and end, handoffs) into events of a
:class:`verified.WorkSession`. Pass it as ``hooks=`` to ``Runner.run``.

It records execution and nothing more. In particular a tool's result is never
recorded as an outcome: the Agents SDK turns a failing tool into a message for
the model by default, so "the tool call ended" does not even mean the function
returned normally, let alone that a business operation took effect. Evidence
comes from an identified source, through :class:`verified.EvidenceSource`.

Function tools decorated with :func:`verified.integrations.verified_tool`
find the session on their own, because the SDK runs them in the context the
run was started in.

Tested against ``openai-agents`` with a scripted model and no network. Model
providers, hosted tools, streaming, guardrails and sessions/memory of the
Agents SDK are not exercised by this adapter's tests.
"""

from __future__ import annotations

from typing import Any

from agents import Agent, RunHooks, Tool
from agents.run_context import RunContextWrapper

from verified.errors import LifecycleError
from verified.instrumentation import EventKind, Scope, WorkSession

__all__ = ["VerifiedRunHooks"]


class VerifiedRunHooks(RunHooks[Any]):
    """Run hooks that record an Agents SDK run in a :class:`verified.WorkSession`.

    With no ``session`` argument the current session is used, so the usual
    form is::

        async with WorkSession(agent="support-agent", tenant="acme") as session:
            await Runner.run(agent, "…", hooks=VerifiedRunHooks())
    """

    def __init__(self, session: WorkSession | None = None) -> None:
        self._session = session
        self._open: dict[str, list[Scope]] = {}

    def _current(self) -> WorkSession:
        session = self._session or WorkSession.current()
        if session is None:
            raise LifecycleError(
                "VerifiedRunHooks needs a WorkSession: run the agent inside one, "
                "or pass session= explicitly"
            )
        return session

    @staticmethod
    def _call_id(context: RunContextWrapper[Any], tool: Tool) -> str:
        call_id = getattr(context, "tool_call_id", None)
        return str(call_id) if call_id else f"tool:{tool.name}"

    async def on_agent_start(self, context: RunContextWrapper[Any], agent: Agent[Any]) -> None:
        self._current().emit(EventKind.AGENT_STARTED, name=agent.name)

    async def on_agent_end(
        self, context: RunContextWrapper[Any], agent: Agent[Any], output: Any
    ) -> None:
        # The output is the agent's own account. It is not recorded.
        self._current().emit(EventKind.AGENT_ENDED, name=agent.name)

    async def on_handoff(
        self, context: RunContextWrapper[Any], from_agent: Agent[Any], to_agent: Agent[Any]
    ) -> None:
        self._current().emit(
            EventKind.NOTE,
            name="handoff",
            attributes={"from": from_agent.name, "to": to_agent.name},
        )

    async def on_tool_start(
        self, context: RunContextWrapper[Any], agent: Agent[Any], tool: Tool
    ) -> None:
        call_id = self._call_id(context, tool)
        scope = self._current().tool(tool.name, correlation_id=call_id, agent=agent.name)
        self._open.setdefault(call_id, []).append(scope)

    async def on_tool_end(
        self, context: RunContextWrapper[Any], agent: Agent[Any], tool: Tool, result: object
    ) -> None:
        scopes = self._open.get(self._call_id(context, tool))
        if scopes:
            # Ended, not succeeded: the result is deliberately not inspected.
            scopes.pop().close()
