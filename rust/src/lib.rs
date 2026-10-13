// SPDX-License-Identifier: Apache-2.0

//! `verified._native`: Python bindings to the public Work Verification
//! Protocol crates of `dekrops/verified-cli`.
//!
//! The surface is deliberately narrow. Every function takes bytes or text and
//! returns bytes or JSON text; no Python object is interpreted here and no
//! protocol rule is decided on the Python side. Canonical encoding, digests,
//! signature verification, contract evaluation, work-unit identity and the
//! thirteen package checks are the upstream crates', called directly.
//!
//! Errors that prevented an examination are raised as `NativeError(code,
//! message)`. Protocol outcomes, refusals included, are returned as data.

mod derivation;
mod evidence;
mod history;
mod issue;
mod json;
mod report;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::{Signer as _, SigningKey};
use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use verified_canonical::Value;
use verified_contract::Contract;
use verified_work_unit::{Identity, Scope, SecretKey};

use crate::json::{digest, list, object, optional, read, text, texts};

create_exception!(
    _native,
    NativeError,
    PyException,
    "An operation could not be carried out. `args` is `(code, message)`."
);

/// The revision of `dekrops/verified-cli` the verification crates are built
/// from. Kept beside the pin in `Cargo.toml`; a test compares the two.
const UPSTREAM_REVISION: &str = "d9e99f54803a1b74f0f0dd53bf1815d2238b8046";

/// The DER encoding of an Ed25519 `SubjectPublicKeyInfo` up to the key.
const SPKI_PREFIX: [u8; 12] = [
    0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00,
];

pub(crate) fn fail(code: &str, message: impl Into<String>) -> PyErr {
    NativeError::new_err((code.to_owned(), message.into()))
}

/// Verifies a package. Returns the outcome as JSON text.
#[pyfunction]
#[pyo3(signature = (package, *, trust=None, protocol=None, expect_tenant=None,
                    expect_contract=None, expect_claim=None, record=None, max_bytes=None))]
#[allow(clippy::too_many_arguments)]
fn verify(
    package: &[u8],
    trust: Option<&[u8]>,
    protocol: Option<&str>,
    expect_tenant: Option<&str>,
    expect_contract: Option<&str>,
    expect_claim: Option<&str>,
    record: Option<&[u8]>,
    max_bytes: Option<usize>,
) -> PyResult<String> {
    let trust = trust.map(report::trust).transpose()?;
    let record = record
        .map(|record| read(record, "work record", "WORK_RECORD"))
        .transpose()?;
    let request = report::Request {
        trust: trust.as_ref(),
        protocol,
        expect_tenant,
        expect_contract,
        expect_claim,
        record: record.as_ref(),
        max_bytes,
    };
    Ok(report::verify(package, &request)?.to_canonical_string())
}

/// The `verified-json-v1` canonical text of a JSON text.
#[pyfunction]
fn canonicalize<'py>(py: Python<'py>, input: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    let value = read(input, "input", "MALFORMED_JSON")?;
    Ok(PyBytes::new(py, value.to_canonical_string().as_bytes()))
}

/// The SHA-256, in hexadecimal, of a JSON text's canonical form.
#[pyfunction]
fn canonical_digest(input: &[u8]) -> PyResult<String> {
    Ok(read(input, "input", "MALFORMED_JSON")?.digest().to_hex())
}

/// Checks a trust registry and returns its keys, as the verifier reads them.
#[pyfunction]
fn trust_registry(registry: &[u8]) -> PyResult<String> {
    let trust = report::trust(registry)?;
    let keys = trust.registry().keys().iter().map(|key| {
        object([
            ("keyId", text(&key.key_id)),
            ("algorithm", text(&key.algorithm)),
            ("publicKey", text(&key.public_key)),
            ("issuer", text(&key.issuer)),
            ("tenant", text(&key.tenant)),
            ("sources", texts(&key.sources)),
            ("validFrom", text(&key.valid_from.to_string())),
            (
                "validUntil",
                optional(key.valid_until.map(|at| at.to_string()).as_deref()),
            ),
            (
                "revokedAt",
                optional(key.revoked_at.map(|at| at.to_string()).as_deref()),
            ),
        ])
    });
    Ok(object([("keys", list(keys))]).to_canonical_string())
}

