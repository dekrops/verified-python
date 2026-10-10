// SPDX-License-Identifier: Apache-2.0

//! Package verification: one call into `verified_verifier`, and its result as
//! JSON.
//!
//! The JSON is the `verify` contract of `dekrops/verified-cli`
//! (`docs/sdk/json-output.md`), member for member, plus one member, `stated`,
//! holding what the package says about itself. Nothing here decides anything:
//! every value is read off the upstream report.

use pyo3::PyResult;
use verified_canonical::{Limits, Sha256Digest, Value};
use verified_protocol::ProtocolVersion;
use verified_verifier::{
    DecisionFinding, Evaluation, Expectations, Finding, Inspection, IssuerSignature, NotChecked,
    Options, ProtocolSelection, Rejection, Report, Reproduced, Trust, inspect,
};

use crate::fail;
use crate::json::{count, digest, list, object, optional, read, text, texts};

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

fn reason(reason: NotChecked) -> &'static str {
    match reason {
        NotChecked::NoTrustRegistry => "no_trust_registry",
        // An upstream reason this build does not know is still "not checked".
        _ => "unknown",
    }
}

fn finding(finding: Finding) -> Value {
    match finding {
        Finding::Established => object([("status", text("established"))]),
        Finding::NotChecked(why) => object([
            ("status", text("not_checked")),
            ("reason", text(reason(why))),
        ]),
        _ => object([("status", text("not_checked")), ("reason", text("unknown"))]),
    }
}

fn decision(finding: &DecisionFinding) -> Value {
    let DecisionFinding::Reproduced(Reproduced {
        decision,
        evaluation,
    }) = finding
    else {
        let why = match finding {
            DecisionFinding::NotChecked(why) => reason(*why),
            _ => "unknown",
        };
        // The decision a package carries is never echoed here.
        return object([("status", text("not_checked")), ("reason", text(why))]);
    };
    let mut reproduced = verified_canonical::Object::new();
    reproduced.insert("status", text("established"));
    reproduced.insert("decision", text(decision.as_str()));
    match evaluation {
        Evaluation::OrderTransition { conditions } => {
            reproduced.insert(
                "conditions",
                list(conditions.iter().map(|c| {
                    object([
                        ("id", text(c.id)),
                        ("holds", Value::Bool(c.holds)),
                        ("evidence", texts(&c.evidence)),
                    ])
                })),
            );
        }
        Evaluation::WorkContract {
            requirements,
            ignored,
            conflicts,
        } => {
            reproduced.insert(
                "requirements",
                list(
                    requirements
                        .iter()
                        .map(|r| object([("id", text(&r.id)), ("value", text(r.value.as_str()))])),
                ),
            );
            reproduced.insert("ignored", texts(ignored));
            reproduced.insert(
                "conflicts",
                list(conflicts.iter().map(|c| {
                    object([
                        ("kind", text(&c.kind)),
                        ("facts", texts(&c.facts)),
                        ("resolvedTo", optional(c.resolved_to.as_deref())),
                    ])
                })),
            );
        }
        _ => {}
    }
    Value::Object(reproduced)
}

fn issuer(issuer: IssuerSignature) -> Value {
    match issuer {
        IssuerSignature::Established { count: n } => {
            object([("status", text("established")), ("count", count(n))])
        }
        IssuerSignature::Absent => object([("status", text("absent"))]),
        IssuerSignature::NotChecked {
            carried,
            reason: why,
        } => object([
            ("status", text("not_checked")),
            ("reason", text(reason(why))),
            ("carried", count(carried)),
        ]),
        _ => object([("status", text("not_checked")), ("reason", text("unknown"))]),
    }
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

/// The report of a package that was not refused.
pub(crate) fn reported(inspection: &Inspection) -> Value {
    let report: &Report = &inspection.report;
    let complete = report.is_complete();
    let met = &report.expectations_met;
    let mut result = verified_canonical::Object::new();
    result.insert(
        "outcome",
        text(if complete { "complete" } else { "incomplete" }),
    );
    result.insert("protocol", text(report.protocol.identifier()));
    result.insert("protocolStatus", text("draft"));
    result.insert("packageId", text(&report.package_id.to_string()));
    result.insert("tenant", text(&report.tenant));
    result.insert("claim", text(&report.claim));
    result.insert("statements", count(report.statements));
    result.insert(
        "components",
        list(report.components.iter().map(|c| {
            object([
                ("path", text(c.path.as_str())),
                ("digest", digest(&c.digest)),
            ])
        })),
    );
    result.insert(
        "properties",
        object([
            ("packageIntegrity", finding(report.integrity)),
            ("evidenceSignatures", finding(report.evidence_signatures)),
            ("signerAuthority", finding(report.signer_authority)),
            ("decisionReproduced", decision(&report.decision)),
            ("issuerSignature", issuer(report.issuer_signature)),
            (
                "sourceTruthfulness",
                object([
                    ("status", text("not_established")),
                    ("reason", text("no_check_can_establish_it")),
                ]),
            ),
        ]),
    );
    result.insert(
        "expectationsMet",
        object([
            ("tenant", optional(met.tenant.as_deref())),
            (
                "contract",
                met.contract.as_ref().map_or(Value::Null, digest),
            ),
            ("claim", optional(met.claim.as_deref())),
        ]),
    );
    if let Some(contract) = &report.contract {
        result.insert(
            "contract",
            object([
                ("id", text(&contract.id)),
                ("version", text(&contract.version)),
                ("digest", digest(&contract.digest)),
            ]),
        );
    }
    if let Some(record) = &report.work_record {
        result.insert("workRecord", record.clone());
        result.insert("recordMatched", Value::Bool(report.record_matched));
    }
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
