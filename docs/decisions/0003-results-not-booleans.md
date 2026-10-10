# 0003. Verification returns a structured result, never a boolean

Status: accepted.

## Decision

`Verifier.verify` returns a `VerificationResult` for every package it could
examine, including refused ones. The result has no `valid` or `ok` member,
`bool(result)` raises `TypeError`, and `decision` is `None` unless a decision
was reproduced. Enforcement is opt-in and names its outcome:
`require_complete()`, `require_supported(issuer_signed=…)`,
`require_decision(…)`. Exceptions are reserved for operational failures.

`Verifier(trust=…)` has no default. Integrity-only verification is written as
`trust=None`.

## Why

A reproduced `CONTRADICTED` is a successful verification. Any single boolean
has to pick whether that is `True` or `False`, and either choice misleads
someone. Raising on `bool()` turns the most likely misuse, `if
verifier.verify(pkg):`, into an immediate error instead of a silent
acceptance.

What a package *states* (its recorded decision, its claimant) is kept under
`result.stated`, apart from what was verified.

## Cost

Slightly more to type than `if valid:`. That is the point.
