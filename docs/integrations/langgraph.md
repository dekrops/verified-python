# LangGraph

```sh
uv add "verified-python[langgraph]"
```

```python
from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from verified import WorkContract, WorkSession
from verified.integrations import verified_tool
from verified.integrations.langgraph import VerifiedCallbackHandler

contract = WorkContract.load("contracts/invoice-posting.json")


@tool
@verified_tool(
    work_type="invoice.post",
    contract=contract,
    inputs=lambda invoice_id: {"invoice": invoice_id},
)
def post_invoice(invoice_id: str) -> str:
    """Posts an invoice in the ERP."""
    return erp.post(invoice_id)


graph = StateGraph(MessagesState)
graph.add_node("model", call_model)  # your model node
graph.add_node("tools", ToolNode([post_invoice]))
graph.add_edge(START, "model")
graph.add_conditional_edges("model", tools_condition)
graph.add_edge("tools", "model")
agent = graph.compile(name="invoice-agent")

with WorkSession(agent="invoice-agent", tenant="acme") as session:
    agent.invoke(
        {"messages": [("user", "Post invoice INV-123")]},
        config={"callbacks": [VerifiedCallbackHandler()]},
    )

for work in session.works:  # OPEN: the run established nothing
    ...  # attach evidence from the ERP's gateway, claim, issue
```

`@tool` goes outside `@verified_tool`. `ainvoke` inside `async with` works the
same way.

What is recorded: the run's start and end under the compiled graph's name,
each node entered (as a note, with its step), and each tool call's start and
end with the model's tool call id. What is not recorded: messages, state,
tool arguments and tool results. A raised exception is recorded by its type
only.

The handler raises if it cannot record, for example outside a `WorkSession`,
instead of logging a warning and letting the run continue unrecorded.

What is tested and what is not is listed in
[agent runtime integration](../architecture/agent-runtime-integration.md).
