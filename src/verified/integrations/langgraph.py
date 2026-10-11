"""Adapter for LangGraph (``pip install verified-python[langgraph]``).

:class:`VerifiedCallbackHandler` translates a graph run (the run itself, its
nodes, its tool calls) into events of a :class:`verified.WorkSession`. Pass it
in the run's config: ``graph.invoke(state, config={"callbacks": [handler]})``.

It records execution and nothing more. A tool's result is never recorded as
an outcome: a ``ToolNode`` can turn a raised exception into a message for the
model, and a tool that returned says only that a function returned. Evidence
comes from an identified source, through :class:`verified.EvidenceSource`.

Tools decorated with :func:`verified.integrations.verified_tool` find the
session on their own, because LangGraph runs nodes in a copy of the context
the run was started in.

Tested against ``langgraph`` with a scripted chat model and no network, with
``invoke`` and ``ainvoke``. Streaming, subgraphs, interrupts, checkpointers
and the LangGraph Platform are not exercised by this adapter's tests.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from verified.errors import LifecycleError
from verified.instrumentation import EventKind, Scope, WorkSession

__all__ = ["VerifiedCallbackHandler"]


class VerifiedCallbackHandler(BaseCallbackHandler):
    """A callback handler that records a LangGraph run in a
    :class:`verified.WorkSession`.

    With no ``session`` argument the current session is used, so the usual
    form is::

        with WorkSession(agent="support-agent", tenant="acme") as session:
            graph.invoke(state, config={"callbacks": [VerifiedCallbackHandler()]})
    """

    # Called in the run's own thread or task, so events keep their order.
    run_inline = True
    # A recording that cannot be made is an error, not a warning in a log.
    raise_error = True

    def __init__(self, session: WorkSession | None = None) -> None:
        self._session = session
        self._runs: dict[UUID, str] = {}
        self._tools: dict[UUID, Scope] = {}

    def _current(self) -> WorkSession:
        session = self._session or WorkSession.current()
        if session is None:
            raise LifecycleError(
                "VerifiedCallbackHandler needs a WorkSession: run the graph inside one, "
                "or pass session= explicitly"
            )
        return session

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = str(kwargs.get("name") or "graph")
        if parent_run_id is None:
            self._runs[run_id] = name
            self._current().emit(EventKind.AGENT_STARTED, name=name)
            return
        # Runnables inside a node inherit its metadata; only the node itself
        # carries the node's name.
        node = (metadata or {}).get("langgraph_node")
        if node is not None and node == name:
            step = (metadata or {}).get("langgraph_step")
            attributes = {"node": name} | ({"step": step} if isinstance(step, int) else {})
            self._current().emit(EventKind.NOTE, name="node", attributes=attributes)

    def on_chain_end(
        self, outputs: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any
    ) -> None:
        name = self._runs.pop(run_id, None)
        if name is not None:
            # The output is the graph's own account. It is not recorded.
            self._current().emit(EventKind.AGENT_ENDED, name=name)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        name = self._runs.pop(run_id, None)
        if name is not None:
            self._current().emit(
                EventKind.AGENT_ENDED, name=name, attributes={"error": type(error).__name__}
            )

    def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        # The arguments are not recorded: they may hold data that does not
        # belong in a trace.
        name = str(kwargs.get("name") or (serialized or {}).get("name") or "tool")
        call_id = kwargs.get("tool_call_id")
        node = (metadata or {}).get("langgraph_node")
        attributes = {"node": node} if isinstance(node, str) else {}
        self._tools[run_id] = self._current().tool(
            name, correlation_id=str(call_id) if call_id else str(run_id), **attributes
        )

    def on_tool_end(
        self, output: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any
    ) -> None:
        scope = self._tools.pop(run_id, None)
        if scope is not None:
            # Ended, not succeeded: the result is deliberately not inspected.
            scope.close()

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        scope = self._tools.pop(run_id, None)
        if scope is not None:
            scope.close(error)
