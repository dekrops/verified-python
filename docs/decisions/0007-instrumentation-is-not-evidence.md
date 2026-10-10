# 0007. Instrumentation records execution and never creates evidence

Status: accepted.

## Decision

`WorkSession`, `verified_tool` and framework adapters record events. They do
not record tool results or model output, do not record "success", and cannot
produce `SignedEvidence` for any system but the runtime's own. `Work.attach`
accepts only `SignedEvidence`. There is no conversion from an OpenTelemetry
span, a trace or a return value to evidence.

`verified_tool` outside a session runs the function unchanged (opt-in by
context); `require_session=True` makes that an error.

No plugin registry: an adapter is a class in its own module that calls
`WorkSession` methods.

## Why

The commonest way a verification product becomes misleading is by promoting
the executor's own telemetry to proof. Keeping the types disjoint makes that
a type error.
