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
| **Duplicated implementations** of signing, canonicalization, contracts | The SDK calls upstream for all of them, issuing included: the producer first written here now lives upstream beside the verifier. |
| **Protocol ownership confusion** | `wvp` is pinned as a submodule and treated as the contract. Expectations are never edited. |
| **Confusing product boundaries** | No billing, compliance or platform logic; see the table above. |
| **Version drift** between consumers | The SDK pins the upstream tag that the applications pin, reports it at run time and on every result, and a test ties the pins together. |
| **Misleading verification** | The result type, `require_*`, `bool()` raising, `trust` without a default, `stated` kept apart from verified values. |
| **SDK proliferation** | The extension's surface is bytes and JSON text, so the same Rust facade can back a Node (napi) or WASM binding. See proposal 2. |
| **Distribution complexity** | One `abi3` wheel per platform covers every supported Python; wheels for Linux, macOS and Windows build in CI. |

## Proposed upstream changes

Proposals 1, 2 and 3 have been carried out upstream. The others are open, and
nothing else was changed in another repository.

1. **Done: a producer in `verified-cli`.** `verified_verifier::issue`
   (upstream ADR 0013) evaluates and lays out `wvp-0.2` packages with the
   verifier's own code. This SDK uses it. Compliance Center (`acc-wvp`) can
   now delete its producer.
2. **Done: a report-to-JSON function in a library crate.** The
   `verify --json` shape is the contract for SDKs, and was implemented only
   inside the binary. From `v0.1.1` the library states it
   (`Report::to_value`), and reads and writes chain anchors
   (`Anchor::from_value`, `Anchor::to_value`). This SDK's copies are deleted.
3. **Done: a tagged release and a shared pin.** Upstream is tagged
   from `v0.1.0`, with semantic versioning for the library crates and a stated
   convention that consumers exchanging packages pin the same tag.
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
not fit, or when the binding facade (proposal 2) is shared
by two languages. Until then a new repository would add a pin to manage
without removing one.
