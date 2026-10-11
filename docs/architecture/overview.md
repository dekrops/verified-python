# Architecture overview

`verified-python` is an idiomatic Python API over a narrowly scoped Rust
extension. The Python side owns developer experience; the Rust side owns every
rule of the protocol.

```text
        WVP specifications and vectors            dekrops/wvp (normative)
                      │
        Rust verification crates                  dekrops/verified-cli, pinned
   canonical · protocol · contract · verifier · work-unit
                      │
        verified._native  (PyO3, abi3)            rust/  — bytes and JSON text in, JSON text out
                      │
        verified          (pure Python)           src/verified/
   ┌──────────────┬───────────────┬──────────────────────────┐
   │ verification │ evidence      │ work · instrumentation   │
   │ trust        │ signing       │ integrations/            │
   │ contracts    │ work_unit     │                          │
   └──────────────┴───────────────┴──────────────────────────┘
                      │
        your agent, your gateway, your verifier
```

## The modules

| Module | Responsibility | Needs |
| --- | --- | --- |
| `verified.verification` | `Verifier`, `VerificationResult`, `Expectations` | native |
| `verified.trust` | `TrustRegistry`, `TrustedKey` | native |
| `verified.contracts` | `WorkContract` | native |
| `verified.records` | `WorkPackage`, `WorkRecord`: the exact bytes | native for records |
| `verified.canonical` | `canonicalize`, `Digest` | native |
| `verified.signing` | `Signer`, `SigningAuthority`, `Ed25519Signer` | native for the in-memory signer |
| `verified.evidence` | `EvidenceSource`, `SignedEvidence`, `Record`, `Completeness` | native |
| `verified.work` | `Work`, `Claim`, `IssuedWork`, `DecisionIssuer`: the lifecycle | native to issue |
| `verified.work_unit` | `work_unit`, `WorkUnitScope` | native |
| `verified.instrumentation` | `WorkSession`, `TraceEvent`, `ExecutionTrace` | nothing |
| `verified.integrations.generic` | `verified_tool` | nothing |
| `verified.integrations.openai_agents` | `VerifiedRunHooks` | the `openai-agents` extra |
| `verified.integrations.langgraph` | `VerifiedCallbackHandler` | the `langgraph` extra |
| `verified._bridge` | The only importer of `verified._native` | |

Three entry points are independent of one another:

- **Verify only.** `Verifier`, `TrustRegistry`. No client, no session.
- **Produce evidence only.** `EvidenceSource`, `SigningAuthority`, a `Signer`.
- **Instrument only.** `WorkSession`, `verified_tool`. Records a trace without
  ever touching the native extension.

## Design rules

1. **No protocol rule in Python.** Python never canonicalizes, hashes for the
   protocol, checks a signature, evaluates a contract or orders a check. It
   builds JSON, calls the extension and wraps what comes back in typed,
   immutable values. A rule duplicated in Python could drift; a rule that is
   only in Rust cannot.
2. **One doorway.** Only `_bridge` imports the extension, lazily, on first
   use. Importing `verified` loads no native code, opens no file and makes no
   network call. A test checks this.
3. **No silent fallback.** Without the extension, native operations raise
   `NativeUnavailableError`. Nothing degrades to a weaker check.
4. **Results for outcomes, exceptions for operations.** A refused package, an
   incomplete verification and a contradicted claim are values. An unreadable
   file, an oversized input, a broken registry are exceptions.
   `RequirementNotMet` is raised only by `require_*`, at the caller's request.
5. **Bytes are kept.** A package is held as the bytes received and is never
   re-serialized. Consumers re-verify from bytes.
6. **Trust is an argument.** No default registry, no ambient credentials, no
   global state. The only context-local state is "the current session", which
   exists so that a decorated tool can find it.
7. **Immutable, explicit types.** Frozen dataclasses and enums. No Pydantic:
   the wire formats are validated by the Rust side, exactly, and a second
   schema layer would be a second definition of the protocol.
8. **No dependencies in the core.** Framework adapters are optional modules
   behind extras.

## Synchronous and asynchronous use

Verification and signing are CPU-bound and take well under a millisecond for
typical packages, so they are plain functions; call them from async code
directly. `WorkSession`, its turns and tool scopes are both `with` and
`async with` context managers, and `verified_tool` wraps `def` and `async def`
alike. Session state is tracked with `contextvars`, so concurrent sessions in
different tasks or threads are isolated.

The extension holds the GIL while it works. For very large packages (the
limit is 32 MiB) a caller that must keep an event loop responsive should
verify in a worker process.

## What the SDK deliberately is not

- Not a platform client. See [ecosystem boundaries](ecosystem-boundaries.md).
- Not a tracing backend or an observability product.
- Not a policy engine: contracts are data, evaluated by the shared evaluator.
- Not a billing or compliance application.
- Not a key store.
