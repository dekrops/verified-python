# Contributing

## Setup

You need Rust 1.99+ (`rustup`), [uv](https://docs.astral.sh/uv/) and git.

```sh
git clone --recurse-submodules https://github.com/dekrops/verified-python
cd verified-python
uv sync                      # creates .venv and builds the extension
```

After changing Rust code, rebuild with `uv sync --reinstall-package verified-python`.

## The gate

Everything CI runs, locally:

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
VERIFIED_CONFORMANCE_REQUIRED=1 uv run pytest
(cd rust && cargo fmt --check && cargo clippy --locked -- -D warnings)
```

The adapter tests need the optional framework:
`uv run --group adapters pytest tests/integration`.

## Rules that are not negotiable

1. **No protocol logic in Python.** If a change needs to canonicalize, hash
   for the protocol, check a signature, evaluate a contract or order a check,
   it calls upstream through the extension. If upstream cannot do it, open an
   issue there and document the gap here.
2. **Conformance vectors are never edited.** If the SDK disagrees with a
   vector, the specification is investigated. A vector that cannot run is
   named in `docs/protocol-compatibility.md` and marked as an expected
   failure; it is never counted as passing.
3. **No silent fallback** from complete verification to anything weaker.
4. **No boolean for a verification.** New result fields are properties read
   one at a time.
5. **Synthetic data only.** No real keys, tenants, customers or documents in
   tests, examples or docs.
6. **Say what is not supported.** An adapter extra is listed in
   `pyproject.toml` only when it has integration tests against the real
   framework. Documentation claims are limited to what tests exercise.
7. **Boundaries.** Billing, settlement and compliance rules belong in the
   applications. See `docs/architecture/ecosystem-boundaries.md`.

## Changing the upstream pin

One pull request that changes the five `rev` values in `rust/Cargo.toml`,
`UPSTREAM_REVISION` in `rust/src/lib.rs`, `rust/Cargo.lock`, and the tables in
`docs/protocol-compatibility.md`, after reading the upstream changes in
between. Nothing else in it.

## Versioning and stability

Semantic versioning, with the usual pre-1.0 caveat: minor versions may break.
Public API is what `verified.__all__` and `verified.integrations` export.
Modules and names starting with an underscore, and `VerificationResult.raw`'s
exact contents, are not. Protocol compatibility is stated separately from the
SDK version, in `docs/protocol-compatibility.md`.

## License

By contributing you agree that your contribution is licensed under
Apache-2.0.
