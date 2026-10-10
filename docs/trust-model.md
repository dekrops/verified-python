# Trust model

Verification is only as meaningful as the assumptions it rests on. This page
states them, so that a result is never taken for more than it is.

## The one sentence

Under a trust registry **the relying party supplies**, a complete verification
establishes that a package is unaltered, who signed each piece of evidence,
that each signer was authorized for the system it speaks for, and that the
contract yields the stated decision from that evidence. It never establishes
that a source told the truth.

## Verification is not success

`verification_status` says how far the checks got. `decision` says what the
contract yields. They are independent.

| `verification_status` | `decision` | Meaning |
| --- | --- | --- |
| `complete` | `SUPPORTED` | Every requirement is established by accepted, authentic evidence |
| `complete` | `CONTRADICTED` | A requirement is conclusively false. **The verification succeeded; the work did not** |
| `complete` | `UNDETERMINED` | The evidence does not settle a requirement. Missing evidence lands here |
| `incomplete` | `None` | No registry was given. Integrity only. The decision in the package is its issuer's claim |
| `refused` | `None` | The package failed a check. `refusal.code` names the first |

A package whose claim is contradicted is still a fully verified package: it is
well formed, its signatures count, and anyone re-running the contract gets
`CONTRADICTED` too. That is the protocol working. An API that reported it as a
"failed verification" would make an honest negative look like a broken file,
and would tempt callers to treat "verification passed" as "the work was done".

For the same reason a result cannot be used as a boolean, and
`require_supported()` exists so that the outcome a caller needs is written
down at the call site.

## Who decides what

Two questions are answered by two different parties, and neither can answer
for the other.

- **The relying party's registry** says which key may speak for which source
  system, for which tenant, on behalf of which issuer, and when.
- **The contract** says which source systems count for which kind of record.

So a record can be authentic and still not count (signed by a key the registry
trusts, from a source the contract does not accept: it is listed in `ignored`),
and a record can name an accepted source and still be refused (signed by a key
the registry does not authorize for that source: `SOURCE_NOT_AUTHORIZED`).

## Assumptions, explicitly

| Assumption | Who makes it | What the SDK does |
| --- | --- | --- |
| The registry is the right one | The relying party | There is no default registry and no way to take one from a package. `Verifier(trust=…)` has no default; `trust=None` must be written out and yields `incomplete`. The registry's byte digest is on every result |
| A key belongs to who the registry says | The relying party | Nothing authenticates a registry. Protect it like any trust anchor |
| A key is used only by its owner | The key's owner | The SDK takes a `Signer`, never a key file. Custody is the caller's |
| The contract is the one that was agreed | The relying party | Pin it by digest with `Expectations(contract=…)`. A package about another contract version is then refused, not silently accepted |
| The package is about the right tenant and claim | The relying party | `Expectations(tenant=…, claim=…)` |
| The sources told the truth | Nobody can check | Reported as `source_truthfulness: not_established`, always |
| A completeness statement was honest | Nobody can check | See below |
| Asserted times are right | Nobody can check | See below |

## What is not established, ever

- **Source truthfulness.** A correctly signed statement can be false. The
  signature proves who said it.
- **Honest completeness.** "There is no posting" can only be concluded when a
  source declares its listing complete. If that declaration is false, the
  decision is wrong, and no verifier can tell. The SDK never infers absence
  from silence: without a completeness statement from an accepted source, an
  `exists` that finds nothing is `UNKNOWN`, and the decision is `UNDETERMINED`.
- **That a package holds everything.** A package discloses what it was
  evaluated against. It cannot show that nothing was left out, except through
  completeness statements.
- **When something happened.** `observedAt` is asserted by the signer.
- **Finality.** A decision answers one question: this contract, these inputs,
  this evidence. Later evidence can change it.
- **Acceptance, payment or compliance.** A reproduced `SUPPORTED` says the
  evidence establishes the contract's requirements. Whether the work is
  accepted, billable, settled or compliant is decided by other parties under
  other rules. A signed package is not by itself an agreement between anyone.

## Keys: scope, rotation, revocation

A registry record binds one key to one issuer, one tenant, a list of source
systems and a validity period (`validFrom`, optional `validUntil`, optional
`revokedAt`). A registry holds each key identifier and each public key once.

- **Scope** is enforced by the verifier per statement: tenant, issuer and
  source must all match the record.
- **Rotation** is adding a record for the new key and giving the old one a
  `validUntil`. Statements signed while the old key was valid keep verifying.
- **Revocation** is `revokedAt`. Statements whose asserted time is at or after
  it are refused (`KEY_NOT_VALID`).

The limit to state plainly: validity is judged at the statement's **asserted**
time. Whoever holds a revoked key can backdate a statement into the key's
validity period. The protocol has no trusted timestamp or freshness input. If
a key is compromised, revoking it does not protect statements "from before";
treat everything signed by that key as suspect, or remove the record.

## Tenants

A statement names its tenant, a key is trusted for one tenant, and a package's
evaluation is for one tenant. Evidence of another tenant is refused at
admission (`FOREIGN_TENANT_EVIDENCE`), and a key trusted for tenant A does not
verify a statement for tenant B (`TENANT_MISMATCH`). `Work.attach` refuses
foreign-tenant evidence early. None of this proves a package is about *your*
tenant: state that with `Expectations(tenant=…)`.

## Replay and duplicate work

Verification is offline and stateless. It cannot know that a package was
already presented, or that the same unit of work was already billed under
another claim or contract version.

`work_unit()` computes the protocol's work-unit identity and nullifier, so
that two claims about the same unit can be recognized as such across contract
versions. Recognizing them requires state with a first-write-wins rule, which
belongs to whoever settles. This SDK keeps no such state and does not say
whether a unit was used before.

## Signing authority in this SDK

An agent process does not hold trusted credentials merely by running.

- Signatures are produced only through an explicit `Signer`, scoped by an
  explicit `SigningAuthority`.
- `EvidenceSource` refuses, before signing, to speak for a system its
  authority does not name, and `DecisionIssuer` requires the `wvp-decision`
  source. These are guards against mistakes.
- A process can lie about its own authority. It then produces a statement that
  relying parties refuse, and `Work.issue` refuses to seal it under the
  issuer's registry. The registry is the boundary, and a source cannot write it.
- `WorkSession.trace_evidence` signs a trace as an `AgentTrace` statement from
  the runtime's own system. It can be authentic. It still says only what the
  agent says.

## Malformed and hostile input

The package parser is the shared Rust one: bounded size (32 MiB by default,
lower with `max_bytes`), depth, value count and integer length. Exceeding a
bound is a `ResourceLimitError`, deliberately not a refusal: the input was not
examined. Malformed input of any kind is a refusal or an error and never a
partial result. Text from a package is untrusted input to whatever reads it
next; the SDK passes it through unchanged and does not interpret it.

## Offline verification without the extension

If the native extension cannot be loaded, verification raises
`NativeUnavailableError`. There is no pure-Python fallback and no weaker mode.
