# Rust and Python interop

## The boundary

The extension `verified._native` (crate `rust/`, built with PyO3 and maturin)
exposes eighteen functions. Every one takes `bytes` or `str` and returns
`bytes` or JSON text. No Python object is interpreted in Rust, and no
protocol value is constructed in Python.

| Function | Calls upstream |
| --- | --- |
| `verify` | `verified_verifier::inspect` (which runs `verify`) |
| `canonicalize`, `canonical_digest` | `verified_canonical::parse`, `Value::to_canonical_string`, `Value::digest` |
| `trust_registry` | `verified_verifier::Trust::from_value` |
| `contract_summary`, `evaluate_contract` | `verified_contract::Contract::read`, `Contract::evaluate` |
| `work_unit` | `verified_work_unit::{Scope, Identity, SecretKey}` |
| `statement_signing_input`, `payload_digest` | `verified_protocol::STATEMENT_DOMAIN`, `Value::digest` |
| `check_statement`, `verify_chain`, `admit` | `verified_verifier::evidence::{authenticate, verify_chain, admit}` |
| `assemble_package`, `decision_signing_input`, `attach_issuer_signature` | `verified_verifier::issue::{issue, decision_signing_input, countersign}` |
| `ed25519_public_key`, `ed25519_sign` | `ed25519-dalek`, the library the verifier uses |
| `build_info` | constants of the crates |

JSON text is the interchange format on purpose:

- The protocol's own value type (`verified_canonical::Value`) is used on the
  Rust side throughout. There is no `serde_json` and no float anywhere between
  Python and the verifier. A Python `float` is refused before it crosses.
- The surface is language-neutral. The same facade can sit behind a Node or
  WASM binding without redesign.
- It is easy to audit: `rust/src` is under 900 lines, most of it reading
  arguments and naming errors.

`verify` returns the member names documented in upstream's
`docs/sdk/json-output.md` for `verified verify --json`, plus `stated` (what
the package says about itself, from `inspect`) and `verifiedIssuerKeys`. The
raw JSON is available as `VerificationResult.raw`.

Errors that prevented an examination are raised as `NativeError(code,
message)` and translated in `_bridge` to typed exceptions. Protocol outcomes,
refusals included, are returned as data.

## What is reused, and what is not duplicated

Reused directly, by pinned revision, with no copy and no fork: canonical
encoding and digests; signing domains and signing input; trust registry
parsing and key decoding; all thirteen package checks; statement
authentication, chains and admission; the contract language's reader and
evaluator; work-unit identity, nullifier and key commitment; work record
computation and comparison; issuing `wvp-0.2` packages and countersigning
their decisions.

Not written in Python, deliberately: any of the above. Python formats
instants (a string format the verifier then validates), converts whole
numbers to the text the contract language uses, and reads display fields out
of an already-validated contract. Nothing else.

## Issuing

Packages are issued by `verified_verifier::issue`, the library that verifies
them. It evaluates the contract with the function the verifier uses, writes
the decision with the function the verifier compares against, and returns a
package only after verifying it under the issuer's registry. `rust/src/issue.rs`
maps the SDK's JSON parts onto its `Draft` and maps its errors back; it
decides nothing about a package's layout.

That module began in this repository. The first version of this SDK laid
packages out itself, because upstream had no producer, and checked each one
with the upstream verifier. The code was then contributed upstream, where it
could share the verifier's internals instead of repeating them, and was
deleted here ([decision 0005](../decisions/0005-producer-with-self-check.md)).

## Pinning and upgrades

The five crates are git dependencies pinned to the commit of an upstream tag
(`rust/Cargo.toml`, currently `v0.1.1`), locked in `rust/Cargo.lock`, built
with `--locked`. Upstream's library API follows semantic versioning from its
first tag, and asks consumers that exchange packages to pin the same tag.
Agent Billing Center and Agent Compliance Center record theirs in
`conformance/upstream.json`; this SDK compiles its pin into the extension.

To move the pin: change the five `rev` values and `UPSTREAM_REVISION` in
`rust/src/lib.rs`, run the full suite with the corpus required, update the
tables in `docs/protocol-compatibility.md`, and read the upstream pull
requests in between. One pull request, nothing else in it. Because the
verifier build is part of every result, a consumer that stores results can
see which verifier produced them.

## Packaging

- **One wheel per platform.** The extension is built against the stable ABI
  (`abi3-py311`), so one wheel serves CPython 3.11 and later.
- **Targets built in CI:** Linux x86-64 and aarch64 (manylinux and musllinux),
  macOS x86-64 and arm64, Windows x86-64.
- **Source distribution.** Building from the sdist needs a Rust toolchain
  (1.99+) and network access to fetch the pinned crates from GitHub. That is a
  real cost of git dependencies, and it goes away when upstream publishes
  crates.
- **No PyPy, no free-threaded build yet.** Neither is tested.
- **No wheel available** for a platform means installation from source. If
  the extension is absent at run time, native operations raise
  `NativeUnavailableError`.

Publishing is not set up to run automatically. `release.yml` builds and
checks artifacts; uploading to PyPI through trusted publishing is a manual,
environment-protected job that needs the project to be registered first.