/// Reads a Work Contract Language 1 contract and returns what identifies it.
#[pyfunction]
fn contract_summary(contract: &[u8]) -> PyResult<String> {
    let value = read(contract, "contract", "MALFORMED_JSON")?;
    let contract = Contract::read(&value)
        .map_err(|refusal| fail(refusal.as_str(), "the contract was refused"))?;
    Ok(object([
        ("id", text(contract.id())),
        ("version", text(contract.version())),
        ("language", text(contract.language())),
        ("semantics", text(contract.semantics())),
        ("digest", digest(&value.digest())),
        ("canonical", text(&value.to_canonical_string())),
    ])
    .to_canonical_string())
}

/// Evaluates a contract against an environment: the language's result
/// object, or `{ "refused": code }`. An evaluation is not a verification.
#[pyfunction]
fn evaluate_contract(contract: &[u8], environment: &[u8]) -> PyResult<String> {
    let contract = read(contract, "contract", "MALFORMED_JSON")?;
    let environment = read(environment, "environment", "MALFORMED_JSON")?;
    let refused = |code: &str| object([("refused", text(code))]).to_canonical_string();
    let contract = match Contract::read(&contract) {
        Ok(contract) => contract,
        Err(refusal) => return Ok(refused(refusal.as_str())),
    };
    Ok(match contract.evaluate(&environment) {
        Ok(outcome) => outcome.to_value().to_canonical_string(),
        Err(refusal) => refused(refusal.as_str()),
    })
}

/// A work unit's identity and, given the tenant's key, its nullifier and the
/// key's commitment. Give `values` (in the scope's order) or claim `inputs`.
#[pyfunction]
#[pyo3(signature = (tenant, scope, *, values=None, inputs=None, key=None))]
fn work_unit(
    tenant: &str,
    scope: &[u8],
    values: Option<&[u8]>,
    inputs: Option<&[u8]>,
    key: Option<&[u8]>,
) -> PyResult<String> {
    let unit = |error: verified_work_unit::Error| fail("WORK_UNIT", error.to_string());
    let scope = Scope::from_value(&read(scope, "scope", "WORK_UNIT")?).map_err(unit)?;
    let identity = match (values, inputs) {
        (Some(values), None) => {
            let values = read(values, "values", "WORK_UNIT")?;
            let values = values
                .as_array()
                .ok_or_else(|| fail("WORK_UNIT", "values is not a list"))?;
            Identity::new(tenant, &scope, values).map_err(unit)?
        }
        (None, Some(inputs)) => {
            Identity::of_claim(tenant, &scope, &read(inputs, "inputs", "WORK_UNIT")?)
                .map_err(unit)?
        }
        _ => return Err(fail("USAGE", "give exactly one of values and inputs")),
    };
    let mut result = verified_canonical::Object::new();
    result.insert("version", text(verified_work_unit::VERSION));
    result.insert("identity", text(&identity.canonical()));
    if let Some(key) = key {
        let key = secret_key(key)?;
        result.insert("nullifier", key.nullifier(&identity).to_value());
        result.insert("keyCommitment", digest(&key.commitment()));
    }
    Ok(Value::Object(result).to_canonical_string())
}

fn secret_key(key: &[u8]) -> PyResult<SecretKey> {
    let bytes: [u8; 32] = key
        .try_into()
        .map_err(|_| fail("USAGE", "a work-unit key is exactly 32 bytes"))?;
    Ok(SecretKey::from_bytes(bytes))
}

fn signing_key(seed: &[u8]) -> PyResult<SigningKey> {
    let bytes: [u8; 32] = seed
        .try_into()
        .map_err(|_| fail("USAGE", "an Ed25519 seed is exactly 32 bytes"))?;
    Ok(SigningKey::from_bytes(&bytes))
}

/// The public key of an Ed25519 seed, as a trust registry spells it: base64
/// of the DER `SubjectPublicKeyInfo`.
#[pyfunction]
fn ed25519_public_key(seed: &[u8]) -> PyResult<String> {
    let mut der = SPKI_PREFIX.to_vec();
    der.extend_from_slice(signing_key(seed)?.verifying_key().as_bytes());
    Ok(STANDARD.encode(der))
}

/// An Ed25519 signature over `message`, in standard base64.
#[pyfunction]
fn ed25519_sign(seed: &[u8], message: &[u8]) -> PyResult<String> {
    Ok(STANDARD.encode(signing_key(seed)?.sign(message).to_bytes()))
}

