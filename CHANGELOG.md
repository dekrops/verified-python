# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `verified.read_history`: reads work relations (work relation v1, a draft)
  against the records given with them, under your trust registry. A relation
  is a signed statement by which a ledger or an application says how the
  records of one unit of work are related. Each relation is reported as
  `CHECKED`, `STATED`, `CONTRADICTED` or `REFUSED`; a `HistoryReading` has
  no truth value, and reading verifies no record. The rules are upstream's
  `verified-history` crate; the 41 cases of the published corpus are
  reproduced.

### Fixed

- Wheels now carry `THIRD-PARTY-LICENSES.md`: the licenses and notices of the
  Rust crates the native extension links, generated from `rust/Cargo.lock`
  and checked in CI. The 0.1.0 wheels lacked them.
- `NOTICE` and the package metadata name the copyright holder as Krops GmbH,
  as `dekrops/verified-cli` and `dekrops/wvp` do.

### Added

- LangGraph adapter: `verified.integrations.langgraph.VerifiedCallbackHandler`,
  installed with the `langgraph` extra.

### Changed

- The native extension is built on `dekrops/verified-cli` `v0.1.3`, and the
  conformance corpus is `dekrops/wvp` at `46ccd1d`. From `v0.1.1`, the
  report `verify` returns is now produced by the upstream library
  (`Report::to_value`) instead of a copy of that mapping in this repository;
  its members are unchanged.
- A chain anchor is read by upstream's `Anchor::from_value`, which accepts
  only the form the conformance corpus writes.

## [0.1.0] - 2026-10-11

First developer preview.

### Added

- Offline verification of `wvp-0.1` and `wvp-0.2` packages (`Verifier`,
  `VerificationResult`), with relying-party expectations and work records.
- `TrustRegistry`, `WorkContract`, `WorkPackage`, `WorkRecord`, `Digest`,
  `canonicalize`.
- Evidence production with scoped authority: `EvidenceSource`,
  `SigningAuthority`, `Signer`, `Ed25519Signer`, `SignedEvidence`.
- Work lifecycle and `wvp-0.2` issuing: `Work`, `Claim`, `IssuedWork`,
  `DecisionIssuer`.
- Work-unit identity and nullifiers: `work_unit`, `WorkUnitScope`.
- Instrumentation: `WorkSession`, `verified_tool`, `ExecutionTrace`.
- OpenAI Agents SDK adapter: `verified.integrations.openai_agents`.
- Native extension over `dekrops/verified-cli` `v0.1.0` (`d270ae0`), the tag
  Agent Billing Center and Agent Compliance Center pin; packages are issued
  by its `verified_verifier::issue`.
- Conformance suite against `dekrops/wvp` at `c7c9de2`.

### Compatibility

WVP `wvp-0.1` (verify), `wvp-0.2` (verify, issue); Evidence Statement v1;
Work Contract Language 1; work-unit identity v1. Claim registration v1 is not
supported.
