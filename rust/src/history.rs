// SPDX-License-Identifier: Apache-2.0

//! Work relation v1 (draft): reading what authorities say about records.
//! One call into `verified_history::read`. No record is verified here, and
//! nothing on the Python side decides anything about a relation.

use pyo3::PyResult;
use verified_canonical::{Sha256Digest, Value};
use verified_history::{Carried, Offered, RelationDraft, prepare_relation, read};
use verified_protocol::relation::{RecordKind, Reference, Relation};
use verified_verifier::Trust;
use verified_verifier::evidence::Step;

use crate::fail;
use crate::json::{member, object};

/// The most relations, and the most records, one history may hold: the
/// reader compares each relation with each record.
const MAX_ITEMS: usize = 1024;

fn items<'a>(value: &'a Value, what: &str) -> PyResult<&'a [Value]> {
    let items = value
        .as_array()
        .ok_or_else(|| fail("MALFORMED_JSON", format!("{what} is a list")))?;
    if items.len() > MAX_ITEMS {
        return Err(fail(
            "RESOURCE_LIMIT",
            format!("{} {what}; at most {MAX_ITEMS} are read", items.len()),
        ));
    }
    Ok(items)
}

/// The reading of `relations` (each `{ statement, body }`) against `records`
/// (each `{ kind, text }`) under `trust`, in the form the conformance
/// vectors state.
pub(crate) fn reading(relations: &Value, records: &Value, trust: &Trust) -> PyResult<Value> {
    let carried = items(relations, "relations")?
        .iter()
        .map(|item| {
            Some(Carried {
                statement: member(item, "statement")?,
                body: member(item, "body")?,
            })
        })
        .collect::<Option<Vec<_>>>()
        .ok_or_else(|| fail("MALFORMED_JSON", "a relation is { statement, body }"))?;
    let offered = items(records, "records")?
        .iter()
        .map(|item| {
            Some(Offered {
                kind: member(item, "kind")?.as_str()?,
                text: member(item, "text")?.as_str()?,
            })
        })
        .collect::<Option<Vec<_>>>()
        .ok_or_else(|| fail("MALFORMED_JSON", "a record is { kind, text }"))?;
    Ok(read(&carried, &offered, trust).to_value())
}

/// The unsigned statement that says `members` belong to `group`, with the
/// relation body: `{ statement, body }`. `members` are `{ kind, hex }`, in
/// any order: a group is a set, and its one encoding orders it. `stated` are
/// the five members the source states. The statement starts `stream`,
/// follows `after`, or is not chained.
pub(crate) fn group(
    group: &str,
    members: &Value,
    stated: &Value,
    stream: Option<&str>,
    after: Option<&Value>,
) -> PyResult<Value> {
    let mut references = items(members, "members")?
        .iter()
        .map(|item| {
            let kind = RecordKind::from_name(member(item, "kind")?.as_str()?)?;
            let digest: Sha256Digest = member(item, "hex")?.as_str()?.parse().ok()?;
            Some(Reference { kind, digest })
        })
        .collect::<Option<Vec<_>>>()
        .ok_or_else(|| {
            fail(
                "USAGE",
                "a member is a record kind this version defines and a sha-256 digest",
            )
        })?;
    references.sort_by(Reference::wire_order);
    let step = match (stream, after) {
        (Some(_), Some(_)) => {
            return Err(fail(
                "USAGE",
                "a relation starts a stream or follows a statement of one, not both",
            ));
        }
        (Some(stream), None) => Step::First { stream },
        (None, Some(previous)) => Step::After(previous),
        (None, None) => Step::Unchained,
    };
    let relation = Relation::Groups {
        group,
        members: references,
    };
    let prepared = prepare_relation(&RelationDraft {
        relation: &relation,
        stated,
        step,
    })
    .map_err(|refusal| fail("USAGE", refusal.detail))?;
    Ok(object([
        ("body", prepared.body),
        ("statement", prepared.statement),
    ]))
}
