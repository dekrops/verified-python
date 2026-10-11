# Protocol compatibility

The Work Verification Protocol is a **draft** in every version. This page
states what this SDK implements, what it was measured against, and what it
found when it looked at the rest of the ecosystem.

## What this build is made of

| | |
| --- | --- |
| SDK | `verified-python` 0.1.0 |
| Verification crates | [`dekrops/verified-cli`](https://github.com/dekrops/verified-cli) `v0.1.3`, commit `519a2d200a05a6778f427cfeee14b5b7aafd277d`: `verified-history`, `verified-canonical`, `verified-protocol`, `verified-contract`, `verified-verifier`, `verified-work-unit` |
| Conformance corpus | [`dekrops/wvp`](https://github.com/dekrops/wvp) at `46ccd1d7c34d3a92e13a59f9235120f8d37395d7`, as the submodule `conformance/wvp` |
| Python | 3.11 to 3.14 (one `abi3` extension) |

`verified.build_info()` reports the same revision at run time, every
`VerificationResult` carries it as `verifier`, and a test fails if the pins in
`rust/Cargo.toml`, the extension and this page disagree.

## Supported

| | `wvp-0.1` | `wvp-0.2` |
| --- | --- | --- |
| Offline verification, all thirteen checks | yes | yes |
| Canonical encoding `verified-json-v1` | yes | yes |
| Relying-party expectations (tenant, contract digest, claim) | not defined by the protocol; asking is an error | yes |
| Work record: computed, and compared with one supplied | not defined; asking is an error | yes |
| Issuing a package | **no** | yes |
| Issuer signature over the decision | verify only | verify and sign |

Also, outside packages: evidence statements (sign, read, authenticate),
statement chains (verify), admission, Work Contract Language 1 (read, and
evaluate through package assembly), work-unit identity v1 (identity,
nullifier, key commitment).

And, as a draft: work relation v1, reading only (`verified.read_history`).
Given relations and the records they name, it reports each relation as
checked, stated, contradicted or refused, whether a registered claim is a
package's claim, and each stream's completeness. It verifies no record, and
this SDK does not yet issue relations.

## Measured against the corpus

Run on 2026-10-11 by `tests/conformance/test_corpus.py`, through the public
Python API where one exists. Every expectation is compared in full, never by
refusal code alone. CI runs it with `VERIFIED_CONFORMANCE_REQUIRED=1`, so a
missing corpus fails instead of skipping.

| Corpus | Result |
| --- | --- |
| `canonical-hash-v1.json` | 12 of 12 valid cases reproduce bytes and digest; 5 of 5 invalid cases refused |
| `wvp/v0.1`, 26 vectors | 26 reproduced: refusal code, or decision, statement count, integrity and issuer-signature state |
| `wvp/v0.2`, 28 vectors | 28 reproduced: as above, plus contract summary and the value of every requirement |
| `wvp/v0.2/expectations.json`, 7 cases | 7 reproduced |
| The two worked examples beside the specifications | Both verify completely as `SUPPORTED` |
| `work-contract/v1`, 82 case files and 5 differential batches | 641 cases reproduced, from 81 case files and the 5 batches. 1 case file cannot be represented (below) |
| `work-unit/v1/vectors.json` | 3 of 3 key commitments and 10 of 10 identities and nullifiers |
| `evidence-statement/v1`, 39 vectors | 39 reproduced: 17 statement, 13 chain, 9 admission. **Not compared:** `verificationResultSha256` and `verificationStatus` of the 3 accepted admissions, which are the platform's result and are not computed by the shared crates |
| `work-relation/v1/vectors.json`, 41 cases | 41 reproduced: the whole reading of each, as the shared reader states it |
| `claim-registration/v1` (163 cases in seven files) | **Not run.** Claim registration is not bound in this release (see below) |

`72-scale-not-whole` gives a type a fractional `scale`. `verified-json-v1` has
no fractions, so the shared reader refuses the file's text before any contract
is read, as upstream documents. It is marked as an expected failure and is not
counted as conforming.

Agreement on a corpus is evidence of conformance, not proof. And since this
SDK calls the same crates as the Rust implementation, passing here shows that
the binding preserves their behaviour. It is not an independent
implementation agreeing with them.

Beyond the corpus, the three packages under
`examples/standalone-verification`, issued by this SDK, were verified with the
upstream `verified` binary and give the same outcome, decision and issuer
signature state.

## Not supported, and why

| | State | Reason |
| --- | --- | --- |
| Claim registration v1 (agreements, receipts, registry log, audit, disputes) | Not bound | The Rust library exists at the pinned revision. It is a separate protocol with its own trust configuration, and no registry service is deployed to exercise it against. Binding it is mechanical and is on the roadmap. |
| Statement chains when producing evidence | Not offered | `EvidenceSource` signs unchained statements (`"chain": null`). A chain needs durable per-stream state (the last sequence and digest), which belongs to the source's deployment. Chains from others can be verified. |
| Issuing `wvp-0.1` | Not offered | `wvp-0.1` names a fixed evaluator; new work should use contracts as data. |
| Platform client (`Client`) | Not built | See the assessment below. |
| Freshness or revocation *at verification time* | Not in the protocol | A key's validity is judged at the statement's asserted time, which its signer chose. |
| Registered-claim unit check | Not bound | Part of claim registration. |

## Readings and limits inherited from upstream

This SDK takes the upstream implementation's documented readings of the
specification as they are, including: duplicate object keys are refused;
base64 must be canonical; Ed25519 verification is strict and a registry
holding a small-order key is refused when loaded; a registry may omit
`validUntil` and `revokedAt` but may not contain unknown members; integers
beyond 4096 digits and packages beyond 32 MiB are not examined (an error, not
a refusal). The list is in upstream's
[`docs/protocol/compatibility.md`](https://github.com/dekrops/verified-cli/blob/main/docs/protocol/compatibility.md).

One convention is this SDK's own: a package *file* may end with exactly one
line end, which is the file's and not the package's, as in the `verified`
command. `Verifier.verify(path)` applies it; `Verifier.verify(bytes)` takes
the text itself and is strict.

## Architectural compatibility assessment

Made on 2026-10-10 by reading code and tests, not READMEs.

### `dekrops/wvp` (public)

Specifications and vectors, exported byte for byte from the platform
repository with a provenance file. The export is manual: nothing checks that
the public copy matches the platform's latest specifications, and
claim-registration changed in the platform after the last publication.
**Consequence:** this SDK pins a commit of `wvp` and treats it as normative.

### `dekrops/verified-cli` (public, Apache-2.0)

Five library crates and a binary. Verification is complete for both protocol
versions and passes the corpus. When this SDK was first written the library
had no producer, no tag and an API declared unstable; its own ADR 0007
anticipated a first SDK wrapping the command's JSON output and left "PyO3 or
pure Python" open. Since then it has gained `verified_verifier::issue` (its
ADR 0013), contributed from this SDK's first producer; tags, from
`v0.1.0`, with a compatibility policy for the library crates; and, in
`v0.1.1`, the `verify --json` shape as a library function
(`Report::to_value`). **Consequence:** this SDK binds the crates directly at
a tag, returns the report as the library states it so there is one contract,
and issues packages through the upstream producer.

### `dekrops/agent-billing-center`

Depends on the same crates by pinned git revision (`ad33276…`). It never
accepts a verdict: it re-verifies from the exact package bytes under its own
registry with mandatory expectations, then applies its own rules.
**Consequence:** what a billing application needs from this SDK is exact
bytes and identifiers, not a "billable" flag. `WorkPackage` keeps bytes
untouched; a result exposes the package identifier, contract digest, stated
claimant and inputs, verified issuer keys and the verifier build; `work_unit`
computes the same identity and nullifier. A test pins this.

### `dekrops/agent-compliance-center`

Pins a third revision (`ab74d41…`). Each turn and each session is its own
`wvp-0.2` package under its own contract; nothing derives the session's
result from the turns'. It contains its own producer (`acc-wvp`), including a
re-implementation of the environment construction, written before upstream
had one.
Its session-level attestation bundle is an application format.
**Consequence:** this SDK exposes generic turn and session primitives and a
producer, and does not copy the policy pack, the PASS/FAIL mapping or the
bundle. The chatbot example reproduces the turn/session independence with two
small contracts of its own.

### `dekrops/verified` (proprietary)

The platform does not yet offer what a client library needs: a stable,
versioned API with service credentials for submitting claims and evidence.
The protocol write it does have is accepting a finished `wvp-0.2` package,
which matches the published specification ("no flow in the product produces
v0.2 packages; they are submitted").
**Consequence:** there is no honest platform client to write yet. This
release ships none, and nothing in it depends on the platform. No platform
source is included in this repository.

### `dekrops/beverified-ai`

Uses "Work Record" for the sealed file and "numbered conditions" for what
`wvp-0.2` calls requirements. The protocol calls the file a *package* and
reserves *work record* for the record of one verification. This SDK follows
the protocol in its type names (`WorkPackage`, `WorkRecord`) and says so
wherever the difference could mislead. The site does not mention an SDK.

### Three things the assessment found that matter beyond this SDK

1. **Three consumers, three pins.** Billing Center, Compliance Center and this
   SDK pinned three different revisions of the same crates. Upstream now
   tags its releases and states a convention that consumers exchanging
   packages pin the same tag. All three moved to `v0.1.0`; this SDK is on
   `v0.1.3`, the third patch release, whose library API only grew.
2. **Two producers.** Compliance Center and this SDK each built packages by
   hand. The producer is now upstream and this SDK uses it. Compliance
   Center can delete its own.
3. **The name `verified` is taken on PyPI** by an unrelated distribution.
   `verified-python` is free as a distribution name, but two distributions
   providing a top-level `verified` package cannot be installed together.
   The other project is a single template-only `0.0.0` release from 2025.
   The decision taken: ship as `verified-python` with `import verified`, and
   request the bare name under PEP 541.
