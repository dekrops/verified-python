# Agent runtime integration

The goal is that adding verifiable work to an agent is as unobtrusive as
adding telemetry, while producing something telemetry cannot: a statement
about the work that a third party can check.

## The instrumentation contract

Everything a framework adapter needs is on `WorkSession`:

| Runtime event | Primitive |
| --- | --- |
| A run starts and ends | `with WorkSession(agent=…, tenant=…)` / `async with` |
| A turn or step starts and ends | `session.turn(turn_id=None)` |
| A tool is called | `session.tool(name, correlation_id=…)`, or `@verified_tool` |
| Anything else (agent start, handoff, model call) | `session.emit(EventKind.…, name=…, attributes=…)` |
| Work is declared under a contract | `session.begin_work(contract=…, inputs=…)` |
| Evidence arrives from a source | `work.attach(signed_evidence)` |
| The claim is fixed | `work.claim()` |
| The decision is issued | `work.issue(trust=…)` |
| The trace is exported | `session.export_trace()` |
| The runtime signs its own trace | `session.trace_evidence(agent_runtime_source)` |
| Correlation with an existing tracer | `WorkSession(trace_context=…)` |
| Live events for a sink | `WorkSession(on_event=…)` |

An adapter is a translation from a framework's callbacks to these calls. The
OpenAI Agents adapter is about a hundred lines.

`WorkSession.current()` returns the session entered in the current thread or
task (a `contextvars` variable), which is how `verified_tool` and adapters
find it without a global registry. Concurrent sessions do not see each other.

## The line that must not be crossed

```text
 the agent's own account                 │  somebody else's observation
─────────────────────────────────────────┼──────────────────────────────────────
 TraceEvent, ExecutionTrace   (unsigned) │
 a tool's return value                   │  SignedEvidence from an EvidenceSource
 the model's final message               │  whose key the relying party's registry
 session.trace_evidence()  (signed by    │  authorizes for the system of record
   the runtime's own key, AgentTrace)    │
```

Nothing on the left becomes something on the right by being recorded, exported,
signed by the agent, or wrapped in a span.

Concretely, the SDK is built so that:

- `verified_tool` does not record a return value or the word "success". It
  records that a call started and that it returned or raised.
- A raised exception is recorded by type only; its message may hold secrets.
- `Work.attach` accepts only `SignedEvidence`. Passing a trace, a dict or a
  tool result is a `TypeError` that says why.
- `session.trace_evidence` produces an `AgentTrace` statement from the
  runtime's own system. A contract that asks the ERP ignores it, and the
  decision stays `UNDETERMINED`. The tests pin this.
- Closing a session issues nothing and verifies nothing.

## The shape of an integration

```python
async with WorkSession(agent="invoice-agent", tenant="acme") as session:
    await run_agent()  # tools decorated with @verified_tool

for work in session.works:  # each still OPEN
    work.attach(*evidence_from_the_system_of_record(work.inputs))
    work.claim()
    issued = work.issue(trust=issuer_registry)
    store(issued.package)  # the portable artifact
```

Where the evidence comes from is the integration's real design question, and
the SDK does not hide it. Usually the evidence source is a separate process
with its own key: a gateway beside the ERP, the tool gateway, the chat
platform. Evidence may arrive long after the run. A `Work` can be kept open
until it does; the trace and the claim identifier correlate the two.

## Turns and sessions

`session.turn()` scopes events to a turn, named `<session>#<n>` by default.
For compliance-style attestation, each turn and the session are **separate
claims under separate contracts**:

```python
turn_work = session.begin_work(contract=turn_contract, inputs={"session": sid, "turn": tid})
session_work = session.begin_work(contract=session_contract, inputs={"session": sid})
```

The session's decision comes from evaluating the session contract against the
session's evidence. It is not computed from the turn decisions, and the SDK
offers no function that would do so.
`examples/chatbot-compliance` shows a session whose turns are all `SUPPORTED`
while the session is `CONTRADICTED`, and the reverse.

The protocol does not bind a turn claim to its session claim. That binding is
by convention (shared `session` input, shared evidence), and an application
that needs a checked binding must build one, as Agent Compliance Center does
with its coverage check.

`content_digest(text)` gives a `sha-256:` reference for a message, so that a
chat platform can sign *that a turn with this content happened* without the
text entering evidence. Evidence is disclosed in full to whoever holds a
package.

## Framework adapters

Assessed for the first release:

| Framework | Hook surface | Fit | State |
| --- | --- | --- | --- |
| **OpenAI Agents SDK** | `RunHooks`: agent start/end, tool start/end with a tool call id, handoff | Direct; function tools run in the caller's context, so `verified_tool` finds the session | **Adapter included**, tested against the real SDK with a scripted model |
| LangGraph / LangChain | `BaseCallbackHandler` (`on_tool_start/end/error`, `on_chain_*`), run ids, config propagation | Good; needs care with context propagation across graph nodes and threads | Not built |
| Google ADK | `before_/after_agent_callback`, `before_/after_tool_callback` | Good, per-agent callbacks | Not built |
| Generic callbacks | none needed | `WorkSession` is the adapter | Included (`verified_tool`) |

The OpenAI Agents SDK was chosen because its hooks map one-to-one onto the
primitives and a complete run (model, tool call, tool result, final answer)
can be exercised offline through its `Model` interface.

### What "supported" means for the OpenAI Agents adapter

Tested: `Runner.run` with a function tool, hooks recording agent and tool
events with the SDK's tool call id as correlation id, a `verified_tool`
function tool opening work, and a failing tool. Tested against
`openai-agents` 0.23.

Not tested, so not claimed: streaming runs, hosted tools, MCP tools,
guardrails, handoffs across several agents (the hook exists and emits a
note), sessions/memory, and any real model provider.

One behaviour to know: by default the Agents SDK turns a failing function
tool into a message for the model and reports the tool as ended. So
`tool_finished` from the hook means "the call ended", never "it worked".

## OpenTelemetry

Observability is not verification. A span is the runtime describing itself;
it is on the left side of the line above, however detailed it is.

The mapping between the two worlds is explicit and one-directional:

| OpenTelemetry | This SDK | Relationship |
| --- | --- | --- |
| trace id, span id | attributes on every `TraceEvent` | Correlation only. Supplied by `trace_context`; never trusted |
| a span for a tool call | `tool_started` / `tool_finished` / `tool_failed` | The same fact, recorded twice |
| span attributes, GenAI semantic conventions | `TraceEvent.attributes` | May be copied by the caller. They stay telemetry |
| an exported trace | `ExecutionTrace` | Unsigned. Its digest can be committed to by a signed `AgentTrace` statement |
| (nothing) | `Claim` | Spans make no claims |
| (nothing) | `SignedEvidence` from a system of record | Cannot be derived from a span |
| (nothing) | `VerificationResult` | Cannot be derived from a span |

To correlate, pass a function that returns the active identifiers. The SDK
does not import OpenTelemetry:

```python
from opentelemetry import trace


def otel_context() -> dict[str, str]:
    ctx = trace.get_current_span().get_span_context()
    return {"trace_id": f"{ctx.trace_id:032x}", "span_id": f"{ctx.span_id:016x}"}


session = WorkSession(agent="invoice-agent", tenant="acme", trace_context=otel_context)
```

In the other direction, put the claim identifier and, once known, the package
identifier on your spans as attributes, so that an engineer looking at a
trace can find the package that says what the work amounted to.

There is no exporter that turns spans into evidence, and there will not be one.
