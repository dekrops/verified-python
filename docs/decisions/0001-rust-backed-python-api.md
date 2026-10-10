# 0001. An idiomatic Python API over a narrow Rust extension

Status: accepted.

## Context

Four ways to give Python developers WVP verification were considered.

| Option | For | Against |
| --- | --- | --- |
| A. PyO3 bindings to the upstream crates | One implementation of the rules; offline; fast | Wheels per platform; a Rust toolchain for source builds |
| B. Pure-Python models and orchestration over (A) | Idiomatic API, typing, docs | Needs (A) |
| C. Subprocess to the `verified` command | No native build | A binary to distribute and find; process cost per call; no issuing; errors as exit codes |
| D. An independent Python implementation | Simplest install | A fifth implementation of canonical encoding, signature checks and a three-valued evaluator, in security-sensitive code, to keep in step by hand |

Upstream had left the question open (its ADR 0007) and suggested wrapping the
command's JSON output.

## Decision

A and B together. A small extension binds the upstream crates directly; a
pure-Python package on top provides the API. No protocol rule is implemented
in Python.

C is not used, even as a fallback: a silent fallback from one mechanism to
another is how "verification succeeded" comes to mean two things. If the
extension is missing, native operations raise `NativeUnavailableError`.

D is rejected. Its one advantage, independence, is real: an independent
implementation agreeing on the corpus is stronger evidence about the
*specification* than a binding is. That is a job for a conformance
implementation, not for the SDK developers will depend on.

## Consequences

- The SDK's conformance results show that the binding preserves upstream
  behaviour, not that a second implementation agrees.
- Packaging is real work: see `rust-python-interop.md`.
- The extension is built against the stable ABI, so one wheel per platform.

## Would change if

Upstream publishes a WASM build with the same surface, which would allow a
no-compile install path with the same single implementation.
