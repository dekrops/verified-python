// SPDX-License-Identifier: Apache-2.0

//! Evidence statements outside a package: authenticating one, verifying a
//! run of an issuer's stream, and admitting statements as a claim's evidence.
//! Each is one call into `verified_verifier::evidence`.

use pyo3::PyResult;
use verified_canonical::{Sha256Digest, Value};
use verified_protocol::SignedStatement;
use verified_verifier::Trust;
use verified_verifier::evidence::{Anchor, EvidenceRefusal, admit, authenticate, verify_chain};

use crate::fail;
use crate::json::{digest, member, member_text, number, object, text, wrapped};

fn refused(refusal: &EvidenceRefusal) -> Value {
    object([
        ("outcome", text("refused")),
        (
            "refusal",
            object([
                ("code", text(refusal.code.as_str())),
                ("detail", text(&refusal.detail)),
            ]),
        ),
    ])
}

fn described(outcome: &str, statement: &SignedStatement<'_>) -> Value {
    object([
        ("outcome", text(outcome)),
        ("id", text(statement.id)),
        ("keyId", text(statement.signature.key_id)),
        ("tenant", text(statement.tenant)),
        ("issuer", text(statement.issuer)),
        ("kind", text(statement.kind)),
        ("source", text(statement.source_system)),
        ("observedAt", text(&statement.observed_at.to_string())),
        ("digest", digest(&statement.digest())),
        (
            "signingInputDigest",
            digest(&Sha256Digest::of(&statement.signing_input())),
        ),
        (
            "canonical",
            text(&statement.statement.to_canonical_string()),
        ),
    ])
}

/// `authenticated` under a registry, `well_formed` without one, or `refused`.
/// Text that is not JSON at all is refused as `MALFORMED`: it is not a
/// statement.
pub(crate) fn statement(signed: &[u8], trust: Option<&Trust>) -> Value {
    let malformed = |detail: String| {
        object([
            ("outcome", text("refused")),
            (
                "refusal",
                object([("code", text("MALFORMED")), ("detail", text(&detail))]),
            ),
        ])
    };
    let value = match verified_canonical::parse(signed, &verified_canonical::Limits::DEFAULT) {
        Ok(value) => value,
        Err(error) => return malformed(error.to_string()),
    };
    match trust {
        Some(trust) => match authenticate(&value, trust) {
            Ok(authenticated) => described("authenticated", authenticated.statement()),
            Err(refusal) => refused(&refusal),
        },
        None => match SignedStatement::from_value(&value) {
            Ok(read) => described("well_formed", &read),
            Err(shape) => malformed(shape.to_string()),
        },
    }
}

fn anchor(value: &Value) -> PyResult<Anchor> {
    let bad = || {
        fail(
            "USAGE",
            "an anchor is { tenant, issuer, stream, sequence, digest }",
        )
    };
    let unwrap = |name: &str| {
        member_text(value, &[name, "value"])
            .or_else(|| member_text(value, &[name]))
            .map(str::to_owned)
            .ok_or_else(bad)
    };
    Ok(Anchor {
        tenant: unwrap("tenant")?,
        issuer: unwrap("issuer")?,
        stream: member_text(value, &["stream"]).ok_or_else(bad)?.to_owned(),
        sequence: member(value, "sequence")
            .and_then(Value::as_integer)
            .and_then(verified_canonical::Integer::to_i64)
            .ok_or_else(bad)?,
        digest: member_text(value, &["digest", "hex"])
            .and_then(|hex| hex.parse().ok())
            .ok_or_else(bad)?,
    })
}

fn anchor_json(anchor: &Anchor) -> Value {
    object([
        ("tenant", wrapped(&anchor.tenant)),
        ("issuer", wrapped(&anchor.issuer)),
        ("stream", text(&anchor.stream)),
        ("sequence", number(anchor.sequence)),
        ("digest", digest(&anchor.digest)),
    ])
}

pub(crate) fn chain(statements: &Value, trust: &Trust, from: Option<&Value>) -> PyResult<Value> {
    let statements = statements
        .as_array()
        .ok_or_else(|| fail("USAGE", "statements is not a list"))?;
    let from = from
        .filter(|value| **value != Value::Null)
        .map(anchor)
        .transpose()?;
    let mut authenticated = Vec::with_capacity(statements.len());
    for signed in statements {
        match authenticate(signed, trust) {
            Ok(statement) => authenticated.push(statement),
            Err(refusal) => return Ok(refused(&refusal)),
        }
    }
    Ok(match verify_chain(&authenticated, from.as_ref()) {
        Ok(segment) => object([
            ("outcome", text("verified")),
            ("fromGenesis", Value::Bool(segment.from_genesis)),
            ("first", number(segment.first)),
            ("last", number(segment.head.sequence)),
            ("head", anchor_json(&segment.head)),
        ]),
        Err(refusal) => refused(&refusal),
    })
}

pub(crate) fn admission(
    tenant: &str,
    claimed: &Value,
    evidence: &Value,
    trust: &Trust,
    manifest: Option<&Value>,
) -> PyResult<Value> {
    let claimed: Vec<&str> = claimed
        .as_array()
        .ok_or_else(|| fail("USAGE", "claimed is not a list"))?
        .iter()
        .map(|id| {
            id.as_str()
                .ok_or_else(|| fail("USAGE", "a claimed id is not text"))
        })
        .collect::<PyResult<_>>()?;
    let entries = evidence
        .as_array()
        .ok_or_else(|| fail("USAGE", "evidence is not a list"))?;
    let mut pairs = Vec::with_capacity(entries.len());
    for entry in entries {
        let (Some(signed), Some(body)) = (member(entry, "statement"), member(entry, "body")) else {
            return Err(fail("USAGE", "an evidence entry is { statement, body }"));
        };
        match authenticate(signed, trust) {
            Ok(statement) => pairs.push((statement, body)),
            Err(refusal) => return Ok(refused(&refusal)),
        }
    }
    let admitted = match admit(tenant, &claimed, &pairs) {
        Ok(admitted) => admitted,
        Err(refusal) => return Ok(refused(&refusal)),
    };
    let mut result = verified_canonical::Object::new();
    result.insert("outcome", text("admitted"));
    result.insert(
        "statements",
        Value::Array(admitted.statements().iter().map(|s| text(s.id)).collect()),
    );
    if let Some(manifest) = manifest {
        let part = |name: &str| member(manifest, name).cloned().unwrap_or(Value::Null);
        let manifest = admitted.manifest(
            &part("packageId"),
            &part("claimId"),
            &part("ingestedAt"),
            &part("assembledAt"),
        );
        result.insert("manifestDigest", digest(&manifest.digest()));
    }
    Ok(Value::Object(result))
}
