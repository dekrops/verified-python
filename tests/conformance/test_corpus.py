"""The published WVP conformance corpus, run through the public Python API.

These are the same vectors the Rust and Scala implementations run
(``dekrops/wvp``, pinned as a submodule). Each expectation is compared in
full, never by refusal code alone, and no expectation is ever edited here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verified import (
    Digest,
    Expectations,
    MalformedInputError,
    TrustRegistry,
    VerificationResult,
    VerificationStatus,
    Verifier,
    WorkUnitScope,
    _bridge,
    canonicalize,
    read_history,
    work_unit,
)
from verified.errors import UnsupportedOperationError

from ..conftest import corpus_dir

pytestmark = pytest.mark.conformance

CORPUS = corpus_dir()


def files(*parts: str) -> list[Path]:
    if CORPUS is None:
        return []
    return sorted(CORPUS.joinpath(*parts).glob("*.json"))


def load(path: Path) -> Any:
    return json.loads(path.read_bytes())


def ids(paths: list[Path]) -> list[str]:
    return [f"{path.parent.parent.name}/{path.parent.name}/{path.stem}" for path in paths]


# --- canonical encoding ------------------------------------------------------


def test_canonical_encoding_vectors(corpus: Path) -> None:
    vectors = load(corpus / "canonical-hash-v1.json")
    assert vectors["canonicalizationVersion"] == "verified-json-v1"
    assert len(vectors["valid"]) == 12
    assert len(vectors["invalid"]) == 5
    for case in vectors["valid"]:
        text = case["inputJson"].encode()
        assert canonicalize(text) == case["canonicalUtf8"].encode(), case["name"]
        assert Digest.of_json(text).hex == case["sha256"], case["name"]
    for case in vectors["invalid"]:
        with pytest.raises(MalformedInputError):
            canonicalize(case["inputJson"].encode())


# --- WVP packages ------------------------------------------------------------


def stated(result: VerificationResult) -> dict[str, Any]:
    """A result in the corpus's vocabulary, as the upstream harness states it."""
    if result.verification_status is VerificationStatus.REFUSED:
        assert result.refusal is not None
        return {"accept": False, "error": result.refusal.code}
    reproduced = result.decision is not None
    issuer = result.issuer_signature.status.value.replace("_", " ")
    out: dict[str, Any] = {
        "accept": True,
        "integrity": result.integrity.established,
        "decision": result.decision.value if result.decision else None,
        "statements": result.statement_count if reproduced else None,
        "issuerSignature": issuer,
    }
    if result.contract is not None:
        out["contract"] = {
            "id": result.contract.id,
            "version": result.contract.version,
            "digest": result.contract.digest.to_wire(),
        }
        out["requirements"] = [
            {"id": item.id, "value": item.value.value} for item in result.requirements
        ]
    return out


def registry(value: Any) -> TrustRegistry | None:
    return None if value is None else TrustRegistry.from_json(json.dumps(value))


PACKAGE_VECTORS = [
    path
    for version in ("v0.1", "v0.2")
    for kind in ("valid", "must-reject", "invalid")
    for path in files("wvp", version, kind)
]


def test_the_package_corpus_is_the_published_size() -> None:
    if CORPUS is None:
        pytest.skip("no corpus")
    assert len([p for p in PACKAGE_VECTORS if "/v0.1/" in p.as_posix()]) == 26
    assert len([p for p in PACKAGE_VECTORS if "/v0.2/" in p.as_posix()]) == 28


@pytest.mark.parametrize("path", PACKAGE_VECTORS, ids=ids(PACKAGE_VECTORS))
def test_package_vector(path: Path) -> None:
    vector = load(path)
    verifier = Verifier(trust=registry(vector["registry"]), protocol=vector["protocol"])
    result = verifier.verify(vector["packageJson"].encode())
    assert stated(result) == vector["expected"]
    assert vector["expected"]["accept"] == (path.parent.name == "valid")
    # What every result must say, whatever the vector.
    assert result.source_truthfulness.status.value == "not_established"
    if vector["registry"] is None:
        assert result.verification_status is not VerificationStatus.COMPLETE
        assert result.decision is None


