// SPDX-License-Identifier: Apache-2.0

//! Assembling a `wvp-0.2` package: issuing, which is not verifying.
//!
//! The upstream crates read and verify packages; they do not yet build them.
//! This module is the smallest producer that can sit on top of them:
//!
//! - the contract is read and **evaluated by `verified-contract`**;
//! - the canonical bytes, digests and signing input are `verified-canonical`'s;
//! - what is written here is only the data layout the specification fixes:
//!   the six components, the environment of WVP v0.2 section 2, the decision
//!   object of section 4, and the container.
//!
//! Because that layout is written twice (here and inside the upstream
//! verifier), nothing leaves this module unchecked: [`assemble`] hands the
//! finished text to `verified_verifier` under the caller's registry and
//! returns it only if the verifier reproduces the decision completely. A
//! package this module would get wrong is an error, never an artifact.
//!
//! See `docs/architecture/rust-python-interop.md` for the proposal to move
//! this upstream.

use std::collections::BTreeMap;

use pyo3::PyResult;
use verified_canonical::{CANONICAL_VERSION, Object, Sha256Digest, Value, cmp_keys};
use verified_contract::Contract;
use verified_protocol::{
    ComponentPath, Container, PACKAGE_VERSION, PackageId, ProtocolVersion, SignedStatement,
};
use verified_verifier::Trust;

use crate::fail;
use crate::json::{digest, list, member, member_text, number, object, read, text, wrapped};
use crate::report::{Request, verify};

const PROTOCOL: ProtocolVersion = ProtocolVersion::V0_2;

fn malformed(detail: impl Into<String>) -> pyo3::PyErr {
    fail("ASSEMBLY_INPUT", detail)
}

fn required<'a>(value: &'a Value, path: &[&str]) -> PyResult<&'a str> {
    member_text(value, path).ok_or_else(|| malformed(format!("{} is not text", path.join("."))))
}

/// One piece of evidence: a signed statement and the body it commits to.
struct Item<'a> {
    signed: &'a Value,
    body: &'a Value,
    statement: SignedStatement<'a>,
}

fn items(evidence: &Value) -> PyResult<Vec<Item<'_>>> {
    let entries = evidence
        .as_array()
        .ok_or_else(|| malformed("evidence is not a list"))?;
    let mut items = entries
        .iter()
        .map(|entry| {
            let signed = member(entry, "statement")
                .ok_or_else(|| malformed("an evidence entry has no statement"))?;
            let body =
                member(entry, "body").ok_or_else(|| malformed("an evidence entry has no body"))?;
            let statement = SignedStatement::from_value(signed)
                .map_err(|error| malformed(format!("a statement is malformed: {error}")))?;
            Ok(Item {
                signed,
                body,
                statement,
            })
        })
        .collect::<PyResult<Vec<_>>>()?;
    // Statements are carried in ascending order of identifier.
    items.sort_by_key(|item| item.statement.id);
    Ok(items)
}

/// A completeness time: a non-negative number in the contract language's
/// spelling. Whether it is admissible is the verifier's check, not ours.
fn as_of(spelling: &str) -> Option<u64> {
    let spelled = !spelling.is_empty()
        && spelling.len() <= 19
        && spelling.bytes().all(|b| b.is_ascii_digit())
        && (spelling == "0" || !spelling.starts_with('0'));
    spelled.then(|| spelling.parse().ok()).flatten()
}

