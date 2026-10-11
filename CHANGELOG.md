# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
