"""The OpenAI Agents SDK adapter, against the real SDK with a scripted model.

No network and no API key: the model below answers from a script. Skipped
when the optional extra is not installed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

pytest.importorskip("agents", reason="the openai-agents extra is not installed")

from agents import Agent, Runner, function_tool, set_tracing_disabled
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from verified import Decision, EventKind, LifecycleError, Verifier, WorkSession, WorkState
from verified.integrations import verified_tool
from verified.integrations.openai_agents import VerifiedRunHooks

from ..conftest import Parties

pytestmark = pytest.mark.openai_agents
set_tracing_disabled(True)


class ScriptedModel(Model):
    """Calls ``post_invoice`` once, then says it is done. Whatever happened."""

    def __init__(self) -> None:
        self.calls = 0

    async def get_response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            output: list[Any] = [
                ResponseFunctionToolCall(
                    type="function_call",
                    call_id="call_1",
                    name="post_invoice",
                    arguments=json.dumps({"invoice_id": "INV-1"}),
                )
            ]
        else:
            output = [
                ResponseOutputMessage(
                    id="msg_1",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        ResponseOutputText(
                            type="output_text", text="Invoice INV-1 is posted.", annotations=[]
                        )
                    ],
                )
            ]
        return ModelResponse(output=output, usage=Usage(), response_id=None)

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def agent_for(parties: Parties, erp: dict[str, str], *, fails: bool = False) -> Agent[Any]:
    @function_tool
    @verified_tool(
        work_type="invoice.post",
        contract=parties.contract,
        inputs=lambda invoice_id: {"invoice": invoice_id},
    )
    async def post_invoice(invoice_id: str) -> str:
        """Posts an invoice in the ERP."""
        if fails:
            raise ConnectionError("erp unreachable")
        erp[f"D-{invoice_id}"] = invoice_id
        return "accepted"

    return Agent(name="invoice-agent", model=ScriptedModel(), tools=[post_invoice])


async def test_a_run_is_recorded_and_establishes_nothing_by_itself(parties: Parties) -> None:
    erp: dict[str, str] = {}
    async with WorkSession(agent=parties.agent, tenant=parties.tenant, clock=parties.clock) as s:
        result = await Runner.run(agent_for(parties, erp), "Post INV-1", hooks=VerifiedRunHooks())
    assert result.final_output == "Invoice INV-1 is posted."

    kinds = [event.kind for event in s.events]
    assert kinds.count(EventKind.AGENT_STARTED) == 1
    assert kinds.count(EventKind.AGENT_ENDED) == 1
    # The hook and the decorator both see the call; both record a start and an end.
    assert kinds.count(EventKind.TOOL_STARTED) == kinds.count(EventKind.TOOL_FINISHED) == 2
    hook_call = next(
        e for e in s.events if e.kind is EventKind.TOOL_STARTED and e.name == "post_invoice"
    )
    assert hook_call.correlation_id == "call_1"
    assert "Invoice INV-1 is posted." not in s.export_trace().to_json().decode()

    (work,) = s.works
    assert work.state is WorkState.OPEN
    assert work.inputs == {"invoice": "INV-1"}

    # Only now does an identified source speak.
    work.attach(parties.posting("INV-1", "D-INV-1")).claim()
    issued = work.issue(trust=parties.trust)
    assert Verifier(trust=parties.trust).verify(issued.package).decision is Decision.SUPPORTED


async def test_the_agent_saying_done_after_a_failed_tool_supports_nothing(parties: Parties) -> None:
    erp: dict[str, str] = {}
    async with WorkSession(agent=parties.agent, tenant=parties.tenant, clock=parties.clock) as s:
        result = await Runner.run(
            agent_for(parties, erp, fails=True), "Post INV-1", hooks=VerifiedRunHooks()
        )
    # The model still reports success, and the SDK reports the tool as ended.
    assert result.final_output == "Invoice INV-1 is posted."
    assert erp == {}
    assert EventKind.TOOL_FAILED in [event.kind for event in s.events]
    (work,) = s.works
    work.attach(parties.listing_complete("INV-1")).claim()
    issued = work.issue(trust=parties.trust)
    assert Verifier(trust=parties.trust).verify(issued.package).decision is Decision.CONTRADICTED


async def test_hooks_need_a_session(parties: Parties) -> None:
    with pytest.raises(LifecycleError, match="needs a WorkSession"):
        await Runner.run(agent_for(parties, {}), "Post INV-1", hooks=VerifiedRunHooks())


def test_the_core_does_not_import_the_framework() -> None:
    code = "import sys, verified, verified.integrations; sys.exit('agents' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