/// WVP v0.2, section 2: the environment a contract is evaluated against.
fn environment(inputs: &Value, items: &[Item<'_>]) -> PyResult<Value> {
    let mut facts = Vec::new();
    let mut complete: BTreeMap<(&str, &str), (u64, &str)> = BTreeMap::new();
    for item in items {
        let source = item.statement.source_system;
        if let Some(record) = member(item.body, "record") {
            facts.push(object([
                ("id", text(&format!("e-{}", item.statement.id))),
                ("kind", text(required(record, &["kind"])?)),
                // The source is the one the signed statement names, never
                // anything a body says about itself.
                ("source", text(source)),
                (
                    "fields",
                    member(record, "fields")
                        .cloned()
                        .ok_or_else(|| malformed("a record body has no fields"))?,
                ),
            ]));
        } else if let Some(listing) = member(item.body, "complete") {
            let kind = required(listing, &["kind"])?;
            let spelling = required(listing, &["asOf"])?;
            let at = as_of(spelling)
                .ok_or_else(|| malformed("a completeness statement's asOf is not a time"))?;
            let latest = complete.entry((kind, source)).or_insert((at, spelling));
            if latest.0 < at {
                *latest = (at, spelling);
            }
        } else {
            return Err(malformed(
                "an evidence body is neither a record nor a completeness statement",
            ));
        }
    }
    let mut complete: Vec<_> = complete.into_iter().collect();
    complete.sort_by(|((k1, s1), _), ((k2, s2), _)| cmp_keys(k1, k2).then(cmp_keys(s1, s2)));
    Ok(object([
        ("inputs", inputs.clone()),
        ("facts", Value::Array(facts)),
        (
            "complete",
            list(complete.into_iter().map(|((kind, source), (_, spelling))| {
                object([
                    ("kind", text(kind)),
                    ("source", text(source)),
                    ("asOf", text(spelling)),
                ])
            })),
        ),
    ]))
}

fn container(files: [(ComponentPath, Value); 6], signatures: Value) -> (String, PackageId) {
    let manifest = object([
        ("canonicalVersion", text(CANONICAL_VERSION)),
        (
            "files",
            list(files.iter().map(|(path, content)| {
                object([
                    ("hash", digest(&content.digest())),
                    ("path", text(path.as_str())),
                ])
            })),
        ),
        ("packageVersion", number(PACKAGE_VERSION)),
        ("protocol", text(PROTOCOL.identifier())),
    ]);
    let commitment = manifest.digest();
    let id = PackageId::from_commitment(commitment);
    let package = object([
        (
            "files",
            list(files.into_iter().map(|(path, content)| {
                object([("content", content), ("path", text(path.as_str()))])
            })),
        ),
        ("manifest", manifest),
        ("packageCommitment", digest(&commitment)),
        ("packageId", text(&id.to_string())),
        ("signatures", signatures),
    ]);
    (package.to_canonical_string(), id)
}

/// Verifies a package this module produced, under the issuer's registry. A
/// package the upstream verifier does not reproduce completely is an error.
fn checked(package: &str, trust: &Trust, what: &str) -> PyResult<Value> {
    let request = Request {
        trust: Some(trust),
        protocol: Some(PROTOCOL.identifier()),
        expect_tenant: None,
        expect_contract: None,
        expect_claim: None,
        record: None,
        max_bytes: None,
    };
    let report = verify(package.as_bytes(), &request)?;
    match member_text(&report, &["outcome"]) {
        Some("complete") => Ok(report),
        Some("refused") => Err(fail(
            "ASSEMBLY_REFUSED",
            format!(
                "{what} would be refused under the registry given: {}: {}",
                member_text(&report, &["refusal", "code"]).unwrap_or("UNKNOWN"),
                member_text(&report, &["refusal", "detail"]).unwrap_or_default(),
            ),
        )),
        _ => Err(fail(
            "ASSEMBLY_REFUSED",
            format!("{what} could not be verified completely"),
        )),
    }
}

/// Assembles a `wvp-0.2` package from a contract, a claim, signed evidence
/// and evaluation metadata, and returns its text with the report of
/// verifying it under `trust`.
pub(crate) fn assemble(parts: &[u8], trust: &Trust) -> PyResult<(String, Value)> {
    let parts = read(parts, "package parts", "ASSEMBLY_INPUT")?;
    let tenant = required(&parts, &["tenant"])?;
    let contract_value =
        member(&parts, "contract").ok_or_else(|| malformed("there is no contract"))?;
    let contract = Contract::read(contract_value)
        .map_err(|refusal| fail(refusal.as_str(), "the contract is not a usable contract"))?;
    let contract_digest = contract_value.digest();
    let claim_inputs = member(&parts, "claim")
        .and_then(|claim| member(claim, "inputs"))
        .ok_or_else(|| malformed("claim.inputs is missing"))?;
    let evidence = member(&parts, "evidence").ok_or_else(|| malformed("there is no evidence"))?;
    let items = items(evidence)?;

    let outcome = contract
        .evaluate(&environment(claim_inputs, &items)?)
        .map_err(|refusal| {
            fail(
                refusal.as_str(),
                "the contract cannot be evaluated against this claim and evidence",
            )
        })?;

    let claim = object([
        ("id", wrapped(required(&parts, &["claim", "id"])?)),
        ("tenant", wrapped(tenant)),
        ("contract", digest(&contract_digest)),
        ("inputs", claim_inputs.clone()),
        (
            "claimant",
            wrapped(required(&parts, &["claim", "claimant"])?),
        ),
        (
            "evidence",
            list(items.iter().map(|item| wrapped(item.statement.id))),
        ),
        (
            "submittedAt",
            wrapped(required(&parts, &["claim", "submittedAt"])?),
        ),
    ]);
    let inputs = object([
        ("tenant", wrapped(tenant)),
        (
            "packageId",
            wrapped(required(&parts, &["evaluation", "packageId"])?),
        ),
        (
            "ingestedAt",
            wrapped(required(&parts, &["evaluation", "ingestedAt"])?),
        ),
        (
            "assembledAt",
            wrapped(required(&parts, &["evaluation", "assembledAt"])?),
        ),
        (
            "evaluatedAt",
            wrapped(required(&parts, &["evaluation", "evaluatedAt"])?),
        ),
    ]);
    let bodies = list(items.iter().map(|item| {
        object([
            ("id", wrapped(item.statement.id)),
            ("body", item.body.clone()),
        ])
    }));
    let statements = list(items.iter().map(|item| item.signed.clone()));
    let evidence_commitment =
        list(items.iter().map(|item| digest(&item.statement.digest()))).digest();

    // WVP v0.2, section 4: the evaluator's result with what it was computed
    // from.
    let evaluator = PROTOCOL.evaluator();
    let mut decision: Object = match outcome.to_value() {
        Value::Object(members) => members,
        _ => Object::new(),
    };
    decision.insert("protocol", text(PROTOCOL.identifier()));
    decision.insert(
        "evaluator",
        object([
            ("name", text(evaluator.name)),
            ("specification", text(evaluator.specification)),
        ]),
    );
    decision.insert(
        "commitments",
        object([
            ("claim", digest(&claim.digest())),
            ("contract", digest(&contract_digest)),
            ("evidence", digest(&evidence_commitment)),
            ("inputs", digest(&inputs.digest())),
        ]),
    );

    let (package, _) = container(
        [
            (ComponentPath::Claim, claim),
            (ComponentPath::Contract, contract_value.clone()),
            (ComponentPath::Decision, Value::Object(decision)),
            (ComponentPath::EvidenceBodies, bodies),
            (ComponentPath::EvidenceStatements, statements),
            (ComponentPath::Inputs, inputs),
        ],
        Value::Array(Vec::new()),
    );
    let report = checked(&package, trust, "the package")?;
    Ok((package, report))
}

fn decision_of(package: &Value) -> PyResult<(&Value, ProtocolVersion)> {
    let container = Container::from_value(package)
        .map_err(|error| fail("MALFORMED_PACKAGE", error.to_string()))?;
    let protocol = member_text(container.manifest, &["protocol"])
        .and_then(|name| name.parse::<ProtocolVersion>().ok())
        .ok_or_else(|| fail("MALFORMED_PACKAGE", "the package names no known protocol"))?;
    let decision = container
        .files
        .iter()
        .find(|file| file.path == ComponentPath::Decision.as_str())
        .map(|file| file.content)
        .ok_or_else(|| fail("MALFORMED_PACKAGE", "the package has no decision.json"))?;
    Ok((decision, protocol))
}

/// The bytes an issuer signs to stand behind a package's decision.
pub(crate) fn decision_signing_input(package: &[u8]) -> PyResult<Vec<u8>> {
    let package = read(package, "package", "MALFORMED_PACKAGE")?;
    let (decision, protocol) = decision_of(&package)?;
    Ok(protocol.decision_domain().signing_input(decision))
}

/// Adds an issuer signature to a package and returns the new text with its
/// report. The signature must count under `trust`, or nothing is returned.
pub(crate) fn attach_issuer_signature(
    package: &[u8],
    key_id: &str,
    encoded: &str,
    trust: &Trust,
) -> PyResult<(String, Value)> {
    let mut value = read(package, "package", "MALFORMED_PACKAGE")?;
    Container::from_value(&value).map_err(|error| fail("MALFORMED_PACKAGE", error.to_string()))?;
    let Value::Object(members) = &mut value else {
        return Err(fail("MALFORMED_PACKAGE", "a package is an object"));
    };
    let mut signatures = members
        .get("signatures")
        .and_then(Value::as_array)
        .map(<[Value]>::to_vec)
        .unwrap_or_default();
    signatures.push(object([
        ("encoded", text(encoded)),
        ("keyId", text(key_id)),
        ("scheme", text("Ed25519")),
    ]));
    members.insert("signatures", Value::Array(signatures));
    let package = value.to_canonical_string();
    let report = checked(&package, trust, "the signed package")?;
    Ok((package, report))
}

/// The digest of a body: what a statement's `payload` commits to.
pub(crate) fn payload(body: &Value) -> Sha256Digest {
    body.digest()
}
