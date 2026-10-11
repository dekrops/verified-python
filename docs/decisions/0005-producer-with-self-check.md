# 0005. A producer in the binding crate, self-checked

Status: superseded. The producer was contributed to `dekrops/verified-cli`
as `verified_verifier::issue` (upstream ADR 0013, tag `v0.1.0`) and deleted
here. `rust/src/issue.rs` now only calls it. Kept as the record of why the
SDK carried one for its first commit.

## Context

The upstream crates verify packages and do not build them. Without a producer
the SDK could verify other people's packages and nothing else; the definition
of done asks for an agent workflow that ends in a verifiable package.

## Options

1. No producer; wait for upstream. Honest, and leaves most of the SDK inert.
2. Build packages in Python. Puts protocol layout, canonical ordering and
   commitments in Python: the thing ADR 0001 rules out.
3. Build packages in the binding crate, in Rust, from upstream's public
   pieces, and verify each one with the upstream verifier before returning it.

## Decision

Option 3. `rust/src/issue.rs` assembles `wvp-0.2` packages. Evaluation,
digests, statement reading and signing domains are upstream's. The
environment (spec §2), the decision object (§4) and the container are laid
out here. `assemble` returns a package only if `verified_verifier` reproduces
its decision completely under the caller's registry.

## Why this is safe enough

The verifier is the oracle. A producer bug can make issuing fail; it cannot
yield a package that a conforming verifier accepts with another decision.

## What it costs

A second copy of roughly 150 lines of layout that also exists in Agent
Compliance Center. It must track the specification.

## Ends when

Upstream exports a producer (proposal 1 in `ecosystem-boundaries.md`).
