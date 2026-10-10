"""The work lifecycle follows the protocol's transitions and no others."""

from __future__ import annotations

import json
import threading
from datetime import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verified import (
    AgentIdentity,
    AssemblyError,
    ContractError,
    Decision,
    Digest,
    LifecycleError,
    MalformedInputError,
    Record,
    Verifier,
    Work,
    WorkContract,
    WorkState,
    WorkUnitScope,
    canonicalize,
    work_unit,
)

from ..conftest import Parties, make_parties


def test_a_claim_alone_never_yields_a_supported_outcome(parties: Parties) -> None:
    work = parties.work()
    states = [work.state]
    with pytest.raises(LifecycleError, match="no claim yet"):
        work.issue(trust=parties.trust)
    claim = work.claim()
    states.append(work.state)
    assert claim.evidence == ()
    assert claim.contract == parties.contract.digest
    issued = work.issue(trust=parties.trust)
    states.append(work.state)
    assert states == [WorkState.OPEN, WorkState.CLAIMED, WorkState.ISSUED]
    assert issued.decision is Decision.UNDETERMINED
    assert issued.issuer_check.is_complete


def test_transitions_happen_once_and_in_order(parties: Parties) -> None:
    work = parties.work()
    work.attach(parties.posting())
    work.claim()
    with pytest.raises(LifecycleError, match="already fixed"):
        work.claim()
    with pytest.raises(LifecycleError, match="only while work is open"):
        work.attach(parties.listing_complete())
    work.issue(trust=parties.trust)
    with pytest.raises(LifecycleError, match="already issued"):
        work.issue(trust=parties.trust)
    assert work.issued is not None


def test_issue_requires_a_registry(parties: Parties) -> None:
    work = parties.work()
    work.claim()
    with pytest.raises(TypeError):
        work.issue()  # type: ignore[call-arg]


def test_only_signed_evidence_can_be_attached(parties: Parties) -> None:
    work = parties.work()
    for not_evidence in ({"status": "posted"}, "posted", Record("posting", {"document": "D"})):
        with pytest.raises(TypeError, match="not evidence until an identified source signs it"):
            work.attach(not_evidence)  # type: ignore[arg-type]


def test_evidence_of_another_tenant_is_refused(parties: Parties) -> None:
    other = make_parties(tenant="another-tenant", seed=20)
    with pytest.raises(LifecycleError, match="another-tenant"):
        parties.work().attach(other.posting())


def test_inputs_must_be_the_contracts(parties: Parties) -> None:
    with pytest.raises(ValueError, match="declares the inputs"):
        Work.begin(
            contract=parties.contract, tenant=parties.tenant, claimant=parties.agent, inputs={}
        )
    with pytest.raises(TypeError, match="WorkContract"):
        Work.begin(
            contract="contracts/invoice-posting.json",  # type: ignore[arg-type]
            tenant=parties.tenant,
            claimant=parties.agent,
            inputs={"invoice": "INV-1"},
        )
    with pytest.raises(ValueError, match="UUID"):
        Work.begin(
            contract=parties.contract,
            tenant=parties.tenant,
            claimant="invoice-agent",
            inputs={"invoice": "INV-1"},
        )


def test_evidence_that_does_not_fit_the_contract_is_an_assembly_error(parties: Parties) -> None:
    misfit = parties.gateway.record(
        "posting", {"document": "D-1", "unexpected": "x"}, subject=parties.subject()
    )
    work = parties.work()
    work.attach(misfit).claim()
    with pytest.raises(AssemblyError) as raised:
        work.issue(trust=parties.trust)
    assert raised.value.code == "ENVIRONMENT_NONCONFORMING"
    assert work.state is WorkState.CLAIMED


def test_evidence_observed_after_evaluation_is_refused(parties: Parties) -> None:
    work = parties.work()
    work.attach(parties.posting()).claim()
    with pytest.raises(AssemblyError, match="INPUT_MISMATCH"):
        work.issue(trust=parties.trust, evaluated_at="2026-03-01T09:00:00Z")


def test_naive_times_are_refused(parties: Parties) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        parties.gateway.record(
            "posting",
            {"document": "D"},
            subject=parties.subject(),
            observed_at=datetime(2026, 3, 1, 10, 0, 0),
        )


def test_fractions_are_refused_not_rounded(parties: Parties) -> None:
    with pytest.raises(TypeError, match="whole number"):
        parties.gateway.record(
            "posting",
            {"document": "D", "amount": 12.5},  # type: ignore[dict-item]
            subject=parties.subject(),
        )
    with pytest.raises(TypeError, match="no fractional numbers"):
        canonicalize({"amount": 12.5})
    with pytest.raises(MalformedInputError):
        canonicalize(b'{"amount": 12.5}')


def test_the_same_statement_can_serve_several_claims(parties: Parties) -> None:
    posting = parties.posting()
    packages = []
    for _ in range(2):
        work = parties.work()
        work.attach(posting, posting).claim()
        packages.append(work.issue(trust=parties.trust))
    assert packages[0].package_id != packages[1].package_id
    assert all(item.decision is Decision.SUPPORTED for item in packages)