def test_expectation_cases(corpus: Path) -> None:
    cases = load(corpus / "wvp" / "v0.2" / "expectations.json")
    assert len(cases) == 7
    for case in cases:
        expect = case["expect"]
        contract = expect.get("contract")
        result = Verifier(trust=registry(case["registry"]), protocol="wvp-0.2").verify(
            case["packageJson"].encode(),
            expect=Expectations(
                tenant=expect.get("tenant"),
                contract=None if contract is None else Digest.from_wire(contract),
                claim=expect.get("claim"),
            ),
        )
        expected = case["expected"]
        if expected["accept"]:
            assert result.is_complete, case["description"]
            assert result.decision is not None
            assert result.decision.value == expected["decision"], case["description"]
        else:
            assert result.refusal is not None, case["description"]
            assert result.refusal.code == expected["error"], case["description"]


@pytest.mark.parametrize(
    "name", ["wvp/v0.1/examples/order-transition", "wvp/v0.2/examples/invoice-processing"]
)
def test_worked_examples_verify_as_supported(corpus: Path, name: str) -> None:
    example = corpus.parent / "protocols" / name
    result = Verifier(trust=TrustRegistry.load(example / "registry.json")).verify(
        example / "package.json"
    )
    assert result.require_supported().is_complete


def test_expectations_are_refused_for_a_version_that_does_not_define_them(corpus: Path) -> None:
    vector = load(corpus / "wvp" / "v0.1" / "valid" / "supported.json")
    with pytest.raises(UnsupportedOperationError):
        Verifier(trust=registry(vector["registry"])).verify(
            vector["packageJson"].encode(), expect=Expectations(tenant="tenant-a")
        )


# --- Work Contract Language 1 ------------------------------------------------

CONTRACT_CASES = files("work-contract", "v1", "cases")
# `72-scale-not-whole` gives a type a fractional scale. verified-json-v1 has no
# fractions, so the shared reader refuses the file's text before any contract
# is read, exactly as upstream documents. It is not counted as conforming.
UNREPRESENTABLE = {"72-scale-not-whole"}


def evaluate(contract: Any, environment: Any) -> Any:
    return _bridge.call_json(
        "evaluate_contract", json.dumps(contract).encode(), json.dumps(environment).encode()
    )


@pytest.mark.parametrize("path", CONTRACT_CASES, ids=[p.stem for p in CONTRACT_CASES])
def test_contract_case(path: Path) -> None:
    case = load(path)
    if path.stem in UNREPRESENTABLE:
        with pytest.raises(MalformedInputError):
            evaluate(case["contract"], case["environment"])
        pytest.xfail("cannot be represented in verified-json-v1; see protocol-compatibility.md")
    assert evaluate(case["contract"], case["environment"]) == case["expected"]


def test_contract_differential_batches(corpus: Path) -> None:
    batches = files("work-contract", "v1", "differential")
    assert len(batches) == 5
    total = 0
    for path in batches:
        batch = load(path)
        for case in batch["cases"]:
            assert evaluate(batch["contract"], case["environment"]) == case["expected"], path.name
            total += 1
    assert total == 641 - 81


# --- work-unit identity ------------------------------------------------------


def test_work_unit_vectors(corpus: Path) -> None:
    vectors = load(corpus / "work-unit" / "v1" / "vectors.json")
    keys = {entry["id"]: entry for entry in vectors["keys"]}
    assert len(keys) == 3
    assert len(vectors["cases"]) == 10
    for case in vectors["cases"]:
        entry = keys[case["key"]]
        scope = case["scope"]
        unit = work_unit(
            tenant=case["tenant"],
            scope=WorkUnitScope(scope["scope"], scope["operation"], tuple(scope["identity"])),
            values=case["values"],
            key=bytes.fromhex(entry["secretHex"]),
        )
        assert unit.identity == case["identityCanonical"], case["name"]
        assert unit.nullifier == f"hmac-sha-256:{case['nullifier']['hex']}", case["name"]
        assert unit.key_commitment == Digest.from_wire(entry["commitment"]), case["name"]


# --- evidence statements, chains and admission -------------------------------

STATEMENT_VECTORS = [
    path
    for kind in ("valid", "must-reject", "invalid")
    for path in files("evidence-statement", "v1", kind)
]


def digest_hex(value: dict[str, str]) -> str:
    return value["hex"]


