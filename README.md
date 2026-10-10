# verified-python

The Python SDK for the [Work Verification Protocol](https://github.com/dekrops/wvp) (WVP).

> What did this agent do, under which authority, with what evidence, according
> to which contract, and can an independent party reproduce the result?

`verified-python` lets a Python agent system produce a portable, signed account
of a unit of work, and lets anyone verify it offline. Verification is performed
by the same Rust crates as the [`verified` CLI](https://github.com/dekrops/verified-cli),
bound natively; the Python layer adds an API, not a second implementation.

**Status: developer preview (0.1.0).** WVP is a draft in every version. This
SDK has not been security-audited, is not on PyPI yet, and its API will change.
Read [what is and is not supported](docs/protocol-compatibility.md) before
relying on it.

```text
Any agent. Any runtime. Independently verifiable work.
```

## Install

Not published yet. From a checkout, with a Rust toolchain (1.99+) and
[uv](https://docs.astral.sh/uv/):

```sh
git clone --recurse-submodules https://github.com/dekrops/verified-python
cd verified-python
uv sync            # builds the native extension
uv run pytest      # 250+ tests, including the WVP conformance corpus
```

Python 3.11 or later. The core package has no runtime dependencies.

## 1. How do I independently verify a package?

You hold a package file and a trust registry **you** chose. No account, no
network, no agent framework.

```python
from verified import Expectations, TrustRegistry, Verifier, WorkContract

examples = "examples/standalone-verification"
verifier = Verifier(
    trust=TrustRegistry.load(f"{examples}/trust.json"),  # yours, never the package's
    expect=Expectations(  # what you agreed to
        tenant="acme-synthetic",
        contract=WorkContract.load("examples/contracts/invoice-posting.json"),
    ),
)

result = verifier.verify(f"{examples}/contradicted.json")

print(result.verification_status)  # complete   <- the verification succeeded
print(result.decision)  # CONTRADICTED   <- the work did not
print(result.explain())
```

Those are two different facts, and the API never merges them:

| You want to know | Read |
| --- | --- |
| Is the file well formed and unaltered? | `result.integrity` |
| Is the evidence authentic under my registry? | `result.evidence_signatures`, `result.signer_authority` |
| Did every protocol check run and pass? | `result.verification_status` |
| What does the contract yield from the evidence? | `result.decision` (`None` unless reproduced) |
| Is that the outcome I need? | `result.require_supported()` |
| Did the sources tell the truth? | Nothing can tell you. `result.source_truthfulness` is always `not_established`. |

A result has no truth value (`bool(result)` raises), and there is no `valid`
flag. To enforce an outcome, say which one:

```python
from verified import RequirementNotMet, TrustRegistry, Verifier

verifier = Verifier(trust=TrustRegistry.load("examples/standalone-verification/trust.json"))

verifier.verify("examples/standalone-verification/supported.json").require_supported()

try:
    verifier.verify("examples/standalone-verification/undetermined.json").require_supported()
except RequirementNotMet as error:
    print(error)  # the reproduced decision is UNDETERMINED, not SUPPORTED
```

Without a registry (`Verifier(trust=None)`, which you must write out), the
result is `incomplete`: integrity only, no decision. The decision a package
carries is its issuer's claim until you reproduce it.

## 2. How do I instrument my Python agent?

Wrap the run in a `WorkSession` and decorate tools. No framework, event loop
or tracing backend is imposed; sync and async both work.

```python
from verified import WorkContract, WorkSession
from verified.integrations import verified_tool

contract = WorkContract.load("examples/contracts/invoice-posting.json")


@verified_tool(
    work_type="invoice.post",
    contract=contract,
    inputs=lambda invoice_id: {"invoice": invoice_id},
)
def post_invoice(invoice_id: str) -> str:
    return "accepted"  # what the ERP's API answered


with WorkSession(agent="invoice-agent", tenant="acme-synthetic") as session:
    with session.turn():
        post_invoice("INV-123")

(work,) = session.works
print(work.state)  # open
print([event.kind.value for event in session.events])
```

The tool returned, and **nothing is established**. The decorator recorded that
the call happened and opened a work item under the contract; it did not record
success. The work stays `open` until evidence from an identified source is
attached:

```text
OPEN ──attach(evidence)──▶ OPEN ──claim()──▶ CLAIMED ──issue(trust=…)──▶ ISSUED
                                                                           │
                             decision: SUPPORTED | CONTRADICTED | UNDETERMINED
```

`issue()` evaluates the contract and seals a package. With only the agent's
word, the decision is `UNDETERMINED`. The full flow, with a simulated ERP as a
separate party, is [`examples/invoice-posting`](examples/invoice-posting/invoice_agent.py).

An **OpenAI Agents SDK** adapter is included
(`verified.integrations.openai_agents.VerifiedRunHooks`); see
[agent runtime integration](docs/architecture/agent-runtime-integration.md).

## 3. How do I produce evidence without misrepresenting its authority?

Evidence is signed where the observation is made, by a key whose authority is
declared explicitly: one issuer, one tenant, named source systems.

```python
from verified import (
    Ed25519Signer,
    EvidenceSource,
    SigningAuthority,
    SigningAuthorityError,
    Subject,
)

signer = Ed25519Signer(key_id="erp-gateway-1", seed=bytes([7]) * 32)  # use a KMS in production
authority = SigningAuthority(
    key_id="erp-gateway-1",
    issuer="00000000-0000-4000-8000-0000000000e1",
    tenant="acme-synthetic",
    sources=["erp"],  # this key speaks for the ERP, and nothing else
)

gateway = EvidenceSource(system="erp", authority=authority, signer=signer)
posting = gateway.record(
    "posting",
    {"document": "DOC-1", "invoice": "INV-123", "amount": 125_000},  # EUR 1250.00 at scale 2
    subject=Subject(system="erp", kind="invoice", key="INV-123"),
)
print(posting.source, posting.key_id)

try:
    EvidenceSource(system="payments", authority=authority, signer=signer)
except SigningAuthorityError as error:
    print(error)  # not declared to speak for source 'payments'
```

The local check prevents mistakes. The security boundary is elsewhere: a
relying party's registry says which key may speak for which system, and its
verifier refuses a statement signed by any other key (`SOURCE_NOT_AUTHORIZED`).
An agent's key is authorized for the agent's runtime, so an agent cannot turn
"I posted the invoice" into "the ERP says it was posted".

A signature establishes who said something and that it was not altered. It
does not establish that it is true. See the [trust model](docs/trust-model.md).

## Six things that are not the same

| Thing | What it is | Who stands behind it | In this SDK |
| --- | --- | --- | --- |
| Execution telemetry | What a runtime logged about itself | Nobody; it is unsigned | `ExecutionTrace` |
| Agent claim | An assertion that work was done, against a contract | The claimant | `Claim` |
| Signed evidence statement | What an identified source says it observed | The signer, for the systems a registry authorizes | `SignedEvidence` |
| Verified decision | What the contract yields from authenticated evidence, reproduced | Whoever re-runs it: you | `VerificationResult.decision` |
| Package ("portable Work Record") | Claim, contract, evidence and decision in one sealed file | Its issuer, if it signed the decision | `WorkPackage` |
| Work record | The record of one verification of a package | The verifier that computed it | `WorkRecord` |

An *attestation* (a party signing that a verdict holds) appears in the protocol
only as the issuer's signature over a decision. Multi-claim attestation
bundles, as in Agent Compliance Center, are application formats and are not
part of this SDK.

## Examples

All run offline with synthetic data: `uv run python examples/<dir>/<script>.py`.

| Example | Shows |
| --- | --- |
| [`standalone-verification`](examples/standalone-verification/verify_packages.py) | A third party verifying three packages; all verify, one is supported |
| [`invoice-posting`](examples/invoice-posting/invoice_agent.py) | A custom agent loop, a tool, and an ERP gateway as a separate evidence source |
| [`chatbot-compliance`](examples/chatbot-compliance/support_chatbot.py) | Turn and session claims under separate contracts; the session is not the sum of its turns |
| [`enterprise-evidence`](examples/enterprise-evidence/order_gateway.py) | Scoped signing authority, a pluggable signer, and three relying parties |

## What is and is not here

Working, with tests: offline verification of `wvp-0.1` and `wvp-0.2` packages;
relying-party expectations and work records; trust registries; evidence
statements, chains and admission; Work Contract Language 1; work-unit identity
and nullifiers; issuing `wvp-0.2` packages; framework-independent
instrumentation; one framework adapter.

Not here: a client for the hosted Verified platform (it has no stable
service API to call yet); claim
registration v1; statement chaining when *producing* evidence; LangGraph and
Google ADK adapters; published wheels. Details and reasons are in the
[roadmap](docs/roadmap.md) and the
[compatibility assessment](docs/protocol-compatibility.md).

This SDK contains no billing, settlement or compliance rules, and does not
decide whether verified work is accepted, payable or compliant.

## Documentation

- [Architecture overview](docs/architecture/overview.md)
- [Ecosystem boundaries](docs/architecture/ecosystem-boundaries.md)
- [Rust and Python interop](docs/architecture/rust-python-interop.md)
- [Agent runtime integration](docs/architecture/agent-runtime-integration.md)
- [Protocol compatibility](docs/protocol-compatibility.md)
- [Trust model](docs/trust-model.md)
- [Roadmap](docs/roadmap.md)
- [Decisions](docs/decisions/README.md)

## Related repositories

- [`dekrops/wvp`](https://github.com/dekrops/wvp): the specifications and conformance vectors. Normative.
- [`dekrops/verified-cli`](https://github.com/dekrops/verified-cli): the Rust implementation this SDK binds, and the `verified` command.
- `dekrops/agent-billing-center`, `dekrops/agent-compliance-center`: reference applications built on verified work.
- `dekrops/verified`: the commercial Work Verification Platform. Not required by anything here.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). The conformance
corpus under `conformance/wvp` is a submodule with its own licenses.
