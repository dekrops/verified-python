// SPDX-License-Identifier: Apache-2.0

//! Issuing `wvp-0.2` packages: three calls into `verified_verifier::issue`.
//!
//! The contract is evaluated, the decision written and the package laid out
//! by the library that verifies packages, which returns only packages its
//! own verifier reproduces under the issuer's registry. Nothing about a
//! package's layout is decided here.

use pyo3::PyResult;
use verified_canonical::{Sha256Digest, Value};
use verified_verifier::issue::{
    Countersignature, Draft, IssueError, Issued, countersign, decision_signing_input as input,
    issue,
};
use verified_verifier::{Options, Rejection, Trust, inspect};

use crate::fail;
use crate::json::{member, member_text, read};
use crate::report::reported;

fn malformed(detail: impl Into<String>) -> pyo3::PyErr {
    fail("ASSEMBLY_INPUT", detail)
}

fn required<'a>(value: &'a Value, path: &[&str]) -> PyResult<&'a str> {
    member_text(value, path).ok_or_else(|| malformed(format!("{} is not text", path.join("."))))
}

fn refused(what: &str, error: IssueError) -> pyo3::PyErr {
    match error {
        IssueError::Refused(refusal) => fail(
            "ASSEMBLY_REFUSED",
            format!(
                "{what} would be refused under the registry given: {}: {}",
                refusal.code.as_str(),
                refusal.detail
            ),
        ),
        IssueError::Limit(limit) => fail("RESOURCE_LIMIT", limit.to_string()),
        other => malformed(other.to_string()),
    }
}

/// The issued text with its report, in the shape `verify` returns.
fn described(issued: Issued, trust: &Trust) -> PyResult<(String, Value)> {
    let options = Options {
        trust: Some(trust),
        ..Options::default()
    };
    let inspection = inspect(issued.package.as_bytes(), &options)
        .map_err(|error| fail("ASSEMBLY_REFUSED", error.to_string()))?;
    let report = reported(&inspection);
    Ok((issued.package, report))
}

/// Issues a `wvp-0.2` package from a contract, a claim, signed evidence and
/// evaluation metadata.
pub(crate) fn assemble(parts: &[u8], trust: &Trust) -> PyResult<(String, Value)> {
    let parts = read(parts, "package parts", "ASSEMBLY_INPUT")?;
    let entries = member(&parts, "evidence")
        .and_then(Value::as_array)
        .ok_or_else(|| malformed("evidence is not a list"))?;
    let evidence = entries
        .iter()
        .map(
            |entry| match (member(entry, "statement"), member(entry, "body")) {
                (Some(statement), Some(body)) => Ok((statement, body)),
                _ => Err(malformed("an evidence entry is { statement, body }")),
            },
        )
        .collect::<PyResult<Vec<_>>>()?;
    let draft = Draft {
        tenant: required(&parts, &["tenant"])?,
        contract: member(&parts, "contract").ok_or_else(|| malformed("there is no contract"))?,
        claim: required(&parts, &["claim", "id"])?,
        claimant: required(&parts, &["claim", "claimant"])?,
        inputs: member(&parts, "claim")
            .and_then(|claim| member(claim, "inputs"))
            .ok_or_else(|| malformed("claim.inputs is missing"))?,
        submitted_at: required(&parts, &["claim", "submittedAt"])?,
        evidence: &evidence,
        evidence_set: required(&parts, &["evaluation", "packageId"])?,
        ingested_at: required(&parts, &["evaluation", "ingestedAt"])?,
        assembled_at: required(&parts, &["evaluation", "assembledAt"])?,
        evaluated_at: required(&parts, &["evaluation", "evaluatedAt"])?,
    };
    let issued = issue(&draft, trust).map_err(|error| refused("the package", error))?;
    described(issued, trust)
}

/// The bytes an issuer signs to stand behind a package's decision.
pub(crate) fn decision_signing_input(package: &[u8]) -> PyResult<Vec<u8>> {
    input(package).map_err(|error| match error {
        Rejection::Limit(limit) => fail("RESOURCE_LIMIT", limit.to_string()),
        other => fail("MALFORMED_PACKAGE", other.to_string()),
    })
}

/// Adds an issuer signature to a package and returns the new text with its
/// report. The signature must count under `trust`, or nothing is returned.
pub(crate) fn attach_issuer_signature(
    package: &[u8],
    key_id: &str,
    encoded: &str,
    trust: &Trust,
) -> PyResult<(String, Value)> {
    let signature = Countersignature { key_id, encoded };
    let issued = countersign(package, &[signature], trust)
        .map_err(|error| refused("the signed package", error))?;
    described(issued, trust)
}

/// The digest of a body: what a statement's `payload` commits to.
pub(crate) fn payload(body: &Value) -> Sha256Digest {
    body.digest()
}
