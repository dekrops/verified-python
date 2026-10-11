# Decisions

Short records of choices that shape the SDK. Each says what was decided, why,
and what would change it.

| | Decision |
| --- | --- |
| [0001](0001-rust-backed-python-api.md) | An idiomatic Python API over a narrow Rust extension |
| [0002](0002-json-text-boundary.md) | Bytes and JSON text across the native boundary |
| [0003](0003-results-not-booleans.md) | Verification returns a structured result, never a boolean |
| [0004](0004-lifecycle-follows-the-protocol.md) | The work lifecycle follows the protocol; no `finalize()` from a claim |
| [0005](0005-producer-with-self-check.md) | A producer in the binding crate, self-checked (superseded: now upstream) |
| [0006](0006-explicit-signing-authority.md) | Signing authority is explicit and scoped; the SDK takes a signer |
| [0007](0007-instrumentation-is-not-evidence.md) | Instrumentation records execution and never creates evidence |
| [0008](0008-no-platform-client-yet.md) | No platform client in the first release |
| [0009](0009-no-pydantic-no-core-dependencies.md) | No Pydantic and no runtime dependencies in the core |
| [0010](0010-pin-upstream-by-revision.md) | Pin upstream crates and the corpus by commit |
