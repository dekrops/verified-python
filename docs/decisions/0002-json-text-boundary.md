# 0002. Bytes and JSON text across the native boundary

Status: accepted.

## Decision

Native functions take `bytes`/`str` and return `bytes` or JSON text. Rust
never walks Python objects; Python never builds protocol values. The JSON
returned by `verify` uses upstream's documented `verify --json` member names.

## Why

- The protocol's encoding has no floats, arbitrary-size integers and its own
  key order. Converting Python objects in Rust would need a second mapping of
  those rules. Text parsed by `verified-canonical` has exactly one.
- The facade is language-neutral and small enough to review in one sitting.
- One documented output shape for the command and for SDKs.

## Cost

A serialization round trip per call (microseconds for typical packages), and
typed errors travel as a `(code, message)` pair.
