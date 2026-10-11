"""The LangGraph adapter, against the real framework with a scripted model.

No network and no API key: the model below answers from a script. Skipped
when the optional extra is not installed.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

pytest.importorskip("langgraph", reason="the langgraph extra is not installed")

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from verified import Decision, EventKind, LifecycleError, Verifier, WorkSession, WorkState
from verified.integrations import verified_tool
from verified.integrations.langgraph import VerifiedCallbackHandler

from ..conftest import Parties

pytestmark = pytest.mark.langgraph

REQUEST = {"messages": [("user", "Post INV-1")]}


def graph_for(
    parties: Parties, erp: dict[str, str], *, fails: bool = False, handles_errors: bool = True
) -> Any:
    """A model node and a tool node. The model calls ``post_invoice`` once,
    then says it is done. Whatever happened."""

    @tool
    @verified_tool(
        work_type="invoice.post",
        contract=parties.contract,
        inputs=lambda invoice_id: {"invoice": invoice_id},
    )
    def post_invoice(invoice_id: str) -> str:
        """Posts an invoice in the ERP."""
        if fails:
            raise ConnectionError("erp unreachable")
        erp[f"D-{invoice_id}"] = invoice_id
        return "accepted"

    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "post_invoice",
                        "args": {"invoice_id": "INV-1"},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Invoice INV-1 is posted."),
        ]
    )

    def call_model(state: MessagesState) -> dict[str, Any]:
        return {"messages": [model.invoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node("tools", ToolNode([post_invoice], handle_tool_errors=handles_errors))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", tools_condition)
    graph.add_edge("tools", "model")
    return graph.compile(name="invoice-agent")


def said(result: dict[str, Any]) -> str:
    return str(result["messages"][-1].content)


def test_a_run_is_recorded_and_establishes_nothing_by_itself(parties: Parties) -> None:
    erp: dict[str, str] = {}
    with WorkSession(agent=parties.agent, tenant=parties.tenant, clock=parties.clock) as s:
        result = graph_for(parties, erp).invoke(
            REQUEST, config={"callbacks": [VerifiedCallbackHandler()]}
        )
    assert said(result) == "Invoice INV-1 is posted."

    kinds = [event.kind for event in s.events]
    assert kinds.count(EventKind.AGENT_STARTED) == 1
    assert kinds.count(EventKind.AGENT_ENDED) == 1
    started = next(e for e in s.events if e.kind is EventKind.AGENT_STARTED)
    assert started.name == "invoice-agent"
    nodes = [e.attributes["node"] for e in s.events if e.name == "node"]
    assert nodes == ["model", "tools", "model"]
    # The handler and the decorator both see the call; both record a start and an end.
    assert kinds.count(EventKind.TOOL_STARTED) == kinds.count(EventKind.TOOL_FINISHED) == 2
    handler_call = next(
        e for e in s.events if e.kind is EventKind.TOOL_STARTED and e.name == "post_invoice"
    )
    assert handler_call.correlation_id == "call_1"
    assert handler_call.attributes["node"] == "tools"
    # Neither what was said nor what a tool was given is in the trace.
    trace = s.export_trace().to_json().decode()
    assert "Invoice INV-1 is posted." not in trace
    assert "Post INV-1" not in trace

    (work,) = s.works
    assert work.state is WorkState.OPEN
    assert work.inputs == {"invoice": "INV-1"}

    # Only now does an identified source speak.
    work.attach(parties.posting("INV-1", "D-INV-1")).claim()
    issued = work.issue(trust=parties.trust)
    assert Verifier(trust=parties.trust).verify(issued.package).decision is Decision.SUPPORTED


async def test_an_async_run_is_recorded_the_same_way(parties: Parties) -> None:
    erp: dict[str, str] = {}
    async with WorkSession(agent=parties.agent, tenant=parties.tenant, clock=parties.clock) as s:
        result = await graph_for(parties, erp).ainvoke(
            REQUEST, config={"callbacks": [VerifiedCallbackHandler()]}
        )
    assert said(result) == "Invoice INV-1 is posted."
    kinds = [event.kind for event in s.events]
    assert kinds.count(EventKind.AGENT_STARTED) == kinds.count(EventKind.AGENT_ENDED) == 1
    assert kinds.count(EventKind.TOOL_STARTED) == kinds.count(EventKind.TOOL_FINISHED) == 2
    (work,) = s.works
    assert work.state is WorkState.OPEN


def test_the_graph_saying_done_after_a_failed_tool_supports_nothing(parties: Parties) -> None:
    erp: dict[str, str] = {}
    with WorkSession(agent=parties.agent, tenant=parties.tenant, clock=parties.clock) as s:
        result = graph_for(parties, erp, fails=True).invoke(
            REQUEST, config={"callbacks": [VerifiedCallbackHandler()]}
        )
    # The tool node turned the exception into a message, and the model still
    # reports success.
    assert said(result) == "Invoice INV-1 is posted."
    assert erp == {}
    failed = [e for e in s.events if e.kind is EventKind.TOOL_FAILED]
    # Once from the handler, once from the decorator; the type, not the message.
    assert [e.attributes["error"] for e in failed] == ["ConnectionError", "ConnectionError"]
    assert "erp unreachable" not in s.export_trace().to_json().decode()
    (work,) = s.works
    work.attach(parties.listing_complete("INV-1")).claim()
    issued = work.issue(trust=parties.trust)
    assert Verifier(trust=parties.trust).verify(issued.package).decision is Decision.CONTRADICTED


def test_a_run_that_raises_is_recorded_as_ended_with_the_error(parties: Parties) -> None:
    session = WorkSession(agent=parties.agent, tenant=parties.tenant, clock=parties.clock)
    with session as s, pytest.raises(ConnectionError):
        graph_for(parties, {}, fails=True, handles_errors=False).invoke(
            REQUEST, config={"callbacks": [VerifiedCallbackHandler()]}
        )
    ended = next(e for e in s.events if e.kind is EventKind.AGENT_ENDED)
    assert ended.attributes["error"] == "ConnectionError"
    (work,) = s.works
    assert work.state is WorkState.OPEN


def test_the_handler_needs_a_session(parties: Parties) -> None:
    with pytest.raises(LifecycleError, match="needs a WorkSession"):
        graph_for(parties, {}).invoke(REQUEST, config={"callbacks": [VerifiedCallbackHandler()]})


def test_the_core_does_not_import_the_framework() -> None:
    code = (
        "import sys, verified, verified.integrations; "
        "sys.exit('langgraph' in sys.modules or 'langchain_core' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