def statement_outcome(vector: dict[str, Any], trust: bytes) -> dict[str, Any]:
    result = _bridge.call_json(
        "check_statement", vector["input"]["signedStatementJson"].encode(), trust=trust
    )
    if result["outcome"] == "refused":
        return {"accept": False, "error": result["refusal"]["code"]}
    return {
        "accept": True,
        "keyId": result["keyId"],
        "statementCanonicalUtf8": result["canonical"],
        "statementSha256": digest_hex(result["digest"]),
        "signingInputSha256": digest_hex(result["signingInputDigest"]),
    }


def chain_outcome(vector: dict[str, Any], trust: bytes) -> dict[str, Any]:
    statements = [json.loads(text) for text in vector["input"]["statements"]]
    anchor = vector["input"]["anchor"]
    result = _bridge.call_json(
        "verify_chain",
        json.dumps(statements).encode(),
        trust,
        anchor=None if anchor is None else json.dumps(anchor).encode(),
    )
    if result["outcome"] == "refused":
        return {"accept": False, "error": result["refusal"]["code"]}
    return {
        "accept": True,
        "first": result["first"],
        "last": result["last"],
        "fromGenesis": result["fromGenesis"],
        "headSha256": digest_hex(result["head"]["digest"]),
    }


def admission_outcome(vector: dict[str, Any], trust: bytes) -> dict[str, Any]:
    given = vector["input"]
    evidence = [
        {"statement": json.loads(statement), "body": json.loads(body)}
        for statement, body in zip(given["statements"], given["bodies"], strict=True)
    ]
    result = _bridge.call_json(
        "admit",
        given["tenant"]["value"],
        json.dumps([item["value"] for item in given["claim"]["evidence"]]).encode(),
        json.dumps(evidence).encode(),
        trust,
        manifest=json.dumps(
            {
                "packageId": given["packageId"],
                "claimId": given["claim"]["id"],
                "ingestedAt": given["ingestedAt"],
                "assembledAt": given["assembledAt"],
            }
        ).encode(),
    )
    if result["outcome"] == "refused":
        return {"accept": False, "error": result["refusal"]["code"]}
    return {"accept": True, "packageManifestSha256": digest_hex(result["manifestDigest"])}


# The platform's verification result of an accepted admission is not specified
# in the published material and is not computed by the shared crates.
NOT_COMPARED = {"verificationResultSha256", "verificationStatus"}


@pytest.mark.parametrize("path", STATEMENT_VECTORS, ids=ids(STATEMENT_VECTORS))
def test_evidence_statement_vector(path: Path) -> None:
    vector = load(path)
    trust = json.dumps(vector["registry"]).encode()
    outcome = {
        "statement": statement_outcome,
        "chain": chain_outcome,
        "admission": admission_outcome,
    }[vector["kind"]](vector, trust)
    expected = {k: v for k, v in vector["expected"].items() if k not in NOT_COMPARED}
    assert outcome == expected


def test_the_evidence_corpus_is_the_published_size() -> None:
    if CORPUS is None:
        pytest.skip("no corpus")
    kinds = [load(path)["kind"] for path in STATEMENT_VECTORS]
    assert (kinds.count("statement"), kinds.count("chain"), kinds.count("admission")) == (17, 13, 9)


# --- work relation v1 (draft) -------------------------------------------------


def relation_cases() -> list[dict[str, Any]]:
    if CORPUS is None:
        return []
    cases: list[dict[str, Any]] = load(CORPUS / "work-relation" / "v1" / "vectors.json")["cases"]
    return cases


RELATION_CASES = relation_cases()


@pytest.mark.parametrize("case", RELATION_CASES, ids=[case["name"] for case in RELATION_CASES])
def test_work_relation_case(case: dict[str, Any]) -> None:
    trust = TrustRegistry.from_json(json.dumps(case["trust"]).encode())
    reading = read_history(case["relations"], case["records"], trust)
    # The whole reading: every record, every relation's standing, every
    # derived relation and every stream.
    assert reading.raw == case["expected"]
    # And the typed view says what the reading says.
    assert [read.standing.value for read in reading.relations] == [
        read["standing"] for read in case["expected"]["relations"]
    ]
    assert len(reading.records) == len(case["records"])
    assert reading.records_verified is False


def test_the_work_relation_corpus_is_the_published_size() -> None:
    if CORPUS is None:
        pytest.skip("no corpus")
    assert len(RELATION_CASES) == 41
