// SPDX-License-Identifier: Apache-2.0

//! Package verification: one call into `verified_verifier`, and its result as
//! JSON.
//!
//! The JSON is the `verify` contract of `dekrops/verified-cli`
//! (`docs/sdk/json-output.md`), produced by the library itself
//! (`Report::to_value`), plus two members read off the inspection: `stated`,
//! holding what the package says about itself, and `verifiedIssuerKeys`.

use pyo3::PyResult;
use verified_canonical::{Limits, Sha256Digest, Value};
use verified_protocol::ProtocolVersion;
use verified_verifier::{
    Expectations, Inspection, Options, ProtocolSelection, Rejection, Trust, inspect,
};

use crate::fail;
use crate::json::{list, object, read, text, texts};

/// What a relying party supplies besides the package.
pub(crate) struct Request<'a> {
    pub(crate) trust: Option<&'a Trust>,
    pub(crate) protocol: Option<&'a str>,
    pub(crate) expect_tenant: Option<&'a str>,
    pub(crate) expect_contract: Option<&'a str>,
    pub(crate) expect_claim: Option<&'a str>,
    pub(crate) record: Option<&'a Value>,
    pub(crate) max_bytes: Option<usize>,
}

/// Reads and decodes a relying party's registry.
pub(crate) fn trust(registry: &[u8]) -> PyResult<Trust> {
    let value = read(registry, "trust registry", "TRUST_REGISTRY")?;
    Trust::from_value(&value).map_err(|error| fail("TRUST_REGISTRY", error.to_string()))
}

fn stated(inspection: &Inspection) -> Value {
    let claim = &inspection.claim;
    object([
        ("status", text("stated_by_the_package_not_verified")),
        (
            "claim",
            object([
                ("id", text(&claim.id)),
                ("claimant", text(&claim.claimant)),
                ("inputs", claim.inputs.clone().unwrap_or(Value::Null)),
            ]),
        ),
        ("recordedDecision", text(&inspection.recorded_decision)),
        ("contractReference", text(&inspection.contract_reference)),
        (
            "statements",
            list(inspection.statements.iter().map(|s| {
                object([
                    ("id", text(&s.id)),
                    ("kind", text(&s.kind)),
                    ("source", text(&s.source)),
                    ("issuer", text(&s.issuer)),
                    ("keyId", text(&s.key_id)),
                    ("observedAt", text(&s.observed_at)),
                    ("body", text(&s.body)),
                    ("claimed", Value::Bool(s.claimed)),
                ])
            })),
        ),
        (
            "issuerSignatureKeys",
            texts(&inspection.issuer_signature_keys),
        ),
        ("claimedButAbsent", texts(&inspection.claimed_but_absent)),
    ])
}

/// The report of a package that was not refused: the upstream report as the
/// library states it, and what the package says about itself.
pub(crate) fn reported(inspection: &Inspection) -> Value {
    let mut result = match inspection.report.to_value() {
        Value::Object(members) => members,
        other => return other,
    };
    result.insert(
        "verifiedIssuerKeys",
        inspection.verified_issuer_keys().map_or(Value::Null, texts),
    );
    result.insert("stated", stated(inspection));
    Value::Object(result)
}

/// Verifies a package and returns the outcome: `complete`, `incomplete` or
/// `refused`. Anything that prevented an examination is an error instead.
pub(crate) fn verify(package: &[u8], request: &Request<'_>) -> PyResult<Value> {
    let mut limits = Limits::DEFAULT;
    if let Some(max_bytes) = request.max_bytes {
        limits.max_bytes = max_bytes;
    }
    let protocol = match request.protocol {
        None => ProtocolSelection::Detect,
        Some(name) => ProtocolSelection::Require(
            name.parse::<ProtocolVersion>()
                .map_err(|error| fail("USAGE", error.to_string()))?,
        ),
    };
    let contract = request
        .expect_contract
        .map(str::parse::<Sha256Digest>)
        .transpose()
        .map_err(|_| {
            fail(
                "USAGE",
                "the expected contract digest is not 64 lowercase hexadecimal digits",
            )
        })?;
    let options = Options {
        limits,
        protocol,
        trust: request.trust,
        expectations: Expectations {
            tenant: request.expect_tenant.map(str::to_owned),
            contract,
            claim: request.expect_claim.map(str::to_owned),
        },
        record: request.record,
    };
    match inspect(package, &options) {
        Ok(inspection) => Ok(reported(&inspection)),
        Err(Rejection::Refused(refusal)) => Ok(object([
            ("outcome", text("refused")),
            (
                "refusal",
                object([
                    ("code", text(refusal.code.as_str())),
                    ("detail", text(&refusal.detail)),
                ]),
            ),
        ])),
        Err(error @ Rejection::Limit(_)) => Err(fail("RESOURCE_LIMIT", error.to_string())),
        Err(error @ Rejection::ExpectationsUndefined(_)) => {
            Err(fail("EXPECTATIONS_UNDEFINED", error.to_string()))
        }
        Err(error @ Rejection::RecordUndefined(_)) => {
            Err(fail("RECORD_UNDEFINED", error.to_string()))
        }
    }
}
