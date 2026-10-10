"""What a verification result may and may not be taken to mean.

These tests pin security semantics, not API shape. A change that makes one of
them fail is a change in what the SDK lets a developer believe.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verified import (
    AssemblyError,
    Decision,
    DecisionIssuer,
    Ed25519Signer,
    EvidenceSource,
    Expectations,
    NativeUnavailableError,
    PropertyStatus,
    RequirementNotMet,
    ResourceLimitError,
    SigningAuthority,
    SigningAuthorityError,
    TrustRegistry,
    TrustRegistryError,
    UnsupportedOperationError,
    VerificationStatus,
    Verifier,
    WorkContract,
    WorkPackage,
    _bridge,
)

from ..conftest import Parties, make_parties
from ..tamper import component, edit, edit_and_reseal


def supported(parties: Parties, *, signed: bool = False) -> WorkPackage:
    work = parties.work()
    work.attach(parties.posting(), parties.listing_complete()).claim()
    return work.issue(trust=parties.trust, issuer=parties.issuer if signed else None).package


def undetermined(parties: Parties) -> WorkPackage:
    work = parties.work()
    work.claim()
    return work.issue(trust=parties.trust).package


def contradicted(parties: Parties) -> WorkPackage:
    work = parties.work()
    work.attach(parties.listing_complete()).claim()
    return work.issue(trust=parties.trust).package


# --- verification is not success ---------------------------------------------


def test_the_three_decisions_are_all_complete_verifications(parties: Parties) -> None:
    verifier = Verifier(trust=parties.trust)
    for package, decision in (
        (supported(parties), Decision.SUPPORTED),
        (undetermined(parties), Decision.UNDETERMINED),
        (contradicted(parties), Decision.CONTRADICTED),
    ):
        result = verifier.verify(package)
        assert result.verification_status is VerificationStatus.COMPLETE
        assert result.decision is decision
        assert result.require_complete() is result


def test_require_supported_refuses_contradicted_and_undetermined(parties: Parties) -> None:
    verifier = Verifier(trust=parties.trust)
    verifier.verify(supported(parties)).require_supported()
    for package in (contradicted(parties), undetermined(parties)):
        result = verifier.verify(package)
        with pytest.raises(RequirementNotMet) as raised:
            result.require_supported()
        # The handler can still tell what happened.
        assert raised.value.result.is_complete
        assert raised.value.result.decision is not Decision.SUPPORTED


def test_a_result_is_never_a_boolean(parties: Parties) -> None:
    result = Verifier(trust=parties.trust).verify(supported(parties))
    with pytest.raises(TypeError, match="no truth value"):
        bool(result)
    assert not hasattr(result, "valid")
    assert not hasattr(result, "ok")
    assert not hasattr(result, "verified")


def test_source_truthfulness_is_never_established(parties: Parties) -> None:
    for trust in (parties.trust, None):
        result = Verifier(trust=trust).verify(supported(parties, signed=True))
        assert result.source_truthfulness.status is PropertyStatus.NOT_ESTABLISHED
        assert "source truthfulness   NOT established" in result.explain()


def test_missing_evidence_is_undetermined_never_contradicted_or_supported(
    parties: Parties,
) -> None:
    # A posting for another invoice, and no statement that the listing is
    # complete: nothing says the claimed invoice was not posted.
    work = parties.work("INV-1")
    work.attach(parties.posting("INV-2", "D-2")).claim()
    assert work.issue(trust=parties.trust).decision is Decision.UNDETERMINED


# --- trust is the relying party's --------------------------------------------


def test_without_a_registry_nothing_but_integrity_is_established(parties: Parties) -> None:
    result = Verifier(trust=None).verify(supported(parties, signed=True))
    assert result.verification_status is VerificationStatus.INCOMPLETE
    assert result.integrity.established
    assert result.decision is None
    assert result.evidence_signatures.status is PropertyStatus.NOT_CHECKED
    assert result.signer_authority.reason == "no_trust_registry"
    assert result.issuer_signature.status is PropertyStatus.NOT_CHECKED
    assert result.verified_issuer_keys is None
    # The package says SUPPORTED. That is only what it says.
    assert result.stated is not None
    assert result.stated.recorded_decision == "SUPPORTED"
    with pytest.raises(RequirementNotMet, match="incomplete"):
        result.require_supported()
    with pytest.raises(RequirementNotMet, match="incomplete"):
        result.require_complete()


def test_trust_must_be_stated_and_must_be_a_registry(parties: Parties) -> None:
    with pytest.raises(TypeError):
        Verifier()  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="TrustRegistry"):
        Verifier(trust=parties.trust.to_dict())  # type: ignore[arg-type]


def test_a_key_the_relying_party_does_not_hold_is_refused(parties: Parties) -> None:
    stranger = make_parties(seed=40)
    result = Verifier(trust=stranger.trust).verify(supported(parties))
    assert result.refusal is not None
    assert result.refusal.code == "SIGNATURE_INVALID"  # same key id, another key
    without_gateway = TrustRegistry.from_keys(
        [key for key in parties.trust.to_dict()["keys"] if key["keyId"] != "erp-gateway-1"]
    )
    result = Verifier(trust=without_gateway).verify(supported(parties))
    assert result.refusal is not None
    assert result.refusal.code == "UNKNOWN_KEY"
    assert result.decision is None


def registry_with(parties: Parties, key_id: str, **changes: object) -> TrustRegistry:
    keys = parties.trust.to_dict()["keys"]
    for key in keys:
        if key["keyId"] == key_id:
            key.update(changes)
    return TrustRegistry.from_keys(keys)


def test_revoked_and_expired_keys_are_refused(parties: Parties) -> None:
    package = supported(parties)
    before = {"value": "2026-02-01T00:00:00Z"}
    for change in ({"revokedAt": before}, {"validUntil": before}):
        result = Verifier(trust=registry_with(parties, "erp-gateway-1", **change)).verify(package)
        assert result.refusal is not None
        assert result.refusal.code == "KEY_NOT_VALID"
    # Revoked after the statement was observed: the statement still counts.
    later = {"revokedAt": {"value": "2027-01-01T00:00:00Z"}}
    Verifier(trust=registry_with(parties, "erp-gateway-1", **later)).verify(
        package
    ).require_supported()


def test_a_key_trusted_for_another_tenant_or_source_is_refused(parties: Parties) -> None:
    package = supported(parties)
    for change, code in (
        ({"tenant": {"value": "another-tenant"}}, "TENANT_MISMATCH"),
        ({"sources": ["crm"]}, "SOURCE_NOT_AUTHORIZED"),
        ({"issuer": {"value": "00000000-0000-4000-8000-00000000ffff"}}, "ISSUER_MISMATCH"),
    ):
        result = Verifier(trust=registry_with(parties, "erp-gateway-1", **change)).verify(package)
        assert result.refusal is not None
        assert result.refusal.code == code


def test_a_misspelt_registry_member_is_an_error_not_a_default(parties: Parties) -> None:
    keys = parties.trust.to_dict()["keys"]
    keys[0]["revokedat"] = {"value": "2026-02-01T00:00:00Z"}
    with pytest.raises(TrustRegistryError):
        TrustRegistry.from_keys(keys)
    with pytest.raises(TrustRegistryError):
        TrustRegistry.from_json(b"{}")
    with pytest.raises(TrustRegistryError):
        TrustRegistry.from_json(b"not json")


def test_a_registry_cannot_alias_one_key_under_two_names(parties: Parties) -> None:
    keys = parties.trust.to_dict()["keys"]
    alias = dict(keys[0], keyId="alias")
    with pytest.raises(TrustRegistryError):
        TrustRegistry.from_keys([*keys, alias])


def test_missing_registry_file(tmp_path: Path) -> None:
    with pytest.raises(TrustRegistryError):
        TrustRegistry.load(tmp_path / "nowhere.json")


# --- expectations ------------------------------------------------------------


def test_wrong_tenant_contract_and_claim_are_refused(parties: Parties) -> None:
    package = supported(parties)
    verifier = Verifier(trust=parties.trust)
    other = WorkContract.from_dict(
        {**parties.contract.to_dict(), "identity": {"id": "invoice-posting", "version": "2.0.0"}}
    )
    for expect, code in (
        (Expectations(tenant="another-tenant"), "TENANT_NOT_EXPECTED"),
        (Expectations(contract=other), "CONTRACT_NOT_EXPECTED"),
        (Expectations(claim="00000000-0000-4000-8000-000000000000"), "CLAIM_NOT_EXPECTED"),
    ):
        result = verifier.verify(package, expect=expect)
        assert result.verification_status is VerificationStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.code == code
        assert result.decision is None
    met = verifier.verify(
        package, expect=Expectations(tenant=parties.tenant, contract=parties.contract)
    )
    assert met.expectations_met.tenant == parties.tenant
    assert met.expectations_met.contract == parties.contract.digest


# --- tampering ---------------------------------------------------------------


def test_altered_evidence_is_refused(parties: Parties) -> None:
    def change(value: dict[str, Any]) -> None:
        bodies = component(value, "evidence/bodies.json")
        record = next(item["body"]["record"] for item in bodies if "record" in item["body"])
        record["fields"]["invoice"] = "INV-999"

    verifier = Verifier(trust=parties.trust)
    assert verifier.verify(edit(supported(parties), change)).refusal.code == "COMPONENT_DIGEST"  # type: ignore[union-attr]
    # Hiding the change by recomputing every digest runs into the signature.
    resealed = verifier.verify(edit_and_reseal(supported(parties), change))
    assert resealed.refusal is not None
    assert resealed.refusal.code == "PAYLOAD_MISMATCH"


def test_an_overstated_decision_is_refused_even_when_resealed(parties: Parties) -> None:
    def overstate(value: dict[str, Any]) -> None:
        decision = component(value, "decision.json")
        decision["decision"] = "SUPPORTED"
        decision["requirements"][0]["value"] = "TRUE"

    for package in (undetermined(parties), contradicted(parties)):
        result = Verifier(trust=parties.trust).verify(edit_and_reseal(package, overstate))
        assert result.refusal is not None
        assert result.refusal.code == "DECISION_MISMATCH"
        # Without a registry the lie is not caught, and is not believed either.
        unchecked = Verifier(trust=None).verify(edit_and_reseal(package, overstate))
        assert unchecked.verification_status is VerificationStatus.INCOMPLETE
        assert unchecked.decision is None


def test_dropping_inconvenient_evidence_is_refused(parties: Parties) -> None:
    def drop(value: dict[str, Any]) -> None:
        component(value, "evidence/bodies.json").clear()
        component(value, "evidence/statements.json").clear()

    result = Verifier(trust=parties.trust).verify(edit_and_reseal(contradicted(parties), drop))
    assert result.refusal is not None
    assert result.refusal.code == "MISSING_EVIDENCE"


@settings(max_examples=150, deadline=None)
@given(data=st.data())
def test_no_single_byte_change_yields_a_supported_result(data: st.DataObject) -> None:
    parties = make_parties()
    package = supported(parties).text
    index = data.draw(st.integers(0, len(package) - 1))
    byte = data.draw(st.integers(0, 255).filter(lambda b: b != package[index]))
    altered = package[:index] + bytes([byte]) + package[index + 1 :]
    result = Verifier(trust=parties.trust).verify(altered)
    assert result.verification_status is VerificationStatus.REFUSED
    assert result.decision is None


# --- malformed and oversized input -------------------------------------------


@pytest.mark.parametrize(
    "text",
    [b"", b"not json", b"{}", b"[]", b'{"files":1}', b"\xff\xfe", b'{"a":1,"a":2}', b"0.5"],
)
def test_malformed_input_is_refused_not_crashed(text: bytes, parties: Parties) -> None:
    result = Verifier(trust=parties.trust).verify(text)
    assert result.verification_status is VerificationStatus.REFUSED
    assert result.decision is None


def test_a_reformatted_package_is_not_the_package(parties: Parties) -> None:
    pretty = json.dumps(json.loads(supported(parties).text), indent=2).encode()
    result = Verifier(trust=parties.trust).verify(pretty)
    assert result.refusal is not None
    assert result.refusal.code == "NOT_CANONICAL"


def test_resource_limits_are_errors_not_refusals(parties: Parties, tmp_path: Path) -> None:
    package = supported(parties)
    with pytest.raises(ResourceLimitError):
        Verifier(trust=parties.trust, max_bytes=100).verify(package)
    big = tmp_path / "big.json"
    big.write_bytes(b" " * 4096)
    with pytest.raises(ResourceLimitError):
        Verifier(trust=parties.trust, max_bytes=100).verify(big)
    with pytest.raises(ResourceLimitError):
        Verifier(trust=parties.trust).verify(b"[" * 100_000)
    with pytest.raises(ValueError, match="max_bytes"):
        Verifier(trust=parties.trust, max_bytes=10**12)


def test_a_file_may_end_with_exactly_one_line_end(parties: Parties, tmp_path: Path) -> None:
    package = supported(parties)
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    one.write_bytes(package.text + b"\n")
    two.write_bytes(package.text + b"\n\n")
    verifier = Verifier(trust=parties.trust)
    verifier.verify(one).require_supported()
    verifier.verify(str(one)).require_supported()
    assert verifier.verify(two).verification_status is VerificationStatus.REFUSED


# --- issuer signatures -------------------------------------------------------


def test_an_issuer_signature_is_separate_from_a_reproduced_decision(parties: Parties) -> None:
    verifier = Verifier(trust=parties.trust)
    unsigned = verifier.verify(supported(parties))
    assert unsigned.issuer_signature.status is PropertyStatus.ABSENT
    unsigned.require_supported()
    with pytest.raises(RequirementNotMet, match="issuer signature"):
        unsigned.require_supported(issuer_signed=True)
    signed = verifier.verify(supported(parties, signed=True))
    signed.require_supported(issuer_signed=True)
    assert signed.verified_issuer_keys == ("decision-issuer-1",)
    # Signed and unsigned packages share an identifier and differ in bytes.
    assert signed.package_id is not None


def test_an_evidence_key_cannot_sign_a_decision(parties: Parties) -> None:
    with pytest.raises(SigningAuthorityError, match="wvp-decision"):
        DecisionIssuer(authority=parties.gateway_authority, signer=parties.gateway_signer)
    lying = SigningAuthority(
        key_id="erp-gateway-1",
        issuer=parties.gateway_authority.issuer,
        tenant=parties.tenant,
        sources=["wvp-decision"],
    )
    work = parties.work()
    work.attach(parties.posting()).claim()
    with pytest.raises(AssemblyError, match="ISSUER_SIGNATURE_INVALID"):
        work.issue(
            trust=parties.trust,
            issuer=DecisionIssuer(authority=lying, signer=parties.gateway_signer),
        )


# --- work records ------------------------------------------------------------


def test_a_work_record_binds_one_package(parties: Parties) -> None:
    verifier = Verifier(trust=parties.trust)
    first, second = supported(parties), contradicted(parties)
    record = verifier.verify(first).work_record
    assert record is not None
    assert record.decision == "SUPPORTED"
    assert verifier.verify(first, record=record).record_matched
    mismatch = verifier.verify(second, record=record)
    assert mismatch.refusal is not None
    assert mismatch.refusal.code == "RECORD_MISMATCH"


def test_a_work_record_for_wvp_0_1_is_an_error(corpus: Path, parties: Parties) -> None:
    vector = json.loads((corpus / "wvp" / "v0.1" / "valid" / "supported.json").read_bytes())
    record = Verifier(trust=parties.trust).verify(supported(parties)).work_record
    with pytest.raises(UnsupportedOperationError):
        Verifier(trust=TrustRegistry.from_json(json.dumps(vector["registry"]))).verify(
            vector["packageJson"].encode(), record=record
        )


# --- signing authority -------------------------------------------------------


def test_an_agent_key_cannot_speak_for_the_erp(parties: Parties) -> None:
    with pytest.raises(SigningAuthorityError, match="not declared to speak for source 'erp'"):
        EvidenceSource(system="erp", authority=parties.agent_authority, signer=parties.agent_signer)
    with pytest.raises(SigningAuthorityError, match="holds key"):
        EvidenceSource(
            system="erp", authority=parties.gateway_authority, signer=parties.agent_signer
        )
    # A process that misdeclares its authority is stopped by the registry.
    lying = SigningAuthority(
        key_id="agent-runtime-1", issuer=parties.agent.id, tenant=parties.tenant, sources=["erp"]
    )
    forged = EvidenceSource(
        system="erp", authority=lying, signer=parties.agent_signer, clock=parties.clock
    ).record(
        "posting",
        {"document": "D-1", "invoice": "INV-1", "amount": 1},
        subject=parties.subject(),
    )
    work = parties.work()
    work.attach(forged).claim()
    with pytest.raises(AssemblyError, match="SOURCE_NOT_AUTHORIZED"):
        work.issue(trust=parties.trust)


def test_an_authentic_agent_trace_does_not_support_a_claim_about_the_erp(
    parties: Parties,
) -> None:
    said = parties.agent_runtime.record(
        "posting",
        {"document": "D-1", "invoice": "INV-1", "amount": 125_000},
        subject=parties.subject(),
    )
    work = parties.work()
    work.attach(said).claim()
    issued = work.issue(trust=parties.trust)
    result = Verifier(trust=parties.trust).verify(issued.package)
    # Authentic, authorized for its own source, and ignored by the contract.
    assert result.evidence_signatures.established
    assert result.signer_authority.established
    assert result.decision is Decision.UNDETERMINED
    assert result.ignored == (f"e-{said.id}",)


def test_a_signer_returning_garbage_is_refused(parties: Parties) -> None:
    class Broken:
        key_id = "erp-gateway-1"

        def sign(self, message: bytes) -> bytes:
            return b"short"

    source = EvidenceSource(system="erp", authority=parties.gateway_authority, signer=Broken())
    with pytest.raises(SigningAuthorityError, match="64 bytes"):
        source.record("posting", {"document": "D"}, subject=parties.subject())


def test_a_seed_never_appears_in_a_repr() -> None:
    signer = Ed25519Signer(key_id="k", seed=bytes([7]) * 32)
    assert "07" not in repr(signer)
    assert not hasattr(signer, "__dict__")


# --- no silent fallback ------------------------------------------------------


def test_without_the_native_extension_verification_fails_loudly(
    parties: Parties, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = supported(parties)
    _bridge._load.cache_clear()
    monkeypatch.setitem(sys.modules, "verified._native", None)
    try:
        assert _bridge.native_available() is False
        with pytest.raises(NativeUnavailableError, match="Nothing was verified"):
            Verifier(trust=parties.trust).verify(package)
        with pytest.raises(NativeUnavailableError):
            Verifier(trust=None).verify(package)
    finally:
        monkeypatch.undo()
        _bridge._load.cache_clear()
    Verifier(trust=parties.trust).verify(package).require_supported()


def test_importing_the_sdk_loads_nothing_heavy() -> None:
    code = (
        "import sys, verified, verified.integrations;"
        "bad=[m for m in ('verified._native','agents','openai','opentelemetry','asyncio',"
        "'pydantic','httpx') if m in sys.modules];"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