/// The bytes a signer signs for an evidence statement: the statement domain
/// followed by the statement's canonical text.
#[pyfunction]
fn statement_signing_input<'py>(
    py: Python<'py>,
    statement: &[u8],
) -> PyResult<Bound<'py, PyBytes>> {
    let statement = read(statement, "statement", "MALFORMED_JSON")?;
    let input = verified_protocol::STATEMENT_DOMAIN.signing_input(&statement);
    Ok(PyBytes::new(py, &input))
}

/// The digest of an evidence body: what a statement's `payload` states.
#[pyfunction]
fn payload_digest(body: &[u8]) -> PyResult<String> {
    Ok(issue::payload(&read(body, "body", "MALFORMED_JSON")?).to_hex())
}

/// Reads one signed statement and, given a registry, authenticates it.
#[pyfunction]
#[pyo3(signature = (signed, *, trust=None))]
fn check_statement(signed: &[u8], trust: Option<&[u8]>) -> PyResult<String> {
    let trust = trust.map(report::trust).transpose()?;
    Ok(evidence::statement(signed, trust.as_ref()).to_canonical_string())
}

/// Verifies that statements are consecutive steps of one issuer's stream.
#[pyfunction]
#[pyo3(signature = (statements, trust, *, anchor=None))]
fn verify_chain(statements: &[u8], trust: &[u8], anchor: Option<&[u8]>) -> PyResult<String> {
    let trust = report::trust(trust)?;
    let statements = read(statements, "statements", "MALFORMED_JSON")?;
    let anchor = anchor
        .map(|anchor| read(anchor, "anchor", "MALFORMED_JSON"))
        .transpose()?;
    Ok(evidence::chain(&statements, &trust, anchor.as_ref())?.to_canonical_string())
}

/// Admits statements, each with its body, as the evidence of one claim.
#[pyfunction]
#[pyo3(signature = (tenant, claimed, evidence, trust, *, manifest=None))]
fn admit(
    tenant: &str,
    claimed: &[u8],
    evidence: &[u8],
    trust: &[u8],
    manifest: Option<&[u8]>,
) -> PyResult<String> {
    let trust = report::trust(trust)?;
    let claimed = read(claimed, "claimed", "MALFORMED_JSON")?;
    let evidence_value = read(evidence, "evidence", "MALFORMED_JSON")?;
    let manifest = manifest
        .map(|manifest| read(manifest, "manifest", "MALFORMED_JSON"))
        .transpose()?;
    Ok(
        evidence::admission(tenant, &claimed, &evidence_value, &trust, manifest.as_ref())?
            .to_canonical_string(),
    )
}

/// Reads work relations against the records given with them, under `trust`
/// (work relation v1, a draft). Verifies no record.
#[pyfunction]
fn read_history(relations: &[u8], records: &[u8], trust: &[u8]) -> PyResult<String> {
    let trust = report::trust(trust)?;
    let relations = read(relations, "relations", "MALFORMED_JSON")?;
    let records = read(records, "records", "MALFORMED_JSON")?;
    Ok(history::reading(&relations, &records, &trust)?.to_canonical_string())
}

/// Replays a recomputed authorization from its evidence, under `trust`
/// (a draft, and not part of the protocol). Returns what was computed, or
/// the stage at which the presented result was not reproduced.
#[pyfunction]
fn replay_derivation(package: &[u8], trust: &[u8]) -> PyResult<String> {
    let trust = report::trust(trust)?;
    let package = read(package, "package", "MALFORMED_JSON")?;
    Ok(derivation::replayed(&package, &trust).to_canonical_string())
}

/// Lays out the statement by which a source says that records belong to one
/// group (work relation v1, a draft). Returns `{ statement, body }`; the
/// caller signs over the statement's signing input.
#[pyfunction]
#[pyo3(signature = (group, members, stated, *, stream=None, after=None))]
fn prepare_group_relation(
    group: &str,
    members: &[u8],
    stated: &[u8],
    stream: Option<&str>,
    after: Option<&[u8]>,
) -> PyResult<String> {
    let members = read(members, "members", "MALFORMED_JSON")?;
    let stated = read(stated, "stated", "MALFORMED_JSON")?;
    let after = after
        .map(|after| read(after, "after", "MALFORMED_JSON"))
        .transpose()?;
    Ok(history::group(group, &members, &stated, stream, after.as_ref())?.to_canonical_string())
}