def test_concurrent_transitions_happen_exactly_once(parties: Parties) -> None:
    work = parties.work()
    work.attach(parties.posting())
    outcomes: list[str] = []

    def claim() -> None:
        try:
            work.claim()
            outcomes.append("claimed")
        except LifecycleError:
            outcomes.append("refused")

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("claimed") == 1


def test_a_contract_is_identified_by_its_digest(parties: Parties) -> None:
    document = parties.contract.to_dict()
    assert WorkContract.from_dict(document) == parties.contract
    assert parties.contract.requirement_ids == ("POSTED",)
    assert parties.contract.accepted_sources == {"posting": ("erp",)}
    reworded = WorkContract.from_dict(
        {**document, "identity": {"id": "invoice-posting", "version": "1.0.1"}}
    )
    assert reworded.digest != parties.contract.digest
    with pytest.raises(ContractError) as raised:
        WorkContract.from_dict({**document, "requires": []})
    assert raised.value.code in {"CONTRACT_ILL_FORMED", "CONTRACT_MALFORMED"}
    with pytest.raises(ContractError):
        WorkContract.from_dict({**document, "code": "return True"})


def test_work_unit_identity_survives_contract_versions_and_claims(parties: Parties) -> None:
    scope = WorkUnitScope("invoice-posting", "post", ("invoice",))
    key = bytes([9]) * 32
    first = work_unit(tenant=parties.tenant, scope=scope, inputs=parties.work().inputs, key=key)
    again = work_unit(tenant=parties.tenant, scope=scope, values=["INV-1"], key=key)
    assert first == again
    assert first.identity == '["work-unit-1","tenant-synthetic","invoice-posting","post",["INV-1"]]'
    assert first.nullifier is not None
    assert first.nullifier.startswith("hmac-sha-256:")
    different = [
        work_unit(tenant="another-tenant", scope=scope, values=["INV-1"], key=key),
        work_unit(tenant=parties.tenant, scope=scope, values=["INV-01"], key=key),
        work_unit(tenant=parties.tenant, scope=scope, values=["INV-1"], key=bytes([8]) * 32),
        work_unit(
            tenant=parties.tenant,
            scope=WorkUnitScope("invoice-posting", "reverse", ("invoice",)),
            values=["INV-1"],
            key=key,
        ),
    ]
    assert len({unit.nullifier for unit in [first, *different]}) == 5
    without_key = work_unit(tenant=parties.tenant, scope=scope, values=["INV-1"])
    assert without_key.nullifier is None
    assert without_key.key_commitment is None
    with pytest.raises(ValueError, match="exactly one"):
        work_unit(tenant=parties.tenant, scope=scope)


def test_a_billing_application_gets_identifiers_not_a_verdict(parties: Parties) -> None:
    """What a consumer such as Agent Billing Center re-verifies from."""
    work = parties.work()
    work.attach(parties.posting()).claim()
    issued = work.issue(trust=parties.trust, issuer=parties.issuer)
    result = Verifier(trust=parties.trust).verify(issued.package)
    assert result.package_id == issued.package_id
    assert result.package_id is not None
    assert result.package_id.removeprefix("wvp:sha-256:") == str(
        result.work_record.package_commitment  # type: ignore[union-attr]
    ).removeprefix("sha-256:")
    assert issued.package.byte_digest == Digest.of_bytes(issued.package.text)
    assert result.stated is not None
    assert result.stated.claimant == parties.agent.id
    assert result.stated.inputs == {"invoice": "INV-1"}
    assert result.verifier.startswith("verified-verifier-")
    assert result.trust_registry == parties.trust.byte_digest
    assert not hasattr(result, "billable")
    assert not hasattr(result, "accepted")


def test_agent_identity_is_stable_and_explicit() -> None:
    assert AgentIdentity("a", "1").id == AgentIdentity("a", "1").id
    assert AgentIdentity("a", "1").id != AgentIdentity("a", "2").id
    assert AgentIdentity("ab", "c").id != AgentIdentity("a", "bc").id
    given = "00000000-0000-4000-8000-000000000001"
    assert AgentIdentity("a", id=given).id == given


@settings(max_examples=100, deadline=None)
@given(
    st.recursive(
        st.none() | st.booleans() | st.integers() | st.text(),
        lambda children: (
            st.lists(children, max_size=4) | st.dictionaries(st.text(), children, max_size=4)
        ),
        max_leaves=20,
    )
)
def test_canonical_encoding_is_stable_and_ignores_key_order(value: object) -> None:
    once = canonicalize(value)
    assert canonicalize(once) == once
    assert json.loads(once) == value
    if isinstance(value, dict):
        assert canonicalize(dict(reversed(list(value.items())))) == once
    assert Digest.of_json(value) == Digest.of_json(once)


def test_a_json_string_is_not_mistaken_for_a_path(parties: Parties) -> None:
    with pytest.raises(TypeError, match="pass package text as bytes"):
        Verifier(trust=parties.trust).verify('{"files": []}')
