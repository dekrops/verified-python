# Ecosystem boundaries

The SDK is useful only if it makes the ecosystem more coherent, not if it
becomes a fifth place where the protocol is defined.

## Who owns what

| Repository | Owns | Never owns |
| --- | --- | --- |
| `wvp` | Specifications, versions, vectors, conformance rules. **Normative** | Any implementation |
| `verified-cli` | The public Rust crates (canonical encoding, protocol types, contract language, verifier, work-unit identity) and the `verified` command | Whom to trust, acceptance, a ledger |
| **`verified-python`** | The Python API, the native binding, typed models, instrumentation primitives, optional framework adapters | Protocol rules, billing or compliance logic, a platform, key custody |
| future `verified-typescript` | The same, for TypeScript | The same |
| `verified` | The commercial platform: evidence infrastructure, tenant governance, ledger, registry, operations | Being a required trust anchor |
| `agent-billing-center` | Billing agreements, acceptance, eligibility, invoices, settlement uniqueness | A second verifier |
| `agent-compliance-center` | Policy packs, result mapping, attestation bundles, replay UI | A second evaluator |
| `beverified-ai` | Product discovery and developer entry point | Technical definitions |

Dependencies point one way: applications depend on the SDK or the crates; the
SDK depends on the crates; the crates depend on the specification. Nothing
here depends on the platform, at build time or at run time.

## Where this SDK stops

| Request | Answer |
| --- | --- |
| "Tell me if this work is billable" | No. The SDK returns the reproduced decision, the identifiers a billing application compares, and the exact bytes. Eligibility, acceptance, invoicing and settlement are separate states owned by the billing application. |
| "Tell me if this session is compliant" | No. The SDK returns one decision per claim. Mapping decisions to PASS or FAIL, wording reasons, and bundling a session's claims are the compliance application's. |
| "Was this unit already billed?" | No. The SDK computes the unit's identity and nullifier. Uniqueness needs shared state, which is the settling party's. |
| "Give me a default trust registry" | No. |
| "Sign as the ERP from inside my agent" | Not in a way a relying party accepts. |
| "Submit this to the Verified platform" | Not yet. See below. |

The test for a feature: would a developer who bills nothing, runs no chatbot
and has no Verified account want it? If not, it belongs in an application.

## The platform client that is not here

A `Client` was part of the original sketch for this SDK. It is not built,
because the platform does not yet offer a stable, versioned API with service
credentials for submitting claims and evidence. What it accepts today is a
finished `wvp-0.2` package, which this SDK can already produce as a file.

When the platform publishes a versioned API with service credentials, a
client belongs in `verified.platform`, as an optional module that imports its
HTTP dependency lazily. It must not become a dependency of verification or
instrumentation.

## Risks, and what this repository does about each

| Risk | Mitigation here |
| --- | --- |
| **Semantic divergence** between Scala, Rust, Python and applications | One implementation of the rules (the Rust crates), bound not rewritten. The published corpus runs in CI through the Python API. |
| **Duplicated implementations** of signing, canonicalization, contracts | The SDK calls upstream for all of them. The one piece it had to write, the package producer, is in Rust beside the verifier, self-checked on every use, and proposed upstream. |
| **Protocol ownership confusion** | `wvp` is pinned as a submodule and treated as the contract. Expectations are never edited. |
| **Confusing product boundaries** | No billing, compliance or platform logic; see the table above. |
| **Version drift** between consumers | One pinned revision, reported at run time and on every result; a test ties the pins together. Still open across repositories: see proposal 3. |
| **Misleading verification** | The result type, `require_*`, `bool()` raising, `trust` without a default, `stated` kept apart from verified values. |
| **SDK proliferation** | The extension's surface is bytes and JSON text, so the same Rust facade can back a Node (napi) or WASM binding. See proposal 2. |
| **Distribution complexity** | One `abi3` wheel per platform covers every supported Python; wheels for Linux, macOS and Windows build in CI. |

## Proposed upstream changes

None of these is implemented here, and nothing was changed in another
repository.

1. **A producer in `verified-cli`** (a `verified-producer` crate, or
   `verified_verifier::assemble`): build the environment of WVP v0.2 §2, the
   decision document of §4, and the container. Today Compliance Center
   (`acc-wvp`) and this SDK (`rust/src/issue.rs`) each do it by hand. With it,
   both delete code and a producer can no longer disagree with the verifier.
   Smallest useful step: make `environment` and `decision_document` public.
2. **A report-to-JSON function in a library crate.** The `verify --json`
   shape is documented as the contract for SDKs but is implemented inside the
   binary. This SDK re-implements the mapping (`rust/src/report.rs`).
   Exporting it (`verified_verifier::report_json`, or a small `verified-json`
   crate) gives every binding the same output for free.
3. **A tagged release and a shared pin.** Three consumers pin three
   revisions. A first tag, plus a `conformance/upstream.json` convention that
   all consumers share (Billing Center and Compliance Center already have
   one), turns drift into a visible diff.
4. **Typed accessors on `Contract`**: declared inputs, kinds, accepted
   sources, requirement identifiers, policy parameters. Consumers currently
   read them from raw JSON.
5. **`Instant` formatting, `Trust::from_bytes`, and an SPKI helper.** Small
   conveniences every consumer has re-written.
6. **In the protocol:** a freshness or trusted-time input for key validity;
   a way to bind a turn claim to its session claim; a multi-claim object. All
   three are protocol changes, to be made in `wvp`, not worked around in an SDK.
7. **For the platform:** service credentials and a versioned API before any
   client is written.
8. **Naming:** decide whether "Work Record" means the file or the record of a
   verification, and use one meaning on the site, in the specifications and in
   SDK type names.

## When to extract a shared core

Not yet. The crates already live in one public repository and can be pinned
by revision. Extraction into a separately versioned `verified-core` becomes
worth its cost when a second SDK needs releases on a cadence the CLI's does
not fit, or when the binding facade (proposal 2 plus the producer) is shared
by two languages. Until then a new repository would add a pin to manage
without removing one.
