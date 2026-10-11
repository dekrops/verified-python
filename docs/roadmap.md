# Roadmap

An honest account of where this is, in three horizons. Nothing below is a
commitment to a date.

## Now (0.1, this repository)

Working and tested:

- **Offline verification** of `wvp-0.1` and `wvp-0.2` packages through the
  shared Rust verifier, with structured results that keep refusal,
  incompleteness and the reproduced decision apart.
- **Typed models**: trust registries, contracts, evidence, claims, packages,
  work records, verification results.
- **Evidence production** with explicit, scoped signing authority and a
  pluggable signer.
- **A work lifecycle** (`OPEN`, `CLAIMED`, `ISSUED`) that issues `wvp-0.2`
  packages, each checked by the shared verifier before it is returned.
- **Work-unit identity** and nullifiers.
- **Generic agent instrumentation**: sessions, turns, tools, traces; sync and
  async.
- **Two framework adapters**: OpenAI Agents SDK and LangGraph.
- **Conformance**: the published corpus for canonical encoding, both package
  versions, the contract language, work-unit identity and evidence statements.
- **Packaging foundations**: maturin, one `abi3` wheel per platform, CI for
  lint, types, tests, conformance and wheels.

Known gaps at this horizon: no security review; claim
registration not bound; no platform client; source builds need Rust and
network access.

## Next

In rough order of leverage:

1. **Settle the bare name.** Wheels are published as `verified-python`. An
   unrelated placeholder owns `verified` on PyPI; a PEP 541 request asks for
   it, so that `pip install verified` cannot install something else.
2. **More framework adapters**: Google ADK next, with integration tests
   against the real framework before the extra is listed. For LangGraph:
   streaming, subgraphs and resumed runs.
   An MCP server-side helper for tools that open work.
3. **Richer evidence producers**: statement chains with a pluggable state
   store; a KMS signer example; batch signing.
4. **Claim registration v1**: bind the existing Rust library; run its 123
   vectors.
5. **Platform service integration**, once the platform has a versioned API
   and service credentials: submit packages, fetch records. Optional module.
6. **Issuing work relations.** The protocol now has a multi-claim object:
   work relation v1 (draft), whose `groups` relation says that packages or
   work records belong to one group. This SDK reads relations
   (`verified.read_history`); issuing one, as an evidence statement signed
   under an application's own source, is next. Detached application
   signatures under caller-owned domains remain open.
7. **Release the GIL** during verification, and an `async` convenience, if
   measurements on large packages justify it.
8. **Documentation site** (mkdocs-material) with API reference generated from
   the docstrings.

## Later

- **Cross-language harmonization.** A `verified-typescript` with the same
  result model and the same names, backed by the same Rust facade through
  napi or WASM, and a shared conformance report format so that every SDK
  publishes the same table.
- **Shared verifier crate extraction**, if and when two SDKs need the
  binding facade on a release cadence the CLI's repository does not fit. Not
  before; see [ecosystem boundaries](architecture/ecosystem-boundaries.md).
- **Protocol work that SDKs should not paper over**: trusted time for key
  validity, a checked binding between a session claim and its turn claims,
  selective disclosure of evidence. These belong in `wvp`.
- **Broader adoption**: adapters maintained with or by framework authors,
  and evidence gateways for common systems of record maintained by those who
  operate them.

## Non-goals

A hosted service, a policy engine, billing or settlement logic, compliance
verdicts, a key management system, and a tracing backend.
