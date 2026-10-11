# Security

## Status

`verified-python` is a developer preview of an SDK for a draft protocol. It
has **not** been independently security-reviewed or audited, and neither have
the upstream verification crates it binds. Do not treat a result from it as
the sole control for a consequential decision.

## Supported versions

Only the latest release.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Use GitHub's
private vulnerability reporting for this repository (**Security → Report a
vulnerability**). If the problem is in verification itself (canonical
encoding, signature checks, contract evaluation, check order), it is most
likely in [`dekrops/verified-cli`](https://github.com/dekrops/verified-cli);
report it there in the same way and mention this SDK.

Useful in a report: the package and registry involved (synthetic, please),
what was expected, what happened, and the output of `verified.build_info()`.

## What counts

- A package that verifies as `complete` and should have been refused, or a
  reproduced decision that differs from another conforming verifier's.
- A way to make `require_supported()` pass without a complete, reproduced
  `SUPPORTED`.
- A way to get a statement accepted for a source its key is not authorized
  for.
- Any silent fallback to a weaker check.
- Memory or resource exhaustion from a package within the stated limits.
- Key material appearing in logs, reprs, traces or errors.

## What the SDK does not protect against

Stated in full in the [trust model](docs/trust-model.md). In short: a source
that lies, a dishonest completeness statement, a compromised key backdating
statements, a relying party using the wrong registry, and replay of a package
across systems that share no state.

## Keys and fixtures

Every key in this repository is synthetic, derived from a published seed.
Anyone can sign with them. Never put one in a registry you rely on. No real
credentials, production secrets or customer data belong here; if you find
any, report it as a vulnerability.
