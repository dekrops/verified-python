# OpenAI Agents SDK

```sh
uv add "verified-python[openai-agents]"
```

```python
from agents import Agent, Runner, function_tool

from verified import WorkContract, WorkSession
from verified.integrations import verified_tool
from verified.integrations.openai_agents import VerifiedRunHooks

contract = WorkContract.load("contracts/invoice-posting.json")


@function_tool
@verified_tool(
    work_type="invoice.post",
    contract=contract,
    inputs=lambda invoice_id: {"invoice": invoice_id},
)
async def post_invoice(invoice_id: str) -> str:
    """Posts an invoice in the ERP."""
    return await erp.post(invoice_id)


agent = Agent(name="invoice-agent", tools=[post_invoice])

async with WorkSession(agent="invoice-agent", tenant="acme") as session:
    await Runner.run(agent, "Post invoice INV-123", hooks=VerifiedRunHooks())

for work in session.works:  # OPEN: the run established nothing
    ...  # attach evidence from the ERP's gateway, claim, issue
```

`@function_tool` goes outside `@verified_tool`.

What is recorded: agent start and end, each tool call's start and end with
the SDK's tool call id, handoffs as notes. What is not recorded: the model's
output and tool results. What is tested and what is not is listed in
[agent runtime integration](../architecture/agent-runtime-integration.md).
