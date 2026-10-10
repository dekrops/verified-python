# 0006. Signing authority is explicit and scoped

Status: accepted.

## Decision

- The SDK takes a `Signer` (a key id and a `sign(bytes)` method), never a
  private key file. `Ed25519Signer` is an in-memory implementation for tests
  and development.
- Every signature is made under a `SigningAuthority`: one key, one issuer, one
  tenant, named sources. `EvidenceSource` refuses a system the authority does
  not name; `DecisionIssuer` requires the `wvp-decision` source.
- There is no ambient key, no environment variable and no default identity.

## Why

An agent process must not be able to produce, by accident or by default, a
statement that reads as the system of record's. The local check makes the
mistake loud. It is not the security boundary: a process can declare any
authority it likes. The boundary is the relying party's registry, and
`Work.issue` checks against the issuer's registry before sealing anything.

## Consequence

Setting up an evidence source takes four explicit values. That friction is
intended.