/// Assembles a `wvp-0.2` package and verifies it under `trust`. Returns the
/// package text and the report, or raises if the verifier would not
/// reproduce the package's decision completely.
#[pyfunction]
fn assemble_package<'py>(
    py: Python<'py>,
    parts: &[u8],
    trust: &[u8],
) -> PyResult<(Bound<'py, PyBytes>, String)> {
    let trust = report::trust(trust)?;
    let (package, report) = issue::assemble(parts, &trust)?;
    Ok((
        PyBytes::new(py, package.as_bytes()),
        report.to_canonical_string(),
    ))
}

/// The bytes an issuer signs to stand behind a package's decision.
#[pyfunction]
fn decision_signing_input<'py>(py: Python<'py>, package: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    Ok(PyBytes::new(py, &issue::decision_signing_input(package)?))
}

/// Adds an issuer signature that must count under `trust`.
#[pyfunction]
fn attach_issuer_signature<'py>(
    py: Python<'py>,
    package: &[u8],
    key_id: &str,
    encoded: &str,
    trust: &[u8],
) -> PyResult<(Bound<'py, PyBytes>, String)> {
    let trust = report::trust(trust)?;
    let (package, report) = issue::attach_issuer_signature(package, key_id, encoded, &trust)?;
    Ok((
        PyBytes::new(py, package.as_bytes()),
        report.to_canonical_string(),
    ))
}

/// What this build is made of.
#[pyfunction]
fn build_info() -> String {
    object([
        ("upstream", text("https://github.com/dekrops/verified-cli")),
        ("upstreamRevision", text(UPSTREAM_REVISION)),
        (
            "verifier",
            text(&format!("verified-verifier-{UPSTREAM_REVISION}")),
        ),
        ("protocols", texts(&["wvp-0.1", "wvp-0.2"])),
        (
            "canonicalVersion",
            text(verified_canonical::CANONICAL_VERSION),
        ),
        ("contractLanguage", text(verified_contract::LANGUAGE)),
        ("contractSemantics", text(verified_contract::SEMANTICS)),
        ("workUnitVersion", text(verified_work_unit::VERSION)),
        (
            "statementProtocol",
            text(verified_protocol::STATEMENT_PROTOCOL),
        ),
        ("version", text(env!("CARGO_PKG_VERSION"))),
    ])
    .to_canonical_string()
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("NativeError", module.py().get_type::<NativeError>())?;
    module.add_function(wrap_pyfunction!(verify, module)?)?;
    module.add_function(wrap_pyfunction!(canonicalize, module)?)?;
    module.add_function(wrap_pyfunction!(canonical_digest, module)?)?;
    module.add_function(wrap_pyfunction!(trust_registry, module)?)?;
    module.add_function(wrap_pyfunction!(contract_summary, module)?)?;
    module.add_function(wrap_pyfunction!(evaluate_contract, module)?)?;
    module.add_function(wrap_pyfunction!(work_unit, module)?)?;
    module.add_function(wrap_pyfunction!(ed25519_public_key, module)?)?;
    module.add_function(wrap_pyfunction!(ed25519_sign, module)?)?;
    module.add_function(wrap_pyfunction!(statement_signing_input, module)?)?;
    module.add_function(wrap_pyfunction!(payload_digest, module)?)?;
    module.add_function(wrap_pyfunction!(check_statement, module)?)?;
    module.add_function(wrap_pyfunction!(verify_chain, module)?)?;
    module.add_function(wrap_pyfunction!(admit, module)?)?;
    module.add_function(wrap_pyfunction!(read_history, module)?)?;
    module.add_function(wrap_pyfunction!(replay_derivation, module)?)?;
    module.add_function(wrap_pyfunction!(prepare_group_relation, module)?)?;
    module.add_function(wrap_pyfunction!(assemble_package, module)?)?;
    module.add_function(wrap_pyfunction!(decision_signing_input, module)?)?;
    module.add_function(wrap_pyfunction!(attach_issuer_signature, module)?)?;
    module.add_function(wrap_pyfunction!(build_info, module)?)?;
    Ok(())
}
